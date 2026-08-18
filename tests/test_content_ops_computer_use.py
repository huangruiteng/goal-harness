"""Tests for content-ops's computer_use_runtime_v0 vertical slice.

These tests do two jobs at once:

1. Exercise content-ops's own stdlib-only provider/reducer boundary
   (loopx/capabilities/content_ops/computer_use_provider.py and
   computer_use_reducer.py), which is all that ships in a plain
   ``pip install loopx``.
2. Cross-validate everything that boundary builds or accepts against the
   authoritative jsonschema-based validator in
   scripts/computer_use_runtime_contract_validator.py (a ``[test]``-extras
   dev tool, not shipped). This is how the full computer_use_runtime_v0
   contract stays a real, exercised call site even though production code
   deliberately does not import jsonschema -- see the module docstring in
   computer_use_provider.py for why.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from loopx.capabilities.content_ops.computer_use_provider import (
    ContentOpsCuaContractViolation,
    FakeComputerUseProvider,
    build_content_ops_browser_action_request,
    check_action_request_shape,
    check_receipt_shape,
)
from loopx.capabilities.content_ops.computer_use_reducer import (
    apply_content_ops_browser_receipt,
    reduce_content_ops_browser_receipt,
)
from loopx.capabilities.content_ops.item_lifecycle import (
    apply_content_ops_item_event,
    build_content_ops_item,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from computer_use_runtime_contract_validator import (  # noqa: E402
    ContractViolation as RealContractViolation,
)
from computer_use_runtime_contract_validator import (  # noqa: E402
    validate_action_request as real_validate_action_request,
)
from computer_use_runtime_contract_validator import (  # noqa: E402
    validate_receipt as real_validate_receipt,
)
from computer_use_runtime_contract_validator import (  # noqa: E402
    validate_receipt_matches_request as real_validate_receipt_matches_request,
)

GOAL_ID = "loopx-content-ops-cua-showcase"
TODO_ID = "todo_content_ops_cua_showcase"
DIGEST_V1 = "sha256:" + "1" * 64


def _item() -> dict[str, Any]:
    return build_content_ops_item(
        item_id="cua-showcase-post",
        item_kind="post",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:cua-showcase-post",
        created_at="2026-08-18T09:00:00+00:00",
    )


def _approve(item: dict[str, Any], *, event_id: str, approval_ref: str) -> dict[str, Any]:
    packet = apply_content_ops_item_event(
        item,
        {
            "event_id": event_id,
            "action": "approve",
            "expected_state": item["state"],
            "expected_revision": item["revision"],
            "occurred_at": "2026-08-18T09:10:00+00:00",
            "payload": {
                "approval_ref": approval_ref,
                "revision": item["revision"],
                "content_digest": item["content_digest"],
                "effect_kind": "publish",
            },
        },
    )
    return packet["item"]


def test_draft_action_request_has_no_gate_binding_and_passes_real_validator() -> None:
    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    assert request["effect_class"] == "draft"
    assert "gate_binding" not in request
    real_validate_action_request(request)


def test_approved_action_request_binds_gate_to_approval_sequence() -> None:
    item = _apply_review_and_approve()
    assert item["approval_sequence"] == 1
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    assert request["effect_class"] == "external_write"
    assert request["gate_binding"] == {
        "gate_id": "gate_cua-showcase-post_publish",
        "revision": 1,
        "status": "open",
    }
    real_validate_action_request(request, known_gate_revision=1)
    with pytest.raises(RealContractViolation, match="stale"):
        real_validate_action_request(request, known_gate_revision=2)


def test_legacy_approved_item_needs_a_fresh_approve_before_it_can_drive_cua() -> None:
    """A content_ops_item_v0 approved before approval_sequence existed --
    e.g. handed straight from a JSON file to item-browser-request, which
    does no validation of its own -- must fail closed rather than crash or
    silently issue a request at an inferred-nothing gate revision. Only a
    fresh approve event (establishing real, CUA-aware gate identity) unlocks
    it. Also exercises build_content_ops_browser_action_request normalizing
    its raw `item` input via require_content_ops_item before reading any
    field, the same defensive pattern the rest of content-ops already uses."""

    legacy_approved = dict(_apply_review_and_approve())
    del legacy_approved["approval_sequence"]

    with pytest.raises(ContentOpsCuaContractViolation, match="positive approval_sequence"):
        build_content_ops_browser_action_request(
            item=legacy_approved, goal_id=GOAL_ID, todo_id=TODO_ID
        )

    # approve only runs from review_ready, so re-establishing gate authority
    # for an already-approved legacy item goes through revoke_approval first.
    back_to_review = apply_content_ops_item_event(
        legacy_approved,
        {
            "event_id": "event-revoke-legacy",
            "action": "revoke_approval",
            "expected_state": "approved",
            "expected_revision": 1,
            "occurred_at": "2026-08-18T09:11:00+00:00",
            "payload": {"reason": "re-establish CUA-aware gate authority"},
        },
    )["item"]
    reapproved = _approve(
        back_to_review, event_id="event-approve-legacy", approval_ref="decision:legacy-1"
    )
    assert reapproved["approval_sequence"] == 1
    request = build_content_ops_browser_action_request(
        item=reapproved, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    assert request["gate_binding"]["revision"] == 1


def _apply_review_and_approve() -> dict[str, Any]:
    item = apply_content_ops_item_event(
        _item(),
        {
            "event_id": "event-review",
            "action": "submit_review",
            "expected_state": "captured",
            "expected_revision": 1,
            "occurred_at": "2026-08-18T09:05:00+00:00",
            "payload": {},
        },
    )["item"]
    return _approve(item, event_id="event-approve-1", approval_ref="decision:cua-showcase-1")


def test_external_write_action_request_without_gate_binding_is_rejected() -> None:
    forged = {
        "schema_version": "computer_use_action_request_v0",
        "goal_id": GOAL_ID,
        "todo_id": TODO_ID,
        "provider_id": "computer_use_runtime",
        "action_unit": "content_ops_publish_after_approved_gate",
        "effect_class": "external_write",
        "write_scope": {
            "allowed_actions": ["click the approved submit control"],
            "forbidden_effect_classes": ["credential_use"],
        },
        "stop_condition": "stop if the live gate revision has changed since approval",
        "validation_target": "submit is clicked only under the exact approved gate revision",
    }
    with pytest.raises(ContentOpsCuaContractViolation, match="requires a gate_binding"):
        check_action_request_shape(forged)
    with pytest.raises(RealContractViolation):
        real_validate_action_request(forged)


def test_draft_round_trip_stops_at_gate_and_proposes_submit_review() -> None:
    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True, "unexpected_modal_present": False},
        session_reference="fake_session_1",
    )
    receipt = provider.attempt(request)
    assert receipt["stop_reason"] == "stopped_at_gate"
    real_validate_receipt(receipt)
    real_validate_receipt_matches_request(receipt, request)

    decision = reduce_content_ops_browser_receipt(item=item, action_request=request, receipt=receipt)
    assert decision["decision"] == "propose_submit_review"
    event = {
        "event_id": receipt["idempotency_key"],
        "expected_state": item["state"],
        "expected_revision": item["revision"],
        "occurred_at": "2026-08-18T09:05:00+00:00",
        **decision["proposed_event"],
    }
    packet = apply_content_ops_item_event(item, event)
    assert packet["item"]["state"] == "review_ready"
    assert packet["receipt"]["status"] == "applied"

    # Idempotent replay: the same provider retry (same idempotency_key/event_id)
    # must not be double-processed.
    replay = apply_content_ops_item_event(packet["item"], event)
    assert replay["receipt"]["status"] == "already_applied"
    assert replay["item"]["state"] == "review_ready"


def test_unknown_modal_hands_off_without_any_state_transition() -> None:
    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True, "unexpected_modal_present": True},
        session_reference="fake_session_2",
    )
    receipt = provider.attempt(request)
    assert receipt["stop_reason"] == "blocked_by_unknown_modal"
    real_validate_receipt(receipt)

    decision = reduce_content_ops_browser_receipt(item=item, action_request=request, receipt=receipt)
    assert decision["decision"] == "handoff_blocked"
    assert decision["proposed_event"] is None
    assert decision["blocker"]["item_id"] == item["item_id"]
    # The reducer proposed nothing; the item itself must be untouched.
    assert item["state"] == "captured"


def test_unreachable_screen_hands_off_without_any_state_transition() -> None:
    """The other stop_reason that means 'hand off, don't guess' --
    stop_reason=failed, when the provider can't even reach the target
    screen. Exercises FakeComputerUseProvider's screen_reachable=False branch
    and the reducer's `failed` branch, neither of which any other test in
    this file drives."""

    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": False}, session_reference="fake_session_unreachable"
    )
    receipt = provider.attempt(request)
    assert receipt["stop_reason"] == "failed"
    assert receipt["observed_facts"]["screen_reached"] is False
    real_validate_receipt(receipt)

    decision = reduce_content_ops_browser_receipt(item=item, action_request=request, receipt=receipt)
    assert decision["decision"] == "handoff_blocked"
    assert decision["proposed_event"] is None
    assert decision["blocker"]["item_id"] == item["item_id"]
    assert item["state"] == "captured"


def test_stale_gate_revision_after_revoke_and_reapprove_is_rejected() -> None:
    item = _apply_review_and_approve()
    stale_request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    assert stale_request["gate_binding"]["revision"] == 1

    revoked = apply_content_ops_item_event(
        item,
        {
            "event_id": "event-revoke",
            "action": "revoke_approval",
            "expected_state": item["state"],
            "expected_revision": item["revision"],
            "occurred_at": "2026-08-18T09:15:00+00:00",
            "payload": {"reason": "owner wants another look before publish"},
        },
    )["item"]
    reapproved = _approve(revoked, event_id="event-approve-2", approval_ref="decision:cua-showcase-2")
    assert reapproved["approval_sequence"] == 2, (
        "content revision never changed across revoke/reapprove, so only the "
        "dedicated approval_sequence counter distinguishes the two approvals"
    )

    provider = FakeComputerUseProvider(
        {"screen_reachable": True, "submit_click_permitted": True},
        session_reference="fake_session_3",
    )
    stale_receipt = provider.attempt(stale_request)
    assert stale_receipt["stop_reason"] == "completed"
    real_validate_receipt(stale_receipt)

    decision = reduce_content_ops_browser_receipt(
        item=reapproved, action_request=stale_request, receipt=stale_receipt
    )
    assert decision["decision"] == "rejected_stale_gate"
    assert decision["proposed_event"] is None

    with pytest.raises(RealContractViolation, match="stale"):
        real_validate_action_request(stale_request, known_gate_revision=2)


def test_reducer_normalizes_a_legacy_item_before_the_gate_staleness_check() -> None:
    """The receipt-side counterpart to
    test_legacy_approved_item_needs_a_fresh_approve_before_it_can_drive_cua:
    reduce_content_ops_browser_receipt must normalize its raw `item` input
    (require_content_ops_item) before reading approval_sequence for the gate
    staleness check, or a legacy item missing that field -- e.g. handed
    straight from a JSON file to item-browser-receipt, which does no
    validation of its own -- would crash with a raw KeyError instead of
    being handled by the same, already-tested logic as everywhere else."""

    item = _apply_review_and_approve()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True, "submit_click_permitted": True},
        session_reference="fake_session_legacy_receipt",
    )
    receipt = provider.attempt(request)

    legacy_item = dict(item)
    del legacy_item["approval_sequence"]

    decision = reduce_content_ops_browser_receipt(
        item=legacy_item, action_request=request, receipt=receipt
    )
    # require_content_ops_item defaults the missing field to 0, which for
    # this *already-approved* legacy item does not match the live request's
    # gate_binding.revision=1 -- so this is correctly rejected as stale, not
    # silently accepted and not a crash.
    assert decision["decision"] == "rejected_stale_gate"

    packet = apply_content_ops_browser_receipt(
        item=legacy_item,
        action_request=request,
        receipt=receipt,
        occurred_at="2026-08-18T09:20:00+00:00",
    )
    assert packet["ok"] is False
    assert packet["decision"] == "rejected_stale_gate"
    # The echoed-back item is the normalized form (approval_sequence now
    # present), not the raw legacy input -- the same "heal on every
    # read/write" behavior apply_content_ops_item_event already has.
    assert packet["item"]["approval_sequence"] == 0


def test_completed_write_consumes_the_gate_via_set_delivery_intent() -> None:
    """A completed external_write receipt must not leave the item in
    "approved" -- that would let the exact same gate issue a second,
    identical external_write request and be attempted again. The reducer
    consumes the gate by proposing set_delivery_intent (approved ->
    delivery_ready), which needs no fabricated public_url/receipt_ref --
    recording the real delivery still stays with content-ops's existing
    readback tooling, not this reducer."""

    item = _apply_review_and_approve()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True, "submit_click_permitted": True},
        session_reference="fake_session_4",
    )
    receipt = provider.attempt(request)
    real_validate_receipt(receipt)
    real_validate_action_request(request, known_gate_revision=item["approval_sequence"])

    decision = reduce_content_ops_browser_receipt(item=item, action_request=request, receipt=receipt)
    assert decision["decision"] == "confirmed_external_write_attempted"
    assert decision["proposed_event"] == {
        "action": "set_delivery_intent",
        "expected_state": "approved",
        "expected_revision": item["revision"],
        "payload": {
            "provider_id": receipt["provider_id"],
            "effect_kind": item["approval"]["effect_kind"],
        },
    }

    event = {
        "event_id": receipt["idempotency_key"],
        "occurred_at": "2026-08-18T09:20:00+00:00",
        **decision["proposed_event"],
    }
    packet = apply_content_ops_item_event(item, event)
    assert packet["item"]["state"] == "delivery_ready"


def test_completed_write_gate_cannot_be_reissued_after_it_is_consumed() -> None:
    """The negative case: once a completed receipt has consumed the gate
    (approved -> delivery_ready), building a new browser action request for
    the same item must fail rather than silently producing an identical
    external_write request that could be attempted a second time."""

    item = _apply_review_and_approve()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True, "submit_click_permitted": True},
        session_reference="fake_session_5",
    )
    receipt = provider.attempt(request)
    decision = reduce_content_ops_browser_receipt(item=item, action_request=request, receipt=receipt)
    event = {
        "event_id": receipt["idempotency_key"],
        "occurred_at": "2026-08-18T09:20:00+00:00",
        **decision["proposed_event"],
    }
    delivery_ready_item = apply_content_ops_item_event(item, event)["item"]
    assert delivery_ready_item["state"] == "delivery_ready"

    with pytest.raises(ContentOpsCuaContractViolation, match="already attempted"):
        build_content_ops_browser_action_request(
            item=delivery_ready_item, goal_id=GOAL_ID, todo_id=TODO_ID
        )


def test_provider_authored_writeback_field_is_rejected_by_both_validators() -> None:
    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True}, session_reference="fake_session_5"
    )
    receipt = dict(provider.attempt(request))
    receipt["complete_todo"] = True

    with pytest.raises(ContentOpsCuaContractViolation, match="writeback"):
        check_receipt_shape(receipt)
    with pytest.raises(RealContractViolation):
        real_validate_receipt(receipt)


def test_smuggled_credential_in_evidence_is_rejected_by_both_validators() -> None:
    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True}, session_reference="fake_session_6"
    )
    receipt = dict(provider.attempt(request))
    receipt = dict(receipt, evidence=dict(receipt["evidence"], handle_kind="session_id=abc123"))

    with pytest.raises(ContentOpsCuaContractViolation, match="smuggles"):
        check_receipt_shape(receipt)
    with pytest.raises(RealContractViolation):
        real_validate_receipt(receipt)


def _run_cli(args: list[str], *, cwd: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--format", "json", "content-ops", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode in (0, 1), result.stderr
    return json.loads(result.stdout)


def test_cli_drives_the_full_draft_until_gate_round_trip(tmp_path: Path) -> None:
    item_path = tmp_path / "item.json"
    item_path.write_text(json.dumps(_item()), encoding="utf-8")

    request_packet = _run_cli(
        [
            "item-browser-request",
            "--item-json",
            str(item_path),
            "--goal-id",
            GOAL_ID,
            "--todo-id",
            TODO_ID,
        ],
        cwd=REPO_ROOT,
    )
    assert request_packet["ok"] is True
    assert request_packet["action_request"]["effect_class"] == "draft"
    assert "gate_binding" not in request_packet["action_request"]
    assert request_packet["expected_transition"] == {
        "expected_state": "captured",
        "expected_revision": 1,
    }

    # Write the *full* item-browser-request packet (not just the inner
    # action_request) -- this is the preferred path, since it carries
    # expected_transition and stays replay-safe even after the item moves on.
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request_packet), encoding="utf-8")

    provider = FakeComputerUseProvider(
        {"screen_reachable": True}, session_reference="fake_cli_session"
    )
    receipt = provider.attempt(request_packet["action_request"])
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    receipt_packet = _run_cli(
        [
            "item-browser-receipt",
            "--item-json",
            str(item_path),
            "--action-request-json",
            str(request_path),
            "--receipt-json",
            str(receipt_path),
            "--occurred-at",
            "2026-08-18T09:05:00+00:00",
        ],
        cwd=REPO_ROOT,
    )
    assert receipt_packet["ok"] is True
    assert receipt_packet["decision"] == "propose_submit_review"
    assert receipt_packet["item"]["state"] == "review_ready"
    assert receipt_packet["transition_receipt"]["status"] == "applied"

    # Same receipt replayed (same idempotency_key -> same event_id) must be a
    # no-op -- using the *same* occurred_at as the first call, since a retry
    # of the same physical attempt is one event happening once, not two.
    updated_item_path = tmp_path / "item_after.json"
    updated_item_path.write_text(
        json.dumps(receipt_packet["item"]), encoding="utf-8"
    )
    replay_packet = _run_cli(
        [
            "item-browser-receipt",
            "--item-json",
            str(updated_item_path),
            "--action-request-json",
            str(request_path),
            "--receipt-json",
            str(receipt_path),
            "--occurred-at",
            "2026-08-18T09:05:00+00:00",
        ],
        cwd=REPO_ROOT,
    )
    assert replay_packet["ok"] is True
    assert replay_packet["transition_receipt"]["status"] == "already_applied"
    assert replay_packet["item"]["state"] == "review_ready"


def test_bare_action_request_retry_with_unrefreshed_item_is_safe_by_determinism() -> None:
    """A caller that never went through item-browser-request (no
    expected_transition sidecar) can still retry safely -- but only by
    resubmitting the exact same, unrefreshed item snapshot every time, which
    converges to the same result deterministically rather than by hitting
    apply_content_ops_item_event's idempotent-replay path."""

    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True}, session_reference="fake_bare_session"
    )
    receipt = provider.attempt(request)

    first = apply_content_ops_browser_receipt(
        item=item, action_request=request, receipt=receipt, occurred_at="2026-08-18T09:05:00+00:00"
    )
    assert first["ok"] is True
    assert first["transition_receipt"]["status"] == "applied"
    assert first["item"]["state"] == "review_ready"

    # Retry against the *same* pre-transition `item` (not first["item"]), with
    # the *same* occurred_at -- a retry describes one event happening once,
    # not a second, later one.
    second = apply_content_ops_browser_receipt(
        item=item, action_request=request, receipt=receipt, occurred_at="2026-08-18T09:05:00+00:00"
    )
    assert second["ok"] is True
    assert second["item"]["state"] == "review_ready"
    assert second["item"] == first["item"], "deterministic reapplication converges to the same item"


def test_bare_action_request_retry_against_a_refreshed_item_is_rejected_not_silently_wrong() -> None:
    """The unsafe half of the bare-path characterization: a caller that DOES
    refresh --item-json between retries (a very plausible, arguably more
    correct calling pattern) does not get silent corruption or a spurious
    already_applied -- it gets a loud, clear error, because
    reduce_content_ops_browser_receipt recomputes expected_state from
    whatever item it is given, and that recomputed value now disagrees with
    what was actually stored in last_event."""

    item = _item()
    request = build_content_ops_browser_action_request(
        item=item, goal_id=GOAL_ID, todo_id=TODO_ID
    )
    provider = FakeComputerUseProvider(
        {"screen_reachable": True}, session_reference="fake_bare_session_2"
    )
    receipt = provider.attempt(request)

    first = apply_content_ops_browser_receipt(
        item=item, action_request=request, receipt=receipt, occurred_at="2026-08-18T09:05:00+00:00"
    )
    assert first["item"]["state"] == "review_ready"

    with pytest.raises(ValueError, match="different content"):
        apply_content_ops_browser_receipt(
            item=first["item"],  # refreshed: already reflects the first transition
            action_request=request,
            receipt=receipt,
            occurred_at="2026-08-18T09:06:00+00:00",
        )

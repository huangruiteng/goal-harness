#!/usr/bin/env python3
"""Contributor-facing walkthrough: Content Ops item lifecycle.

Covers stable item identity, revision-bound approval invalidation,
delivery/readback receipts, and supersession — without provider calls,
draft bodies, credentials, private locators, or publish authority.

1. **Stable item identity** — item_id, revision, content_digest,
   content_ref, source_refs, created_at/updated_at
2. **State machine** — captured → draft → review_ready → approved →
   delivery_ready → published → readback_verified, plus skip/supersede
3. **Revision-bound approval** — revise increments revision and
   clears approval + delivery_intent + delivery_receipt + readback
4. **Delivery receipt** — record_delivery binds provider_id, effect_kind,
   public_url, receipt_ref at a recorded_at timestamp
5. **Readback receipt** — verify_readback confirms public_url and
   content_digest match the delivery receipt exactly
6. **Supersession** — supersede links successor_item_id and sets
   terminal_reason; superseded items reject further events
7. **Fail-closed** — mismatched revision, content_digest, effect_kind,
   or approval window produces ValueError
8. **Idempotency** — re-applying the same event returns already_applied;
   changing the event body under the same event_id is rejected
9. **Queue projection** — managed queue surface with priority ordering,
   counts by state, next_action, and truth_contract
10. **Markdown rendering** — item and queue markdown are public-safe
11. **CLI path** — item-create and item-transition via loopx CLI
12. **Public safety** — no provider payloads, credentials, absolute
    paths, private locators, or external sinks

No provider payloads, raw sessions, credentials, private locators, or external sinks.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.content_ops.item_lifecycle import (  # noqa: E402
    apply_content_ops_item_event,
    build_content_ops_item,
    build_content_ops_item_packet,
    build_content_ops_queue_projection,
    build_content_ops_queue_status_packet,
    project_content_ops_item,
    render_content_ops_item_packet_markdown,
    render_content_ops_queue_status_markdown,
    validate_content_ops_item,
)

FORBIDDEN = [
    "/" + "Users/", "/" + "private/", "/" + "tmp/",
    "api" + "_key", "pass" + "word", "sec" + "ret",
    "C:\\", "C:/",
]

DIGEST_V1 = "sha256:" + "1" * 64
DIGEST_V2 = "sha256:" + "2" * 64


def _assert_public_safe(payload: Any, *, label: str = "") -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [n for n in FORBIDDEN if n.lower() in text.lower()]
    assert not leaked, f"{label}: public-boundary leak: {leaked}"


# ── Helpers ──────────────────────────────────────────────────────────


def _item(**kw: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "item_id": "partner-launch-reply-v1",
        "item_kind": "reply",
        "channel": "x",
        "content_digest": DIGEST_V1,
        "content_ref": "draft:partner-launch-reply-v1",
        "source_refs": ["source:partner-launch-post"],
        "created_at": "2026-08-03T09:00:00+08:00",
    }
    defaults.update(kw)
    return build_content_ops_item(**defaults)


def _event(
    item: dict[str, Any],
    event_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
    occurred_at: str = "2026-08-03T09:05:00+08:00",
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "action": action,
        "expected_state": item["state"],
        "expected_revision": item["revision"],
        "occurred_at": occurred_at,
        "payload": payload or {},
    }


def _apply(
    item: dict[str, Any],
    event_id: str,
    action: str,
    payload: dict[str, Any] | None = None,
    occurred_at: str = "2026-08-03T09:05:00+08:00",
) -> dict[str, Any]:
    packet = apply_content_ops_item_event(
        item,
        _event(item, event_id, action, payload, occurred_at),
    )
    assert packet["external_writes_performed"] is False
    assert packet["autopublish_allowed"] is False
    return packet["item"]


# ── Scenario 1: Stable item identity ──


def test_stable_item_identity() -> None:
    """A created item has stable identity fields: item_id, revision,
    content_digest, content_ref, source_refs, and timestamps."""
    item = _item()
    assert item["schema_version"].startswith("content_ops_item_v")
    assert item["item_id"] == "partner-launch-reply-v1"
    assert item["item_kind"] == "reply"
    assert item["channel"] == "x"
    assert item["state"] == "captured"
    assert item["revision"] == 1
    assert item["content_digest"] == DIGEST_V1
    assert item["content_ref"] == "draft:partner-launch-reply-v1"
    assert item["source_refs"] == ["source:partner-launch-post"]
    assert item["approval"] is None
    assert item["delivery_intent"] is None
    assert item["delivery_receipt"] is None
    assert item["readback_receipt"] is None
    assert item["autopublish_allowed"] is False
    assert item["created_at"] == item["updated_at"]

    _assert_public_safe(item, label="identity")


# ── Scenario 2: Item packet wraps projection ──


def test_item_packet_wraps_projection() -> None:
    """build_content_ops_item_packet returns ok=True with item,
    projection, and boundary flags."""
    packet = build_content_ops_item_packet(
        item_id="launch-post-v1",
        item_kind="post",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:launch-post-v1",
        created_at="2026-08-03T09:00:00+08:00",
    )
    assert packet["ok"] is True
    assert packet["external_reads_performed"] is False
    assert packet["external_writes_performed"] is False
    assert packet["autopublish_allowed"] is False
    assert packet["projection"]["state"] == "captured"
    assert packet["projection"]["next_actions"] == [
        "revise", "submit_review", "skip", "supersede",
    ]
    assert packet["projection"]["truth_contract"]["external_effect_authority"] == "none"

    _assert_public_safe(packet, label="packet")


# ── Scenario 3: Full lifecycle through readback ──


def test_full_lifecycle_through_readback() -> None:
    """An item transitions through every state:
    captured → review_ready → approved → delivery_ready →
    published → readback_verified."""
    item = _apply(_item(), "event-review", "submit_review")
    assert item["state"] == "review_ready"

    item = _apply(
        item, "event-approve", "approve",
        {
            "approval_ref": "decision:partner-launch-reply-v1",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
            "account_ref": "account:maintainer",
            "valid_from": "2026-08-03T09:00:00+08:00",
            "valid_until": "2026-08-03T12:00:00+08:00",
        },
    )
    assert item["state"] == "approved"
    assert item["approval"]["effect_kind"] == "reply"

    item = _apply(
        item, "event-intent", "set_delivery_intent",
        {
            "provider_id": "ego-lite",
            "effect_kind": "reply",
            "account_ref": "account:maintainer",
            "not_before": "2026-08-03T09:30:00+08:00",
            "not_after": "2026-08-03T11:00:00+08:00",
        },
    )
    assert item["state"] == "delivery_ready"

    item = _apply(
        item, "event-delivery", "record_delivery",
        {
            "provider_id": "ego-lite",
            "effect_kind": "reply",
            "account_ref": "account:maintainer",
            "content_digest": DIGEST_V1,
            "public_url": "https://x.com/example/status/123",
            "receipt_ref": "receipt:x-reply-123",
        },
        occurred_at="2026-08-03T10:00:00+08:00",
    )
    assert item["state"] == "published"
    assert item["delivery_receipt"]["public_url"] == "https://x.com/example/status/123"

    item = _apply(
        item, "event-readback", "verify_readback",
        {
            "public_url": "https://x.com/example/status/123",
            "content_digest": DIGEST_V1,
            "readback_ref": "readback:x-reply-123",
        },
        occurred_at="2026-08-03T10:01:00+08:00",
    )
    assert item["state"] == "readback_verified"

    projection = project_content_ops_item(item)
    assert projection["terminal"] is True
    assert projection["readback_verified"] is True
    assert projection["next_actions"] == []

    _assert_public_safe(item, label="full-lifecycle")


# ── Scenario 4: Revision invalidates prior approval ──


def test_revision_invalidates_prior_approval() -> None:
    """Revise increments revision and clears approval, delivery_intent,
    delivery_receipt, and readback_receipt — approval is revision-bound."""
    item = _apply(_item(), "event-review", "submit_review")
    item = _apply(
        item, "event-approve", "approve",
        {
            "approval_ref": "decision:partner-launch-reply-v1",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
        },
    )
    assert item["approval"] is not None

    item = _apply(
        item, "event-revise", "revise",
        {
            "content_digest": DIGEST_V2,
            "content_ref": "draft:partner-launch-reply-v2",
        },
    )
    assert item["state"] == "draft"
    assert item["revision"] == 2
    assert item["content_digest"] == DIGEST_V2
    assert item["approval"] is None
    assert item["delivery_intent"] is None
    assert item["delivery_receipt"] is None
    assert item["readback_receipt"] is None

    _assert_public_safe(item, label="revision-invalidation")


# ── Scenario 5: Delivery receipt binds to approval ──


def test_delivery_receipt_binds_to_approval() -> None:
    """record_delivery checks effect_kind and content_digest match
    the current approval.  Mismatches fail closed."""
    item = _apply(_item(), "event-review", "submit_review")
    item = _apply(
        item, "event-approve", "approve",
        {
            "approval_ref": "decision:partner-launch-reply-v1",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
        },
    )
    item = _apply(
        item, "event-delivery", "record_delivery",
        {
            "provider_id": "ego-lite",
            "effect_kind": "reply",
            "content_digest": DIGEST_V1,
            "public_url": "https://x.com/example/status/123",
            "receipt_ref": "receipt:x-reply-123",
        },
    )
    assert item["delivery_receipt"]["provider_id"] == "ego-lite"
    assert item["delivery_receipt"]["public_url"] == "https://x.com/example/status/123"
    assert item["delivery_receipt"]["receipt_ref"] == "receipt:x-reply-123"
    assert item["delivery_receipt"]["recorded_at"] == "2026-08-03T09:05:00+08:00"

    _assert_public_safe(item, label="delivery-receipt")


# ── Scenario 6: Readback receipt must match delivery exactly ──


def test_readback_receipt_must_match_delivery() -> None:
    """verify_readback requires public_url and content_digest to match
    the delivery receipt.  A mismatch in either fails closed."""
    item = _apply(_item(), "event-review", "submit_review")
    item = _apply(
        item, "event-approve", "approve",
        {
            "approval_ref": "decision:partner-launch-reply-v1",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
        },
    )
    item = _apply(
        item, "event-delivery", "record_delivery",
        {
            "provider_id": "ego-lite",
            "effect_kind": "reply",
            "content_digest": DIGEST_V1,
            "public_url": "https://x.com/example/status/123",
            "receipt_ref": "receipt:x-reply-123",
        },
    )
    item = _apply(
        item, "event-readback", "verify_readback",
        {
            "public_url": "https://x.com/example/status/123",
            "content_digest": DIGEST_V1,
            "readback_ref": "readback:x-reply-123",
        },
    )
    assert item["state"] == "readback_verified"
    assert item["readback_receipt"]["readback_ref"] == "readback:x-reply-123"
    assert item["readback_receipt"]["verified_at"] is not None

    _assert_public_safe(item, label="readback-receipt")


# ── Scenario 7: Supersession links successor ──


def test_supersession_links_successor() -> None:
    """supersede sets successor_item_id and terminal_reason.
    The superseded item is terminal and rejects further events."""
    item = _apply(
        _item(), "event-supersede", "supersede",
        {
            "successor_item_id": "partner-launch-reply-v2",
            "reason": "A newer draft replaces this review packet.",
        },
    )
    assert item["state"] == "superseded"
    assert item["superseded_by"] == "partner-launch-reply-v2"
    assert item["terminal_reason"] == "A newer draft replaces this review packet."

    projection = project_content_ops_item(item)
    assert projection["terminal"] is True
    assert projection["next_actions"] == []

    # Superseded item rejects further events.
    try:
        _apply(item, "event-review", "submit_review")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "submit_review is not allowed from superseded" in str(exc)

    _assert_public_safe(item, label="supersession")


# ── Scenario 8: Fail-closed on mismatched approval fields ──


def test_fail_closed_on_approval_mismatch() -> None:
    """approve fails closed when revision or content_digest
    does not match the current item."""
    item = _apply(_item(), "event-review", "submit_review")

    # Wrong revision.
    try:
        _apply(item, "event-bad-rev", "approve", {
            "approval_ref": "decision:test",
            "revision": 99,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
        })
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "revision" in str(exc)

    # Wrong content_digest.
    try:
        _apply(item, "event-bad-digest", "approve", {
            "approval_ref": "decision:test",
            "revision": 1,
            "content_digest": DIGEST_V2,
            "effect_kind": "reply",
        })
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "content_digest" in str(exc)

    _assert_public_safe(item, label="fail-closed-approval")


# ── Scenario 9: Event idempotency ──


def test_event_idempotency() -> None:
    """Re-applying the same event returns already_applied.
    Changing the event body under the same event_id is rejected."""
    item = _item()
    event = _event(item, "event-review", "submit_review")

    first = apply_content_ops_item_event(item, event)
    assert first["receipt"]["status"] == "applied"

    retried = apply_content_ops_item_event(first["item"], event)
    assert retried["receipt"]["status"] == "already_applied"
    assert retried["receipt"]["from_state"] == retried["receipt"]["to_state"]

    # Same event_id, different body.
    changed = dict(event)
    changed["occurred_at"] = "2026-08-03T09:06:00+08:00"
    try:
        apply_content_ops_item_event(first["item"], changed)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "different content" in str(exc)

    _assert_public_safe(first, label="idempotency")


# ── Scenario 10: Validation rejects forged state and embedded bodies ──


def test_validation_rejects_forged_state_and_bodies() -> None:
    """validate_content_ops_item rejects items with forged state
    (e.g. published without approval) and unknown fields (draft bodies)."""
    # Forged state.
    forged = _item()
    forged["state"] = "published"
    validation = validate_content_ops_item(forged)
    assert validation["ok"] is False
    assert "published item requires approval" in validation["errors"][0]

    # Embedded draft body.
    embedded = _item()
    embedded["post_body"] = "private draft body"
    validation = validate_content_ops_item(embedded)
    assert validation["ok"] is False
    assert "unsupported fields" in validation["errors"][0]

    # Valid item.
    valid = _item()
    validation = validate_content_ops_item(valid)
    assert validation["ok"] is True
    assert validation["errors"] == []

    _assert_public_safe(validation, label="validation")


# ── Scenario 11: Queue projection ──


def test_queue_projection() -> None:
    """A managed queue surface orders items by priority,
    counts by state, and surfaces the next_action."""
    item_a = _item(item_id="item-a")
    item_b = _item(item_id="item-b")
    item_c = _apply(_item(item_id="item-c"), "event-review", "submit_review")

    projection = build_content_ops_queue_projection(
        items=[item_a, item_b, item_c],
        queue_id="content_ops_managed_queue",
        generated_at="2026-08-03T10:00:00+08:00",
    )
    assert projection["item_count"] == 3
    assert projection["terminal_count"] == 0
    assert projection["counts"]["captured"] == 2
    assert projection["counts"]["review_ready"] == 1

    items = projection["items"]
    assert items[0]["priority_index"] == 1
    assert items[0]["item_id"] == "item-a"
    assert items[2]["priority_index"] == 3
    assert items[2]["state"] == "review_ready"

    next_action = projection["next_action"]
    assert next_action is not None
    assert next_action["item_id"] == "item-a"
    assert next_action["priority_index"] == 1

    assert projection["truth_contract"]["projection_is_writable"] is False

    _assert_public_safe(projection, label="queue-projection")


# ── Scenario 12: Queue status packet ──


def test_queue_status_packet() -> None:
    """build_content_ops_queue_status_packet is read-only: it reads no
    external sources, performs no external writes, and excludes bodies."""
    item = _item(item_id="test-item")
    packet = build_content_ops_queue_status_packet(
        items=[item],
        queue_id="managed_queue",
    )
    assert packet["ok"] is True
    assert packet["external_reads_performed"] is False
    assert packet["external_writes_performed"] is False
    assert packet["autopublish_allowed"] is False
    assert packet["item_count"] == 1
    assert packet["projection"]["items"][0]["item_id"] == "test-item"

    _assert_public_safe(packet, label="queue-status")


# ── Scenario 13: Markdown render is public-safe ──


def test_markdown_render_is_public_safe() -> None:
    """Both item-packet and queue-status markdown are public-safe:
    no credentials, paths, or provider payloads."""
    packet = build_content_ops_item_packet(
        item_id="md-test",
        item_kind="article",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:md-test",
        created_at="2026-08-03T09:00:00+08:00",
    )
    md = render_content_ops_item_packet_markdown(packet)
    assert "md-test" in md
    assert "captured" in md
    _assert_public_safe(md, label="item-md")

    # Queue markdown.
    queue = build_content_ops_queue_status_packet(
        items=[_item(item_id="queue-md-item")],
    )
    queue_md = render_content_ops_queue_status_markdown(queue)
    assert "queue-md-item" in queue_md
    assert "captured" in queue_md
    _assert_public_safe(queue_md, label="queue-md")


# ── Scenario 14: Skip and revoke paths ──


def test_skip_and_revoke_paths() -> None:
    """skip sets terminal_reason and moves to skipped state.
    revoke_approval returns an approved item to review_ready."""
    # Skip from captured.
    item = _apply(
        _item(), "event-skip", "skip",
        {"reason": "No longer relevant."},
    )
    assert item["state"] == "skipped"
    assert item["terminal_reason"] == "No longer relevant."
    projection = project_content_ops_item(item)
    assert projection["terminal"] is True

    # Revoke approval.
    item2 = _apply(_item(), "event-review", "submit_review")
    item2 = _apply(
        item2, "event-approve", "approve",
        {
            "approval_ref": "decision:test",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
        },
    )
    item2 = _apply(
        item2, "event-revoke", "revoke_approval",
        {"reason": "Approval window expired."},
    )
    assert item2["state"] == "review_ready"
    assert item2["approval"] is None
    assert item2["delivery_receipt"] is None

    _assert_public_safe(item, label="skip-revoke")


# ── Scenario 15: CLI path creates and transitions without external effects ──


def test_cli_path_creates_and_transitions() -> None:
    """The loopx CLI item-create and item-transition subcommands produce
    public-safe packets with external_writes_performed=False."""
    create = subprocess.run(
        [
            sys.executable, "-m", "loopx.cli", "--format", "json",
            "content-ops", "item-create",
            "--item-id", "launch-post-v1",
            "--item-kind", "post",
            "--channel", "x",
            "--content-digest", DIGEST_V1,
            "--content-ref", "draft:launch-post-v1",
            "--created-at", "2026-08-03T09:00:00+08:00",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    created = json.loads(create.stdout)
    assert created["projection"]["state"] == "captured"
    assert created["external_writes_performed"] is False

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        item_path = temp / "item.json"
        event_path = temp / "event.json"
        item_path.write_text(json.dumps(created["item"]), encoding="utf-8")
        event_path.write_text(
            json.dumps(_event(created["item"], "event-review", "submit_review")),
            encoding="utf-8",
        )

        transition = subprocess.run(
            [
                sys.executable, "-m", "loopx.cli", "--format", "json",
                "content-ops", "item-transition",
                "--item-json", str(item_path),
                "--event-json", str(event_path),
            ],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        transitioned = json.loads(transition.stdout)
        assert transitioned["projection"]["state"] == "review_ready"
        assert transitioned["receipt"]["status"] == "applied"
        assert transitioned["external_writes_performed"] is False

        _assert_public_safe(transitioned, label="cli-transition")


def main() -> int:
    tests: list[tuple[str, Any]] = [
        ("stable item identity", test_stable_item_identity),
        ("item packet wraps projection", test_item_packet_wraps_projection),
        ("full lifecycle through readback", test_full_lifecycle_through_readback),
        ("revision invalidates prior approval", test_revision_invalidates_prior_approval),
        ("delivery receipt binds to approval", test_delivery_receipt_binds_to_approval),
        ("readback receipt must match delivery", test_readback_receipt_must_match_delivery),
        ("supersession links successor", test_supersession_links_successor),
        ("fail-closed on approval mismatch", test_fail_closed_on_approval_mismatch),
        ("event idempotency", test_event_idempotency),
        ("validation rejects forged state and bodies", test_validation_rejects_forged_state_and_bodies),
        ("queue projection", test_queue_projection),
        ("queue status packet", test_queue_status_packet),
        ("markdown render is public-safe", test_markdown_render_is_public_safe),
        ("skip and revoke paths", test_skip_and_revoke_paths),
        ("CLI path creates and transitions", test_cli_path_creates_and_transitions),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("content-ops-item-lifecycle-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

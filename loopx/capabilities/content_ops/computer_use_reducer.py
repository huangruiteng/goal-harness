"""content-ops's capability-local reducer for computer_use_runtime_v0 receipts.

Per the protocol, the reducer is deliberately not specified by the contract
itself -- it is capability-local, combining a receipt with the action request
that carried the current gate binding, plus domain policy that only
content-ops knows. This module never writes LoopX state directly: it returns
a *proposed* content-ops item-lifecycle event (or no event at all), and the
caller applies it through the existing, already-tested
``apply_content_ops_item_event`` -- the same optimistic-concurrency path used
by every other content-ops writer.

Gate identity note: ``gate_binding.revision`` is bound to the item's
``approval_sequence`` counter (loopx/capabilities/content_ops/item_lifecycle.py),
not to the item's content ``revision``. The two are independent: content
``revision`` only changes on ``revise``, but ``approval_sequence`` advances on
every ``approve`` -- including a re-approval that follows a ``revoke_approval``
with no content change in between. Reusing content ``revision`` for gate
staleness would let a revoked-then-reapproved gate collide with the revoked
one whenever the content itself never changed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Literal

from .computer_use_provider import (
    check_action_request_shape,
    check_receipt_matches_request,
    check_receipt_shape,
)
from .item_lifecycle import apply_content_ops_item_event, project_content_ops_item
from .schemas import CONTENT_OPS_BROWSER_RECEIPT_PACKET_SCHEMA_VERSION

_EVENT_ID_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

ReducerDecision = Literal[
    "propose_submit_review",
    "confirmed_external_write_attempted",
    "handoff_blocked",
    "rejected_stale_gate",
]


def reduce_content_ops_browser_receipt(
    *,
    item: Mapping[str, Any],
    action_request: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Turn one computer_use_receipt_v0 into a proposed content-ops transition.

    Returns a dict with ``decision``, ``reason``, and either
    ``proposed_event`` (to be applied via ``apply_content_ops_item_event``)
    or ``blocker`` (a human-facing report; no state change is proposed).
    """

    check_action_request_shape(action_request)
    check_receipt_shape(receipt)
    check_receipt_matches_request(receipt, action_request)

    gate_binding = action_request.get("gate_binding")
    if gate_binding is not None:
        current_approval_sequence = int(item["approval_sequence"])
        requested_revision = int(gate_binding["revision"])
        if requested_revision != current_approval_sequence:
            return {
                "decision": "rejected_stale_gate",
                "reason": (
                    f"action_request gate_binding.revision={requested_revision} does not "
                    f"match the item's current approval_sequence={current_approval_sequence}; "
                    "the approval this request was authorized under has since been revoked "
                    "and/or replaced"
                ),
                "proposed_event": None,
            }

    stop_reason = receipt["stop_reason"]

    if stop_reason == "blocked_by_unknown_modal":
        return {
            "decision": "handoff_blocked",
            "reason": (
                "provider reported an unrecognized modal and stopped rather than "
                "clicking through it; hand off to a human"
            ),
            "proposed_event": None,
            "blocker": {
                "item_id": item["item_id"],
                "attempted_action_unit": receipt["attempted_action_unit"],
                "evidence_handle": receipt["evidence"]["handle_kind"],
                "session_reference": receipt["session_reference"],
            },
        }

    if stop_reason == "failed":
        return {
            "decision": "handoff_blocked",
            "reason": "provider could not reach the target screen",
            "proposed_event": None,
            "blocker": {
                "item_id": item["item_id"],
                "attempted_action_unit": receipt["attempted_action_unit"],
                "evidence_handle": receipt["evidence"]["handle_kind"],
                "session_reference": receipt["session_reference"],
            },
        }

    if stop_reason == "stopped_at_gate":
        return {
            "decision": "propose_submit_review",
            "reason": "provider stopped at the final submit control as instructed",
            "proposed_event": {
                "action": "submit_review",
                "expected_state": item["state"],
                "expected_revision": item["revision"],
                "payload": {},
            },
        }

    if stop_reason == "completed":
        if action_request.get("effect_class") != "external_write":
            raise ValueError(
                "a 'completed' receipt for a request whose effect_class is not "
                "external_write is out of contract for this reducer"
            )
        return {
            "decision": "confirmed_external_write_attempted",
            "reason": (
                "provider reports the approved write completed; recording a durable "
                "public_url/receipt_ref is content-ops's existing readback-verified "
                "delivery flow, not something a compact CUA receipt can carry -- "
                "the receipt schema has no field for it"
            ),
            "proposed_event": None,
        }

    raise ValueError(f"unsupported receipt.stop_reason {stop_reason!r}")


def _event_id_from_idempotency_key(idempotency_key: str) -> str:
    """content-ops item events require an opaque token id; a receipt's
    idempotency_key is a looser 1-200 char string with no such constraint.
    Reuse it directly when it already fits, otherwise derive a stable token
    so the same idempotency_key always maps to the same event_id and a
    provider retry lands on content-ops's existing idempotent-replay path."""

    if _EVENT_ID_TOKEN_RE.fullmatch(idempotency_key):
        return idempotency_key
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"cua_receipt_{digest}"


def apply_content_ops_browser_receipt(
    *,
    item: Mapping[str, Any],
    action_request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    occurred_at: str,
    expected_transition: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """CLI-facing wrapper: reduce a receipt and, if it proposes one, apply the
    transition through the existing, already-tested item-lifecycle event path.

    A rejected-as-stale receipt or a handoff never touches item state; the
    caller gets back the item exactly as it was.

    ``expected_transition`` should be the ``expected_transition`` sidecar from
    the ``item-browser-request`` packet that produced ``action_request`` --
    i.e. the item's state/revision *at request-build time*, not whatever the
    item's state happens to be right now. Passing it makes a receipt replay
    safe even after the item has already moved on: the same
    idempotency_key always builds the exact same event body, so
    ``apply_content_ops_item_event``'s own digest-based idempotent-replay
    check (not a bespoke one here) is what recognizes the retry and no-ops it.

    Without it (a caller that hand-built ``action_request`` without going
    through ``item-browser-request``), expected_state/expected_revision are
    read from ``item`` fresh on every call. That is only replay-safe if the
    caller keeps re-submitting the *same, unrefreshed* item snapshot on every
    retry (safe by determinism, not by the idempotent-replay path); a caller
    that refreshes the item between retries will get a clear
    "reused with different content" error rather than a silently wrong
    result -- see test_bare_action_request_retry_against_a_refreshed_item_is_rejected_not_silently_wrong.
    """

    decision = reduce_content_ops_browser_receipt(
        item=item, action_request=action_request, receipt=receipt
    )
    base = {
        "schema_version": CONTENT_OPS_BROWSER_RECEIPT_PACKET_SCHEMA_VERSION,
        "decision": decision["decision"],
        "reason": decision["reason"],
    }
    if "blocker" in decision:
        base["blocker"] = decision["blocker"]

    if decision["decision"] == "rejected_stale_gate":
        return {
            **base,
            "ok": False,
            "item": dict(item),
            "projection": project_content_ops_item(item),
        }

    if decision["proposed_event"] is None:
        return {
            **base,
            "ok": True,
            "item": dict(item),
            "projection": project_content_ops_item(item),
        }

    proposed_event = dict(decision["proposed_event"])
    if expected_transition is not None:
        proposed_event["expected_state"] = expected_transition["expected_state"]
        proposed_event["expected_revision"] = expected_transition["expected_revision"]

    event = {
        "event_id": _event_id_from_idempotency_key(str(receipt["idempotency_key"])),
        "occurred_at": occurred_at,
        **proposed_event,
    }
    transition_packet = apply_content_ops_item_event(item, event)
    return {
        **base,
        "ok": True,
        "item": transition_packet["item"],
        "projection": transition_packet["projection"],
        "transition_receipt": transition_packet["receipt"],
    }


def render_content_ops_browser_receipt_markdown(packet: Mapping[str, Any]) -> str:
    raw_projection = packet.get("projection")
    projection: Mapping[str, Any] = raw_projection if isinstance(raw_projection, Mapping) else {}
    lines = [
        "# LoopX Content-Ops Browser Receipt",
        "",
        f"- ok: `{packet.get('ok')}`",
        f"- decision: `{packet.get('decision')}`",
        f"- reason: {packet.get('reason')}",
        f"- item_id: `{projection.get('item_id')}`",
        f"- state: `{projection.get('state')}`",
    ]
    raw_blocker = packet.get("blocker")
    blocker: Mapping[str, Any] | None = raw_blocker if isinstance(raw_blocker, Mapping) else None
    if blocker:
        lines.extend(
            [
                "",
                "## Blocker",
                "",
                f"- attempted_action_unit: `{blocker.get('attempted_action_unit')}`",
                f"- evidence_handle: `{blocker.get('evidence_handle')}`",
            ]
        )
    raw_transition_receipt = packet.get("transition_receipt")
    transition_receipt: Mapping[str, Any] | None = (
        raw_transition_receipt if isinstance(raw_transition_receipt, Mapping) else None
    )
    if transition_receipt:
        lines.extend(
            [
                "",
                "## Transition",
                "",
                f"- transition_status: `{transition_receipt.get('status')}`",
                f"- transition: `{transition_receipt.get('from_state')} -> {transition_receipt.get('to_state')}`",
            ]
        )
    return "\n".join(lines) + "\n"

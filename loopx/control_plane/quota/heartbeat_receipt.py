from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ...rollout_event_log import load_rollout_events, rollout_event_log_path
from .effect_program import SETTLEMENT_IDENTITY_SCHEMA_VERSION

HEARTBEAT_RECEIPT_SCHEMA_VERSION = "heartbeat_quota_receipt_v0"


def find_heartbeat_receipt(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str,
    turn_instance_id: str,
) -> dict[str, object] | None:
    events = load_rollout_events(rollout_event_log_path(runtime_root, goal_id))
    for event in reversed(events):
        if (
            event.get("event_kind") == "quota_should_run"
            and str(event.get("goal_id") or "") == goal_id
            and str(event.get("agent_id") or "") == agent_id
            and str(event.get("run_id") or "") == turn_instance_id
        ):
            return event
    return None


def heartbeat_receipt_view(
    event: Mapping[str, object],
    *,
    turn_instance_id: str,
    status: str,
) -> dict[str, object]:
    details_value = event.get("details")
    details: Mapping[str, object] = (
        details_value if isinstance(details_value, Mapping) else {}
    )
    receipt: dict[str, object] = {
        "schema_version": HEARTBEAT_RECEIPT_SCHEMA_VERSION,
        "turn_instance_id": turn_instance_id,
        "status": status,
        "stall_observation": str(details.get("stall_observation") or "not_applicable"),
        "event_id": event.get("event_id"),
        "recorded_at": event.get("recorded_at"),
    }
    todo_id = str(details.get("todo_id") or "").strip()
    effect_id = str(details.get("settlement_effect_id") or "").strip()
    if todo_id and effect_id:
        receipt["settlement_identity"] = {
            "schema_version": SETTLEMENT_IDENTITY_SCHEMA_VERSION,
            "effect_id": effect_id,
            "goal_id": event.get("goal_id"),
            "agent_id": event.get("agent_id"),
            "todo_id": todo_id,
            "turn_instance_id": turn_instance_id,
        }
    return receipt


def fail_heartbeat_receipt(
    payload: dict[str, object],
    *,
    turn_instance_id: str,
    stall_observation: str,
    reason: str,
) -> None:
    payload.update(
        {
            "ok": False,
            "decision": "skip",
            "should_run": False,
            "effective_action": "heartbeat_receipt_write_failed",
            "state": "blocked_health",
            "waiting_on": "codex",
            "reason": reason,
            "recommended_action": (
                "retry quota should-run with the same --turn-instance-id after "
                "repairing heartbeat receipt writeback"
            ),
            "heartbeat_receipt": {
                "schema_version": HEARTBEAT_RECEIPT_SCHEMA_VERSION,
                "turn_instance_id": turn_instance_id,
                "status": "write_failed",
                "stall_observation": stall_observation,
            },
        }
    )

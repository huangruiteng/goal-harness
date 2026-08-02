from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ...rollout_event_log import load_rollout_events, rollout_event_log_path

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
    details = event.get("details") if isinstance(event.get("details"), Mapping) else {}
    return {
        "schema_version": HEARTBEAT_RECEIPT_SCHEMA_VERSION,
        "turn_instance_id": turn_instance_id,
        "status": status,
        "stall_observation": str(details.get("stall_observation") or "not_applicable"),
        "event_id": event.get("event_id"),
        "recorded_at": event.get("recorded_at"),
    }


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

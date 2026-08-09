from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ...file_lock import exclusive_file_lock
from ...rollout_event_log import (
    ROLLOUT_EVENT_SCHEMA_VERSION,
    build_rollout_event,
    load_rollout_events,
    rollout_event_log_path,
)
from .effect_program import SETTLEMENT_IDENTITY_SCHEMA_VERSION, SettlementIdentity

HEARTBEAT_RECEIPT_SCHEMA_VERSION = "heartbeat_quota_receipt_v0"


def _heartbeat_receipt_events(
    events: list[dict[str, object]],
    *,
    goal_id: str,
    agent_id: str,
    turn_instance_id: str,
) -> list[dict[str, object]]:
    return [
        event
        for event in events
        if event.get("event_kind") == "quota_should_run"
        and str(event.get("goal_id") or "") == goal_id
        and str(event.get("agent_id") or "") == agent_id
        and str(event.get("run_id") or "") == turn_instance_id
    ]


def _receipt_settlement_identity(
    event: Mapping[str, object],
) -> tuple[str, str] | None:
    details_value = event.get("details")
    details: Mapping[str, object] = (
        details_value if isinstance(details_value, Mapping) else {}
    )
    todo_id = str(details.get("todo_id") or "").strip()
    effect_id = str(details.get("settlement_effect_id") or "").strip()
    if effect_id and not todo_id:
        raise ValueError(
            "heartbeat receipt has an effect identity without a Todo; refuse to "
            "infer or upgrade it"
        )
    if not todo_id:
        return None
    if not effect_id:
        goal_id = str(event.get("goal_id") or "").strip()
        agent_id = str(event.get("agent_id") or "").strip()
        turn_instance_id = str(event.get("run_id") or "").strip()
        effect_id = SettlementIdentity(
            goal_id=goal_id,
            agent_id=agent_id,
            todo_id=todo_id,
            turn_instance_id=turn_instance_id,
        ).effect_id
    return todo_id, effect_id


def _effective_heartbeat_receipt(
    events: list[dict[str, object]],
) -> dict[str, object] | None:
    if not events:
        return None
    identities: dict[tuple[str, str], dict[str, object]] = {}
    for event in events:
        identity = _receipt_settlement_identity(event)
        if identity is not None:
            identities[identity] = event
    if len(identities) > 1:
        raise ValueError(
            "heartbeat receipt has conflicting settlement identities for the "
            "same goal, agent, and turn"
        )
    if identities:
        return next(iter(identities.values()))
    return events[-1]


def find_heartbeat_receipt(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str,
    turn_instance_id: str,
) -> dict[str, object] | None:
    events = load_rollout_events(rollout_event_log_path(runtime_root, goal_id))
    return _effective_heartbeat_receipt(
        _heartbeat_receipt_events(
            events,
            goal_id=goal_id,
            agent_id=agent_id,
            turn_instance_id=turn_instance_id,
        )
    )


def upgrade_identityless_heartbeat_receipt(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str,
    turn_instance_id: str,
    todo_id: str,
    settlement_effect_id: str,
    status: str,
    summary: str,
    details: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    """Append one settlement-bound receipt after an identity-less same-turn guard.

    The correction is append-only and serialized with the rollout log lock. A
    matching correction replays, a legacy Todo-only receipt gains its derived
    effect id, and effect-only or conflicting identities fail closed.
    """

    normalized_todo_id = str(todo_id).strip()
    normalized_effect_id = str(settlement_effect_id).strip()
    expected_effect_id = SettlementIdentity(
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=normalized_todo_id,
        turn_instance_id=turn_instance_id,
    ).effect_id
    if not normalized_todo_id or normalized_effect_id != expected_effect_id:
        raise ValueError(
            "heartbeat receipt upgrade requires the deterministic selected Todo "
            "settlement identity"
        )

    log_path = rollout_event_log_path(runtime_root, goal_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(log_path):
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        events: list[dict[str, object]] = []
        for line in lines:
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(parsed, dict)
                and parsed.get("schema_version") == ROLLOUT_EVENT_SCHEMA_VERSION
            ):
                events.append(parsed)
        matching = _heartbeat_receipt_events(
            events,
            goal_id=goal_id,
            agent_id=agent_id,
            turn_instance_id=turn_instance_id,
        )
        effective = _effective_heartbeat_receipt(matching)
        if effective is None:
            raise ValueError(
                "identity-less heartbeat receipt is missing; rerun the original guard"
            )
        existing_identity = _receipt_settlement_identity(effective)
        expected_identity = (normalized_todo_id, normalized_effect_id)
        if existing_identity is not None:
            if existing_identity != expected_identity:
                raise ValueError(
                    "heartbeat receipt settlement identity conflicts with the "
                    "current selected Todo"
                )
            existing_details_value = effective.get("details")
            existing_details = (
                existing_details_value
                if isinstance(existing_details_value, Mapping)
                else {}
            )
            if str(existing_details.get("settlement_effect_id") or "").strip():
                return effective, False

        corrected_details = dict(details)
        corrected_details.update(
            {
                "turn_instance_id": turn_instance_id,
                "todo_id": normalized_todo_id,
                "settlement_effect_id": normalized_effect_id,
                "settlement_receipt_revision": "identity_upgrade",
            }
        )
        source_event_id = str(effective.get("event_id") or "").strip() or None
        corrected = build_rollout_event(
            goal_id=goal_id,
            event_kind="quota_should_run",
            agent_id=agent_id,
            todo_id=normalized_todo_id,
            run_id=turn_instance_id,
            status=status,
            summary=summary,
            source_event_id=source_event_id,
            caused_by=source_event_id,
            details=corrected_details,
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(corrected, sort_keys=True, ensure_ascii=False) + "\n")
        return corrected, True


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

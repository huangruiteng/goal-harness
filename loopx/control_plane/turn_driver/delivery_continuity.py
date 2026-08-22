from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..todos.contract import (
    TODO_STATUS_OPEN,
    normalize_todo_claimed_by,
    normalize_todo_id,
    normalize_todo_status,
)
from ..todos.projection import todo_item_task_class


DELIVERY_CONTINUITY_REQUEST_SCHEMA = "loopx_delivery_continuity_request_v0"
DELIVERY_CONTINUITY_RESULT_SCHEMA = "loopx_delivery_continuity_result_v0"
DELIVERY_BOUNDARY_REQUEST_SCHEMA = "loopx_delivery_boundary_request_v0"
DELIVERY_BOUNDARY_RESULT_SCHEMA = "loopx_delivery_boundary_result_v0"
DELIVERY_BOUNDARY_IN_FLIGHT = "in_flight_continuation"
DELIVERY_BOUNDARY_SEMANTIC_CLOSEOUT = "semantic_closeout"
DELIVERY_BOUNDARY_VALUES = (
    DELIVERY_BOUNDARY_IN_FLIGHT,
    DELIVERY_BOUNDARY_SEMANTIC_CLOSEOUT,
)
DELIVERY_CONTINUITY_DECISIONS = {
    "resume_in_flight",
    "release_for_reselection",
    "preempt",
}
DELIVERY_CONTINUITY_PREEMPTIONS = {
    "heartbeat_receipt",
    "blocking_work_lane",
    "autonomous_replan",
    "control_repair",
    "delivery_not_allowed",
}
DELIVERY_BOUNDARY_REASONS = {
    *DELIVERY_CONTINUITY_PREEMPTIONS,
    "no_selected_todo",
    "todo_not_open",
    "todo_not_advancement",
    "todo_not_actionable",
    "todo_capability_blocked",
    "todo_claimed_by_other_agent",
    "open_advancement_todo",
}


def normalize_delivery_boundary(value: Any) -> str:
    boundary = str(value or DELIVERY_BOUNDARY_SEMANTIC_CLOSEOUT).strip()
    if boundary not in DELIVERY_BOUNDARY_VALUES:
        raise ValueError(
            "delivery_boundary must be one of: " + ", ".join(DELIVERY_BOUNDARY_VALUES)
        )
    return boundary


def _delivery_todo_payload(
    current_todo: Mapping[str, Any] | None,
    *,
    actionable: bool,
    capability_ready: bool,
) -> dict[str, Any] | None:
    if current_todo is None:
        return None
    todo_id = normalize_todo_id(current_todo.get("todo_id"))
    if not todo_id:
        raise ValueError("delivery continuity current Todo requires a typed todo_id")
    return {
        "todo_id": todo_id,
        "status": normalize_todo_status(current_todo.get("status")) or TODO_STATUS_OPEN,
        "task_class": todo_item_task_class(dict(current_todo)),
        "claimed_by": normalize_todo_claimed_by(current_todo.get("claimed_by")),
        "actionable": bool(actionable),
        "capability_ready": bool(capability_ready),
    }


def _normalize_preemptions(preemptions: Sequence[str]) -> list[str]:
    normalized = list(dict.fromkeys(str(item).strip() for item in preemptions))
    if any(item not in DELIVERY_CONTINUITY_PREEMPTIONS for item in normalized):
        raise ValueError("delivery continuity received an unsupported preemption")
    return normalized


def evaluate_delivery_continuity(
    *,
    agent_id: str,
    previous_todo_id: str | None,
    previous_delivery_outcome: str | None,
    current_todo: Mapping[str, Any] | None,
    actionable: bool,
    capability_ready: bool,
    preemptions: Sequence[str] = (),
) -> dict[str, Any]:
    """Ask the TypeScript Turn owner whether one open Todo remains in flight."""

    safe_agent_id = normalize_todo_claimed_by(agent_id)
    if not safe_agent_id:
        raise ValueError("delivery continuity requires a valid agent_id")
    normalized_preemptions = _normalize_preemptions(preemptions)
    todo_payload = _delivery_todo_payload(
        current_todo,
        actionable=actionable,
        capability_ready=capability_ready,
    )
    try:
        result = effect_runtime_result(
            "turn.delivery_continuity.evaluate",
            {
                "schema_version": DELIVERY_CONTINUITY_REQUEST_SCHEMA,
                "agent_id": safe_agent_id,
                "previous_todo_id": normalize_todo_id(previous_todo_id),
                "previous_delivery_outcome": (
                    str(previous_delivery_outcome or "").strip() or None
                ),
                "current_todo": todo_payload,
                "preemptions": normalized_preemptions,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping):
        raise RuntimeError("TypeScript delivery continuity result must be an object")
    if (
        result.get("schema_version") != DELIVERY_CONTINUITY_RESULT_SCHEMA
        or result.get("decision") not in DELIVERY_CONTINUITY_DECISIONS
        or not isinstance(result.get("reason"), str)
        or result.get("delivery_boundary") not in DELIVERY_BOUNDARY_VALUES
        or not (result.get("todo_id") is None or isinstance(result.get("todo_id"), str))
    ):
        raise RuntimeError("TypeScript delivery continuity result shape mismatch")
    return dict(result)


def evaluate_delivery_boundary(
    *,
    agent_id: str,
    current_todo: Mapping[str, Any] | None,
    actionable: bool,
    capability_ready: bool,
    preemptions: Sequence[str] = (),
) -> dict[str, Any]:
    """Ask the TypeScript Turn owner how this selected Todo should settle."""

    safe_agent_id = normalize_todo_claimed_by(agent_id)
    if not safe_agent_id:
        raise ValueError("delivery boundary requires a valid agent_id")
    try:
        result = effect_runtime_result(
            "turn.delivery_boundary.evaluate",
            {
                "schema_version": DELIVERY_BOUNDARY_REQUEST_SCHEMA,
                "agent_id": safe_agent_id,
                "current_todo": _delivery_todo_payload(
                    current_todo,
                    actionable=actionable,
                    capability_ready=capability_ready,
                ),
                "preemptions": _normalize_preemptions(preemptions),
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping):
        raise RuntimeError("TypeScript delivery boundary result must be an object")
    if (
        result.get("schema_version") != DELIVERY_BOUNDARY_RESULT_SCHEMA
        or result.get("delivery_boundary") not in DELIVERY_BOUNDARY_VALUES
        or result.get("reason") not in DELIVERY_BOUNDARY_REASONS
        or not (result.get("todo_id") is None or isinstance(result.get("todo_id"), str))
    ):
        raise RuntimeError("TypeScript delivery boundary result shape mismatch")
    return dict(result)

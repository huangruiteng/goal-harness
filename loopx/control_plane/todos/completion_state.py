"""Typed durable continuation selected when a Todo becomes done."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class TodoCompletionContinuation(str, Enum):
    ACTIVE_GOAL = "active_goal"
    SUCCESSOR = "successor"
    NO_FOLLOWUP = "no_followup"


class TodoCompletionRecovery(str, Enum):
    SAME_TURN_TERMINAL_CLOSEOUT = "same_turn_terminal_closeout"


def normalize_todo_no_followup(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    candidate = str(value or "").strip().lower()
    if candidate in {"1", "true", "yes", "y", "no_followup", "no-followup"}:
        return True
    if candidate in {"0", "false", "no", "n"}:
        return False
    return None


def normalize_todo_completion_continuation(value: Any) -> str | None:
    candidate = str(value or "").strip().lower()
    values = {item.value for item in TodoCompletionContinuation}
    return candidate if candidate in values else None


def require_todo_completion_continuation(value: Any) -> str:
    normalized = normalize_todo_completion_continuation(value)
    if normalized:
        return normalized
    raise ValueError(
        "completion_continuation must be one of: active_goal, successor, no_followup"
    )


def normalize_todo_completion_recovery(value: Any) -> str | None:
    candidate = str(value or "").strip().lower()
    values = {item.value for item in TodoCompletionRecovery}
    return candidate if candidate in values else None


def require_todo_completion_metadata(key: str, value: Any) -> str | None:
    if key == "completion_continuation":
        return require_todo_completion_continuation(value)
    normalized = normalize_todo_completion_recovery(value)
    if normalized or not value:
        return normalized
    raise ValueError("completion_recovery must be same_turn_terminal_closeout")


def completion_continuation_for_write(
    *, no_followup: bool, has_successor: bool
) -> str:
    if no_followup and has_successor:
        raise ValueError("todo completion cannot record both no_followup and a successor")
    if no_followup:
        return TodoCompletionContinuation.NO_FOLLOWUP.value
    if has_successor:
        return TodoCompletionContinuation.SUCCESSOR.value
    return TodoCompletionContinuation.ACTIVE_GOAL.value


@dataclass(frozen=True, slots=True)
class TodoCompletionState:
    continuation: str
    recovery: str | None = None


def completion_state_for_todo_write(
    todo: Mapping[str, Any],
    *,
    requested_no_followup: bool,
    has_successor: bool,
) -> TodoCompletionState:
    """Select durable state and audit the one supported recovery transition."""

    effective_no_followup = (
        requested_no_followup
        or normalize_todo_no_followup(todo.get("no_followup")) is True
    )
    continuation = completion_continuation_for_write(
        no_followup=effective_no_followup,
        has_successor=has_successor,
    )
    recovery = None
    if (
        str(todo.get("status") or "") == "done"
        and requested_no_followup
        and normalize_todo_completion_continuation(
            todo.get("completion_continuation")
        )
        == TodoCompletionContinuation.ACTIVE_GOAL.value
    ):
        recovery = TodoCompletionRecovery.SAME_TURN_TERMINAL_CLOSEOUT.value
    return TodoCompletionState(continuation=continuation, recovery=recovery)


def completion_metadata_updates(
    block: Mapping[str, Any],
    *,
    target_status: str,
    normalized_status: str | None,
    completion_continuation: str | None,
    completion_recovery: str | None,
    no_followup: bool | None,
    successor_todo_ids: list[str] | None,
) -> dict[str, Any]:
    """Build explicit completion metadata, including repair of untyped rows."""

    updates: dict[str, Any] = {}
    if completion_continuation is not None:
        updates["completion_continuation"] = completion_continuation
    if completion_recovery is not None:
        updates["completion_recovery"] = completion_recovery
    if not (
        target_status == "done"
        and normalized_status == "done"
        and completion_continuation is None
        and normalize_todo_completion_continuation(
            block.get("completion_continuation")
        )
        is None
    ):
        return updates
    effective_no_followup = (
        no_followup
        if no_followup is not None
        else normalize_todo_no_followup(block.get("no_followup")) is True
    )
    effective_successors = (
        successor_todo_ids
        if successor_todo_ids is not None
        else list(block.get("successor_todo_ids") or [])
    )
    updates["completion_continuation"] = completion_continuation_for_write(
        no_followup=bool(effective_no_followup),
        has_successor=bool(effective_successors),
    )
    return updates

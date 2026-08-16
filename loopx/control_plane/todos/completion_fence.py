from __future__ import annotations

from typing import Any

from .contract import (
    TODO_STATUS_DONE,
    normalize_todo_id_list,
    normalize_todo_no_followup,
)
from .completion_state import (
    TodoCompletionContinuation,
    normalize_todo_completion_continuation,
)


def completed_todo_replay(
    *,
    todo: dict[str, Any],
    goal_id: str,
    todo_id: str,
    completion_turn_key: str | None,
    no_followup: bool,
    handoff_mode: str,
    mutation_authority: dict[str, Any],
    state_file: str,
    project: str | None,
    dry_run: bool,
) -> dict[str, Any] | None:
    """Return local terminal-replay response-shape parity for a completed Todo.

    ``handoff_mode`` is the currently resolved goal mode, not a persisted copy
    of the original completion result. This local replay therefore is not a
    durable operation receipt and must not be presented as Stage 2 proof.
    Original effect markers such as a lease fence or handoff-gate override are
    intentionally absent because this branch performs neither effect. A
    same-turn request may return ``None`` only to append the missing terminal
    no-follow-up state; it cannot replace a successor or cross a turn fence.
    """

    if str(todo.get("status") or "") != TODO_STATUS_DONE:
        return None
    existing_turn_key = str(todo.get("completion_turn_key") or "")
    if completion_turn_key and completion_turn_key != existing_turn_key:
        raise ValueError(
            "todo is already completed under a different completion_turn_key"
        )
    terminal_upgrade = (
        no_followup and normalize_todo_no_followup(todo.get("no_followup")) is not True
    )
    completion_continuation = normalize_todo_completion_continuation(
        todo.get("completion_continuation")
    )
    if terminal_upgrade:
        if normalize_todo_id_list(todo.get("successor_todo_ids")):
            raise ValueError(
                "todo terminal closeout cannot replace an existing successor"
            )
        if completion_continuation is None:
            raise ValueError(
                "completed todo is missing completion_continuation; repair the "
                "Todo with `loopx todo complete` without --no-follow-up before terminal "
                "closeout"
            )
        if completion_continuation != TodoCompletionContinuation.ACTIVE_GOAL.value:
            raise ValueError(
                "todo terminal closeout recovery requires "
                "completion_continuation=active_goal"
            )
        if not completion_turn_key or completion_turn_key != existing_turn_key:
            raise ValueError(
                "todo terminal closeout requires the original completion_turn_key"
            )
        return None
    if completion_continuation is None:
        return None
    return {
        "ok": True,
        "dry_run": dry_run,
        "completed": True,
        "idempotent_replay": True,
        "changed": False,
        "goal_id": goal_id,
        "todo_id": todo_id,
        "status": TODO_STATUS_DONE,
        "completion_continuation": completion_continuation,
        "completion_recovery": todo.get("completion_recovery"),
        "handoff_mode": handoff_mode,
        "mutation_authority": mutation_authority,
        "state_file": state_file,
        "project": project,
    }

from __future__ import annotations

from typing import Any

from .active_state_todo_parser import parse_active_state_todos
from .contract import (
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_claimed_by,
)


def require_unique_open_advancement_target_claim(
    lines: list[str],
    *,
    todo_id: str | None,
    claimed_by: str | None,
    task_class: str | None,
    target_key: str | None,
) -> None:
    """Keep one agent from owning overlapping open work for one target."""
    if (
        not claimed_by
        or task_class != TODO_TASK_CLASS_ADVANCEMENT
        or not target_key
    ):
        return
    parsed = parse_active_state_todos("\n".join(lines), item_limit=None)
    agent_todos = parsed.get("agent_todos")
    items: list[dict[str, Any]] = (
        agent_todos.get("items", []) if isinstance(agent_todos, dict) else []
    )
    conflicts = [
        str(item.get("todo_id") or "")
        for item in items
        if item.get("status") == TODO_STATUS_OPEN
        and item.get("task_class") == TODO_TASK_CLASS_ADVANCEMENT
        and normalize_todo_claimed_by(item.get("claimed_by")) == claimed_by
        and str(item.get("target_key") or "") == target_key
        and str(item.get("todo_id") or "") != str(todo_id or "")
    ]
    if conflicts:
        raise ValueError(
            f"agent {claimed_by!r} already owns open advancement todo(s) "
            f"{', '.join(conflicts)} for target_key={target_key!r}; complete, "
            "supersede, defer, or clear the existing claim before claiming "
            "overlapping work"
        )

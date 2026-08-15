"""Todo validation authority checks for quota settlement."""

from __future__ import annotations

from typing import Any

from ..todos.completion_validation_projection import (
    pending_completion_validation_todo,
)
from ..todos.contract import normalize_todo_id


def completion_validation_spend_error(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    todo_id: str | None,
    agent_id: str | None,
    selected_todo: dict[str, Any] | None,
) -> str | None:
    """Explain why one requested settlement still lacks validation authority."""

    normalized_todo_id = normalize_todo_id(todo_id)
    if not normalized_todo_id:
        return None
    summaries: list[dict[str, Any]] = []
    if (
        selected_todo
        and normalize_todo_id(selected_todo.get("todo_id")) == normalized_todo_id
    ):
        summaries.append({"items": [selected_todo]})
    queue = status_payload.get("attention_queue")
    queue_items = queue.get("items") if isinstance(queue, dict) else []
    queue_item = next(
        (
            item
            for item in queue_items if isinstance(queue_items, list)
            if isinstance(item, dict) and item.get("goal_id") == goal_id
        ),
        {},
    )
    project_asset = (
        queue_item.get("project_asset")
        if isinstance(queue_item.get("project_asset"), dict)
        else {}
    )
    for owner in (queue_item, project_asset):
        summary = owner.get("agent_todos")
        if isinstance(summary, dict):
            summaries.append(summary)
    if any(
        pending_completion_validation_todo(
            summary,
            todo_id=normalized_todo_id,
            agent_id=agent_id,
        )
        is not None
        for summary in summaries
    ):
        return (
            "quota spend is blocked until controller-declared completion "
            f"validation durably completes todo {normalized_todo_id}"
        )
    return None

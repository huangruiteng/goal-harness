"""Public-safe projection for controller-declared Todo completion validation."""

from __future__ import annotations

from typing import Any

from .contract import (
    TODO_STATUS_DONE,
    normalize_todo_claimed_by,
    normalize_todo_id,
)


def project_completion_validation_authority(item: dict[str, Any]) -> dict[str, Any]:
    """Replace private validation execution details with one authority marker."""

    projected = dict(item)
    required = bool(str(projected.pop("validation_command", "") or "").strip())
    projected.pop("validation_label", None)
    projected.pop("validation_timeout_seconds", None)
    if required:
        projected["completion_validation_required"] = True
    return projected


def pending_completion_validation_todo(
    todo_summary: dict[str, Any] | None,
    *,
    todo_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any] | None:
    """Return a projected open Todo whose controller validation is required."""

    if not isinstance(todo_summary, dict):
        return None
    expected_todo_id = normalize_todo_id(todo_id)
    expected_agent_id = normalize_todo_claimed_by(agent_id)
    items = todo_summary.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        item_todo_id = normalize_todo_id(item.get("todo_id"))
        if expected_todo_id and item_todo_id != expected_todo_id:
            continue
        item_agent_id = normalize_todo_claimed_by(item.get("claimed_by"))
        if (
            expected_agent_id
            and item_agent_id
            and item_agent_id != expected_agent_id
        ):
            continue
        if item.get("completion_validation_required") is not True:
            continue
        if item.get("done") is True or item.get("status") == TODO_STATUS_DONE:
            continue
        return item
    return None

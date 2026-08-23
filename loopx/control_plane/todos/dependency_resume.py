from __future__ import annotations

from typing import Any, Callable

from .active_state_editing import section_bounds, todo_blocks
from .contract import (
    TODO_STATUS_BLOCKED,
    TODO_STATUS_DEFERRED,
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_BLOCKER,
    normalize_todo_id,
    normalize_todo_id_list,
    normalize_todo_status,
    normalize_todo_task_class,
    todo_done_for_status,
)


TODO_DEPENDENCY_RESUME_SCHEMA_VERSION = "todo_dependency_resume_v0"
TODO_DEPENDENCY_WAITING_STATUSES = {TODO_STATUS_BLOCKED, TODO_STATUS_DEFERRED}


def require_depends_on_todo_ids(value: Any) -> list[str]:
    normalized = normalize_todo_id_list(value)
    if value and not normalized:
        raise ValueError(
            "depends_on_todo_ids must contain public "
            "todo_<letters-digits-underscore-hyphen> tokens"
        )
    return normalized


def _status(todo: dict[str, Any]) -> str:
    return normalize_todo_status(todo.get("status")) or TODO_STATUS_OPEN


def _task_class(todo: dict[str, Any]) -> str:
    text = " ".join(
        str(value or "")
        for value in (todo.get("title"), todo.get("text"))
        if str(value or "").strip()
    )
    return normalize_todo_task_class(
        todo.get("task_class"),
        text=text,
        action_kind=todo.get("action_kind"),
    )


def iter_goal_todos(lines: list[str]) -> list[dict[str, Any]]:
    """Return user and agent todos in the current active-state document."""

    items: list[dict[str, Any]] = []
    for role in ("user", "agent"):
        bounds = section_bounds(lines, role)
        if not bounds:
            continue
        start, end, section = bounds
        for todo in todo_blocks(
            lines,
            start,
            end,
            role=role,
            source_section=section,
        ):
            items.append({**todo, "role": role})
    return items


def _todo_status_by_id(lines: list[str]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for todo in iter_goal_todos(lines):
        todo_id = normalize_todo_id(todo.get("todo_id"))
        if todo_id:
            statuses[todo_id] = _status(todo)
    return statuses


def dependents_of_completed_todo(
    lines: list[str],
    *,
    source_todo_id: str,
) -> list[dict[str, Any]]:
    """Return todos that list the completed todo among their fan-in dependencies."""

    normalized_source = normalize_todo_id(source_todo_id)
    if not normalized_source:
        return []
    dependents: list[dict[str, Any]] = []
    for todo in iter_goal_todos(lines):
        depends_on = normalize_todo_id_list(todo.get("depends_on_todo_ids"))
        if normalized_source in depends_on:
            dependents.append(todo)
    return dependents


def plan_completed_todo_dependency_resume(
    lines: list[str],
    *,
    source_todo_id: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    """Plan whether one dependent todo can leave blocked/deferred after a completion."""

    source_id = normalize_todo_id(source_todo_id) or source_todo_id
    target_id = normalize_todo_id(target.get("todo_id")) or ""
    target_status = _status(target)
    receipt: dict[str, Any] = {
        "schema_version": TODO_DEPENDENCY_RESUME_SCHEMA_VERSION,
        "source_todo_id": source_id,
        "target_todo_id": target_id,
        "target_role": str(target.get("role") or ""),
        "previous_status": target_status,
        "status": target_status,
        "changed": False,
    }
    if not target_id:
        return {**receipt, "state": "target_not_found"}
    if target_status not in TODO_DEPENDENCY_WAITING_STATUSES:
        return {**receipt, "state": "target_not_waiting"}
    if _task_class(target) == TODO_TASK_CLASS_BLOCKER:
        return {**receipt, "state": "explicit_blocker_repair_required"}

    depends_on = normalize_todo_id_list(target.get("depends_on_todo_ids"))
    statuses = _todo_status_by_id(lines)
    remaining_ids = sorted(
        {
            todo_id
            for todo_id in depends_on
            if todo_id != source_id and not todo_done_for_status(statuses.get(todo_id))
        }
    )
    if remaining_ids:
        return {
            **receipt,
            "state": "other_dependencies_active",
            "remaining_todo_ids": remaining_ids,
        }
    return {**receipt, "state": "resume_ready"}


def apply_completed_todo_dependency_resumes(
    lines: list[str],
    *,
    source_todo_id: str,
    updated_at: str,
    apply_update: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resume same-goal dependents whose fan-in dependencies are now all done."""

    receipts: list[dict[str, Any]] = []
    for target in dependents_of_completed_todo(lines, source_todo_id=source_todo_id):
        receipt = plan_completed_todo_dependency_resume(
            lines,
            source_todo_id=source_todo_id,
            target=target,
        )
        if receipt.get("state") != "resume_ready":
            receipts.append(
                {
                    key: value
                    for key, value in receipt.items()
                    if value not in (None, "", [], {})
                }
            )
            continue
        resumed = apply_update(
            lines,
            todo_id=str(receipt["target_todo_id"]),
            role=str(target.get("role") or None) or None,
            status=TODO_STATUS_OPEN,
            reason=(
                "dependencies satisfied by completed todo "
                f"{receipt['source_todo_id']}"
            ),
            updated_at=updated_at,
        )
        receipt.update(
            state="resumed",
            status=resumed.get("status"),
            changed=bool(resumed.get("changed")),
            claimed_by=resumed.get("claimed_by"),
        )
        receipts.append(
            {
                key: value
                for key, value in receipt.items()
                if value not in (None, "", [], {})
            }
        )
    return receipts

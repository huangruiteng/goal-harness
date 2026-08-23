"""Shared helpers for opening waiting todos after a completed dependency."""

from __future__ import annotations

from typing import Any, Callable

from .contract import TODO_STATUS_OPEN, normalize_todo_id_list


def assign_depends_on_todo_ids(target: dict[str, Any], value: Any) -> list[str]:
    """Copy a non-empty depends_on_todo_ids list onto a todo or event payload."""

    normalized = normalize_todo_id_list(value)
    if normalized:
        target["depends_on_todo_ids"] = normalized
    return normalized


def compact_resume_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Drop empty resume-receipt fields so callers share one serialization."""

    return {
        key: value
        for key, value in receipt.items()
        if value not in (None, "", [], {})
    }


def apply_open_todo_resume(
    lines: list[str],
    *,
    todo_id: str,
    role: str | None,
    reason: str,
    updated_at: str,
    apply_update: Callable[..., dict[str, Any]],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Open one waiting todo and record the shared resumed receipt fields."""

    resumed = apply_update(
        lines,
        todo_id=todo_id,
        role=role,
        status=TODO_STATUS_OPEN,
        reason=reason,
        updated_at=updated_at,
    )
    receipt.update(
        state="resumed",
        status=resumed.get("status"),
        changed=bool(resumed.get("changed")),
        claimed_by=resumed.get("claimed_by"),
    )
    return compact_resume_receipt(receipt)

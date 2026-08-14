"""Cohesive validation helpers for adding or upserting a Todo."""

from __future__ import annotations

from typing import Any

from .active_state_editing import todo_blocks
from .contract import (
    TODO_STATUS_DONE,
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_replan_obligation_id,
    normalize_todo_status,
    replan_successor_semantic_binding,
    todo_done_for_status,
)
from .todo_summary import normalize_todo_text


def matching_todo_block(
    lines: list[str],
    start: int,
    end: int,
    text: str,
    *,
    role: str | None = None,
    source_section: str | None = None,
) -> dict[str, Any] | None:
    """Return an unfinished Todo block with the same normalized text."""

    expected = normalize_todo_text(text)
    for block in todo_blocks(
        lines,
        start,
        end,
        role=role,
        source_section=source_section,
    ):
        status = normalize_todo_status(block.get("status")) or (
            TODO_STATUS_DONE if block.get("done") else TODO_STATUS_OPEN
        )
        if todo_done_for_status(status):
            continue
        if normalize_todo_text(str(block.get("text") or "")) == expected:
            return block
    return None


def require_replan_successor_scope(
    *,
    role: str,
    task_class: str | None,
    claimed_by: str | None,
    obligation_id: str | None,
    action_kind: str | None,
    target_key: str | None,
    explore_result_node_refs: list[str] | None,
) -> str | None:
    """Validate that an obligation binding denotes an executable successor."""

    if not obligation_id:
        return None
    if not (
        role == "agent"
        and task_class == TODO_TASK_CLASS_ADVANCEMENT
        and claimed_by
    ):
        raise ValueError(
            "replan_obligation_id requires an explicitly claimed agent "
            "advancement_task"
        )
    if replan_successor_semantic_binding(
        action_kind=action_kind,
        target_key=target_key,
        explore_result_node_refs=explore_result_node_refs,
    ) is None:
        raise ValueError(
            "replan_obligation_id requires a typed action_kind and a stable "
            "target_key or explore_result_node_ref"
        )
    normalized_obligation_id = normalize_todo_replan_obligation_id(obligation_id)
    if not normalized_obligation_id:
        raise ValueError(
            "replan_obligation_id must use the public token shape "
            "replan-<16 lowercase hex characters>"
        )
    return normalized_obligation_id


def require_replan_successor_rebinding(
    *,
    existing_obligation_id: Any,
    requested_obligation_id: str,
) -> str:
    """Keep a successor's causal obligation identity immutable."""

    requested = normalize_todo_replan_obligation_id(requested_obligation_id)
    existing = normalize_todo_replan_obligation_id(existing_obligation_id)
    if existing and existing != requested:
        raise ValueError(
            "a runnable successor cannot be rebound to a different replan obligation"
        )
    return requested

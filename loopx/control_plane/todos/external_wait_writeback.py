from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .active_state_editing import archive_section_bounds, section_bounds, todo_blocks
from .contract import (
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_id,
    normalize_todo_id_list,
)
from .external_wait_contract import build_monitor_advancement_authoring_contract
from .resume_condition import plan_todo_external_wait_transition


def _transition_items(lines: list[str]) -> list[dict[str, Any]]:
    """Collect complete active/archive Todo metadata under the caller's lock."""

    collected: list[dict[str, Any]] = []
    archive_bounds = archive_section_bounds(lines)
    if archive_bounds:
        collected.extend(
            {
                **item,
                "role": "agent",
            }
            for item in todo_blocks(
                lines,
                archive_bounds[0],
                archive_bounds[1],
                role="agent",
                source_section="Completed Work Archive",
            )
        )
    for role in ("user", "agent"):
        bounds = section_bounds(lines, role)
        if bounds:
            collected.extend(
                {
                    **item,
                    "role": role,
                }
                for item in todo_blocks(
                    lines,
                    bounds[0],
                    bounds[1],
                    role=role,
                    source_section=bounds[2],
                )
            )
    return collected


def plan_todo_external_wait_update(
    *,
    lines: list[str],
    todo_id: str,
    resume_when: str | None,
    successor_todo_ids: list[str] | None,
    existing_successor_todo_ids: Any,
    role: str,
    status: str,
    task_class: str,
) -> tuple[dict[str, Any] | None, int | None]:
    """Plan one typed open-Todo wait and return its persisted monitor fence."""

    if not resume_when or not resume_when.startswith(
        ("todo_done:", "monitor_changed:")
    ):
        return None, None
    uses_open_external_wait = (
        role == "agent"
        and status == TODO_STATUS_OPEN
        and task_class == TODO_TASK_CLASS_ADVANCEMENT
    )
    # todo_done is also valid for ordinary deferred authoring. monitor_changed,
    # however, always uses the typed open-wait protocol so invalid role/status/
    # task-class combinations receive the exact TS-owned diagnostic.
    if resume_when.startswith("todo_done:") and not uses_open_external_wait:
        return None, None

    items = _transition_items(lines)
    normalized_id = normalize_todo_id(todo_id)
    for index, item in enumerate(items):
        if normalize_todo_id(item.get("todo_id")) == normalized_id:
            items[index] = {
                **item,
                "role": role,
                "status": status,
                "task_class": task_class,
            }
    transition = plan_todo_external_wait_transition(
        todo_id=todo_id,
        resume_when=resume_when,
        successor_todo_ids=(
            successor_todo_ids
            if successor_todo_ids is not None
            else normalize_todo_id_list(existing_successor_todo_ids)
        ),
        items=items,
    )
    if resume_when.startswith("monitor_changed:"):
        transition["authoring_contract"] = (
            build_monitor_advancement_authoring_contract(
                monitor_todo_id=resume_when.partition(":")[2],
                successor_todo_ids=list(transition.get("successor_todo_ids") or []),
            )
        )
    updates = transition.get("metadata_updates")
    baseline = updates.get("resume_monitor_generation") if isinstance(updates, Mapping) else None
    return transition, int(baseline) if baseline is not None else None

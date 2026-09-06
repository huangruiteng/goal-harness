from __future__ import annotations

import re
from typing import Any

from ...todos.contract import (
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_id,
    normalize_todo_task_class,
)
from ...todos.deferred_resume import todo_summary_blocked_successor_items
from ..goal_vision_state import goal_vision_state_is_closed

VISION_FALLBACK_GAP_TRIGGER = "vision_fallback_unresolved"
VISION_FALLBACK_GAP_REASON_CODE = "declared_fallback_without_runnable_or_terminal"
DECLARED_FALLBACK_PATTERN = re.compile(r"\bfallback\b", re.IGNORECASE)
VISION_FALLBACK_TERMINAL_PATH_OUTCOME = "stop"
# Mirror of VISION_FRONTIER_TODO_DELTA_ACTIONS in goal_frontier.__init__
# (kept local to avoid a circular import from the package root).
VISION_FALLBACK_TODO_DELTA_ACTIONS = frozenset(
    {"activate", "create", "reopen", "resume", "retain"}
)
VISION_FALLBACK_SUCCESSOR_DELTA_ACTIONS = frozenset({"create", "reopen"})
VISION_FALLBACK_RUNNABLE_ITEM_SLOTS = (
    "executable_backlog_items",
    "first_executable_items",
    "backlog_items",
    "unclaimed_priority_open_items",
    "claimed_advancement_open_items",
)
VISION_FALLBACK_RUNNABLE_ITEM_LIMIT = 3
VISION_FALLBACK_RECOMMENDED_ACTION = (
    "resolve the declared fallback direction: link or retain a runnable "
    "successor Todo referencing it, declare a bounded create/reopen "
    "successor, or record an explicit terminal no-follow-up disposition; "
    "do not invent a user gate"
)


def _compact_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _declares_fallback_direction(agent_vision: dict[str, Any]) -> bool:
    patch = agent_vision.get("vision_patch")
    patch = patch if isinstance(patch, dict) else {}
    return any(
        DECLARED_FALLBACK_PATTERN.search(str(field or ""))
        for field in (
            patch.get("acceptance_summary"),
            patch.get("vision_summary"),
            agent_vision.get("vision_summary"),
        )
    )


def _vision_todo_delta(agent_vision: dict[str, Any]) -> list[tuple[str, str]]:
    delta: list[tuple[str, str]] = []
    for value in agent_vision.get("todo_delta") or []:
        if not isinstance(value, str):
            continue
        action, separator, raw_todo_id = value.strip().partition(":")
        todo_id = _compact_text(raw_todo_id, limit=120)
        if separator and todo_id and action.strip().lower() in (
            VISION_FALLBACK_TODO_DELTA_ACTIONS
        ):
            delta.append((action.strip().lower(), todo_id))
    return delta


def _item_is_runnable_open_advancement(item: dict[str, Any]) -> bool:
    if item.get("done") is True:
        return False
    status = str(item.get("status") or "open").strip().lower()
    if status not in {"", "open", "todo", "active", "pending"}:
        return False
    text = " ".join(
        str(value or "")
        for value in (item.get("title"), item.get("text"))
        if str(value or "").strip()
    )
    task_class = normalize_todo_task_class(
        item.get("task_class"),
        text=text,
        action_kind=item.get("action_kind"),
    )
    return task_class == TODO_TASK_CLASS_ADVANCEMENT


def _summary_runnable_open_todo_ids(
    agent_todo_summary: dict[str, Any] | None,
) -> set[str]:
    """Collect open advancement Todo ids the frontier can still select."""

    if not isinstance(agent_todo_summary, dict):
        return set()
    runnable: set[str] = set()
    for slot in VISION_FALLBACK_RUNNABLE_ITEM_SLOTS:
        items = agent_todo_summary.get(slot)
        if not isinstance(items, list):
            continue
        for item in items:
            if (
                isinstance(item, dict)
                and _item_is_runnable_open_advancement(item)
                and (todo_id := normalize_todo_id(item.get("todo_id")))
            ):
                runnable.add(todo_id)
    return runnable


def _blocked_primary_waiting(
    agent_todo_summary: dict[str, Any] | None,
    *,
    agent_id: str | None,
) -> bool:
    """Reuse the blocked-successor wait scope as the primary-blocked signal."""

    if not isinstance(agent_todo_summary, dict):
        return False
    blocker_items = agent_todo_summary.get("current_agent_blocker_items")
    if isinstance(blocker_items, list) and blocker_items:
        return True
    return bool(
        todo_summary_blocked_successor_items(
            agent_todo_summary,
            agent_id=agent_id,
        )
    )


def _vision_has_terminal_disposition(agent_vision: dict[str, Any]) -> bool:
    """Terminal evidence: closed-family state or path_delta.outcome=stop."""

    if goal_vision_state_is_closed(agent_vision.get("state")):
        return True
    path_delta = agent_vision.get("path_delta")
    path_delta = path_delta if isinstance(path_delta, dict) else {}
    return (
        str(path_delta.get("outcome") or "").strip().lower()
        == VISION_FALLBACK_TERMINAL_PATH_OUTCOME
    )


def declared_fallback_gap_from_agent_vision(
    agent_vision: dict[str, Any] | None,
    *,
    agent_todo_summary: dict[str, Any] | None,
    agent_id: str | None,
) -> dict[str, Any] | None:
    """Project one advisory gap for an unresolved declared fallback.

    A fallback direction declared in the goal vision must resolve to one of:
    a runnable open Todo referencing it via todo_delta, a bounded successor
    declaration (create/reopen action), or an explicit terminal disposition
    (closed-family state or path_delta.outcome=stop). When the primary path
    is blocked and none of the three holds, the fallback would otherwise
    disappear silently behind the blocked-successor wait state, which clears
    the ordinary acceptance gaps. This advisory gap stays in the independent
    ``fallback_gaps`` projection field and never enters the acceptance-gap
    replan stream.
    """

    if not isinstance(agent_vision, dict):
        return None
    if _vision_has_terminal_disposition(agent_vision):
        return None
    if not _declares_fallback_direction(agent_vision):
        return None
    if not _blocked_primary_waiting(
        agent_todo_summary,
        agent_id=agent_id,
    ):
        return None
    todo_delta = _vision_todo_delta(agent_vision)
    referenced_todo_ids = {todo_id for _, todo_id in todo_delta}
    if referenced_todo_ids & _summary_runnable_open_todo_ids(agent_todo_summary):
        return None
    if {action for action, _ in todo_delta} & VISION_FALLBACK_SUCCESSOR_DELTA_ACTIONS:
        return None
    gap: dict[str, Any] = {
        "kind": VISION_FALLBACK_GAP_TRIGGER,
        "source": "latest_agent_vision",
        "agent_id": agent_vision.get("agent_id"),
        "state": agent_vision.get("state"),
        "reason_code": VISION_FALLBACK_GAP_REASON_CODE,
        "recommended_action": VISION_FALLBACK_RECOMMENDED_ACTION,
    }
    unresolved_todo_ids = [
        todo_id
        for todo_id in sorted(referenced_todo_ids)
        if todo_id
    ][:VISION_FALLBACK_RUNNABLE_ITEM_LIMIT]
    if unresolved_todo_ids:
        gap["unresolved_todo_ids"] = unresolved_todo_ids
    generated_at = _compact_text(agent_vision.get("generated_at"), limit=80)
    if generated_at:
        gap["generated_at"] = generated_at
    return {key: value for key, value in gap.items() if value is not None}

from __future__ import annotations

from typing import Any

from ...todos.contract import (
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_claimed_by,
    normalize_todo_id,
)
from ...todos.deferred_resume import todo_summary_blocked_successor_items
from ...todos.projection import (
    todo_item_excludes_agent,
    todo_item_is_actionable_open,
    todo_item_task_class,
)
from ..goal_vision_state import goal_vision_state_is_closed

# Single owner of the vision todo_delta action contract shared by the
# acceptance-gap projection and this module.
VISION_FRONTIER_TODO_DELTA_ACTIONS = frozenset(
    {"activate", "create", "reopen", "resume", "retain"}
)
# create/reopen entries are bounded successor declarations and resolve the
# fallback disposition on their own; activate/resume/retain entries only link
# the vision to existing Todos and still need a selectable frontier match.
VISION_TODO_DELTA_SUCCESSOR_ACTIONS = frozenset({"create", "reopen"})
VISION_TODO_DELTA_LINKAGE_ACTIONS = frozenset(
    VISION_FRONTIER_TODO_DELTA_ACTIONS - VISION_TODO_DELTA_SUCCESSOR_ACTIONS
)
VISION_TODO_DELTA_ID_LIMIT = 120
VISION_FALLBACK_GAP_TRIGGER = "vision_fallback_unresolved"
VISION_FALLBACK_GAP_REASON_CODE = "declared_fallback_without_runnable_or_terminal"
VISION_FALLBACK_TERMINAL_PATH_OUTCOME = "stop"
VISION_FALLBACK_RUNNABLE_ITEM_LIMIT = 3
VISION_FALLBACK_RECOMMENDED_ACTION = (
    "resolve the declared fallback direction: link or retain a runnable "
    "successor Todo referencing it, declare a bounded create/reopen "
    "successor, or record an explicit terminal no-follow-up disposition; "
    "do not invent a user gate"
)


def _compact_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def parse_vision_todo_delta_entries(entries: Any) -> list[tuple[str, str]]:
    """Parse ``action:todo_id`` vision todo_delta entries once for consumers."""

    parsed: list[tuple[str, str]] = []
    for value in entries or []:
        if not isinstance(value, str):
            continue
        action, separator, raw_todo_id = value.strip().partition(":")
        todo_id = _compact_text(raw_todo_id, limit=VISION_TODO_DELTA_ID_LIMIT)
        normalized_action = action.strip().lower()
        if (
            separator
            and todo_id
            and normalized_action in (VISION_FRONTIER_TODO_DELTA_ACTIONS)
        ):
            parsed.append((normalized_action, todo_id))
    return parsed


def agent_scoped_selectable_advancement_todo_ids(
    agent_todo_summary: dict[str, Any] | None,
    *,
    agent_id: str | None,
) -> set[str]:
    """Return the ids the agent-scoped selectable advancement frontier holds.

    Mirrors the slot order and item predicates of the authoritative
    ``todo_advancement_frontier_counts`` counter (executable backlog first,
    unclaimed priority plus agent-claimed advancement items as the slotless
    fallback), including claim ownership: peer-claimed advancement work is
    intentionally not part of this agent's selectable frontier.
    """

    if not isinstance(agent_todo_summary, dict):
        return set()
    normalized_agent_id = normalize_todo_claimed_by(agent_id)
    executable_items = agent_todo_summary.get("executable_backlog_items")
    if isinstance(executable_items, list):
        slots: tuple[Any, ...] = (executable_items,)
    else:
        slots = (
            agent_todo_summary.get("unclaimed_priority_open_items"),
            agent_todo_summary.get("claimed_advancement_open_items"),
        )
    selectable: set[str] = set()
    for items in slots:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if not todo_item_is_actionable_open(item):
                continue
            if todo_item_task_class(item) != TODO_TASK_CLASS_ADVANCEMENT:
                continue
            claimed_by = normalize_todo_claimed_by(item.get("claimed_by"))
            if normalized_agent_id and claimed_by and claimed_by != normalized_agent_id:
                continue
            if todo_item_excludes_agent(item, agent_id=normalized_agent_id):
                continue
            if todo_id := normalize_todo_id(item.get("todo_id")):
                selectable.add(todo_id)
    return selectable


def _blocked_successor_todo_ids(
    agent_todo_summary: dict[str, Any] | None,
    *,
    agent_id: str | None,
) -> set[str]:
    """Ids the blocked-successor wait state itself is waiting on."""

    if not isinstance(agent_todo_summary, dict):
        return set()
    return {
        todo_id
        for todo_id in (
            normalize_todo_id(item.get("todo_id"))
            for item in todo_summary_blocked_successor_items(
                agent_todo_summary,
                agent_id=agent_id,
            )
            if isinstance(item, dict)
        )
        if todo_id
    }


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

    A fallback direction is declared structurally: the vision's todo_delta
    links it to existing Todos via activate/resume/retain entries. Prose
    mentions never declare a fallback, so negated or non-English vision text
    cannot invent a gap. The declared direction is resolved when one of:
    a linked Todo sits on the authoritative agent-scoped selectable
    advancement frontier (peer-claimed primary-path Todos do not), the
    todo_delta declares a bounded create/reopen successor, or the vision
    records an explicit terminal disposition (closed-family state or
    path_delta.outcome=stop). The primary path's own blocked successors are
    the wait state itself, not fallback declarations, and are excluded.

    When the primary path is blocked and none of the resolutions holds, the
    declared fallback would otherwise disappear silently behind the
    blocked-successor wait state, which clears the ordinary acceptance gaps.
    This advisory gap stays in the independent ``fallback_gaps`` projection
    field and never enters the acceptance-gap replan stream.
    """

    if not isinstance(agent_vision, dict):
        return None
    if _vision_has_terminal_disposition(agent_vision):
        return None
    if not _blocked_primary_waiting(
        agent_todo_summary,
        agent_id=agent_id,
    ):
        return None
    todo_delta = parse_vision_todo_delta_entries(agent_vision.get("todo_delta"))
    if {action for action, _ in todo_delta} & VISION_TODO_DELTA_SUCCESSOR_ACTIONS:
        return None
    waiting_todo_ids = _blocked_successor_todo_ids(
        agent_todo_summary,
        agent_id=agent_id,
    )
    declared_linkage_todo_ids = {
        todo_id
        for action, todo_id in todo_delta
        if action in VISION_TODO_DELTA_LINKAGE_ACTIONS
        and todo_id not in waiting_todo_ids
    }
    if not declared_linkage_todo_ids:
        return None
    if declared_linkage_todo_ids & agent_scoped_selectable_advancement_todo_ids(
        agent_todo_summary,
        agent_id=agent_id,
    ):
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
        todo_id for todo_id in sorted(declared_linkage_todo_ids) if todo_id
    ][:VISION_FALLBACK_RUNNABLE_ITEM_LIMIT]
    if unresolved_todo_ids:
        gap["unresolved_todo_ids"] = unresolved_todo_ids
    generated_at = _compact_text(agent_vision.get("generated_at"), limit=80)
    if generated_at:
        gap["generated_at"] = generated_at
    return {key: value for key, value in gap.items() if value is not None}

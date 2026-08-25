from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..todos.contract import normalize_todo_id
from ..todos.summary_item import compact_todo_summary_item
from .action_portfolio import quota_runnable_action_candidates
from .primary_action import protocol_action_text


PLANNING_HORIZON_REQUEST_SCHEMA_VERSION = "quota_planning_horizon_request_v0"
PLANNING_HORIZON_SCHEMA_VERSION = "quota_planning_horizon_v0"

_CONTEXT_LANES = (
    "active_next_action_items",
    "active_next_action_executable_items",
    "first_open_items",
    "first_executable_items",
    "backlog_items",
    "executable_backlog_items",
    "unclaimed_priority_open_items",
    "current_agent_claimed_advancement_items",
    "current_agent_blocker_items",
    "resume_blocked_items",
    "deferred_items",
    "route_continuation_replan_items",
    "monitor_open_items",
)


def _compact_context_candidate(
    value: Mapping[str, Any],
) -> dict[str, Any] | None:
    todo_id = normalize_todo_id(value.get("todo_id"))
    text = protocol_action_text(value.get("text"), limit=500)
    if not todo_id or not text:
        return None
    return compact_todo_summary_item(dict(value), text=text)


def _context_candidate_sources(
    *,
    selected: Mapping[str, Any],
    runnable: list[dict[str, Any]],
    agent_todo_summary: Mapping[str, Any] | None,
    blocked_priority_fallback: Mapping[str, Any] | None,
) -> list[Any]:
    sources: list[Any] = [selected, *runnable]
    if isinstance(agent_todo_summary, Mapping):
        sources.extend(
            value
            for lane in _CONTEXT_LANES
            for value in (
                agent_todo_summary.get(lane)
                if isinstance(agent_todo_summary.get(lane), list)
                else []
            )
        )
    if isinstance(blocked_priority_fallback, Mapping):
        blocked_items = blocked_priority_fallback.get("blocked_items")
        if isinstance(blocked_items, list):
            sources.extend(blocked_items)
    return sources


def _context_candidates(
    *,
    selected: Mapping[str, Any],
    agent_todo_summary: Mapping[str, Any] | None,
    capability_gate: Mapping[str, Any] | None,
    blocked_priority_fallback: Mapping[str, Any] | None,
    agent_id: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    runnable = quota_runnable_action_candidates(
        agent_id=agent_id,
        agent_todo_summary=agent_todo_summary,
        capability_gate=capability_gate,
    )
    sources = _context_candidate_sources(
        selected=selected,
        runnable=runnable,
        agent_todo_summary=agent_todo_summary,
        blocked_priority_fallback=blocked_priority_fallback,
    )
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in sources:
        if not isinstance(value, Mapping):
            continue
        compact = _compact_context_candidate(value)
        if compact is None:
            continue
        todo_id = str(compact["todo_id"])
        if todo_id in seen:
            continue
        seen.add(todo_id)
        candidates.append(compact)
    return candidates, [str(item["todo_id"]) for item in runnable]


def _source_context_count(summary: Mapping[str, Any] | None) -> int:
    if not isinstance(summary, Mapping):
        return 0
    counts = (summary.get("open_count"), summary.get("deferred_count"))
    return sum(value for value in counts if type(value) is int and value >= 0)


def _frontier_acceptance_gaps(
    projection: Mapping[str, Any] | None,
) -> list[Any]:
    if not isinstance(projection, Mapping):
        return []
    acceptance_gaps = projection.get("acceptance_gaps")
    return acceptance_gaps if isinstance(acceptance_gaps, list) else []


def build_quota_planning_horizon(
    *,
    goal_id: str,
    selected: Mapping[str, Any] | None,
    agent_id: str | None,
    agent_todo_summary: Mapping[str, Any] | None,
    capability_gate: Mapping[str, Any] | None,
    blocked_priority_fallback: Mapping[str, Any] | None,
    goal_frontier_projection: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Adapt existing Todo/frontier facts into the TS-owned read model."""

    safe_agent_id = str(agent_id or "").strip()
    compact_selected = (
        _compact_context_candidate(selected) if selected is not None else None
    )
    if not goal_id or not safe_agent_id or compact_selected is None:
        return None
    candidates, runnable_todo_ids = _context_candidates(
        selected=selected,
        agent_todo_summary=agent_todo_summary,
        capability_gate=capability_gate,
        blocked_priority_fallback=blocked_priority_fallback,
        agent_id=safe_agent_id,
    )
    source_context_count = _source_context_count(agent_todo_summary)
    acceptance_gaps = _frontier_acceptance_gaps(goal_frontier_projection)
    try:
        projected = effect_runtime_result(
            "work_item.planning_horizon.project",
            {
                "schema_version": PLANNING_HORIZON_REQUEST_SCHEMA_VERSION,
                "goal_id": goal_id,
                "agent_id": safe_agent_id,
                "selected_todo": compact_selected,
                "candidates": candidates,
                "runnable_todo_ids": runnable_todo_ids,
                "source_context_todo_count": source_context_count,
                "acceptance_gaps": acceptance_gaps,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if projected is None:
        return None
    if not isinstance(projected, Mapping) or (
        projected.get("schema_version") != PLANNING_HORIZON_SCHEMA_VERSION
    ):
        raise RuntimeError("TypeScript quota planning horizon shape mismatch")
    return dict(projected)

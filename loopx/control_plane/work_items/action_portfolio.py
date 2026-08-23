from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..todos.contract import (
    TODO_TASK_CLASS_ADVANCEMENT,
    TODO_TASK_CLASS_MONITOR,
    normalize_todo_claimed_by,
    normalize_todo_id,
)
from ..todos.projection import (
    todo_item_is_actionable_open,
    todo_item_task_class,
)
from ..todos.summary_item import compact_todo_summary_item
from .primary_action import protocol_action_text


ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION = "quota_action_portfolio_request_v0"
ACTION_PORTFOLIO_SCHEMA_VERSION = "quota_action_portfolio_v0"


def _compact_candidate(value: Mapping[str, Any]) -> dict[str, Any] | None:
    todo_id = normalize_todo_id(value.get("todo_id"))
    text = protocol_action_text(value.get("text"), limit=500)
    if not todo_id or not text:
        return None
    compact = compact_todo_summary_item(dict(value), text=text)
    for field in (
        "source",
        "selected_by",
        "claim_required_before_work",
        "availability_reason",
    ):
        if value.get(field) is not None:
            compact[field] = value[field]
    return compact


def _runnable_candidates(
    *,
    agent_id: str,
    agent_todo_summary: Mapping[str, Any] | None,
    capability_gate: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(agent_todo_summary, Mapping):
        return []
    capability_candidates = (
        capability_gate.get("runnable_candidates")
        if isinstance(capability_gate, Mapping)
        else None
    )
    if isinstance(capability_candidates, list):
        sources: list[list[Any]] = [capability_candidates]
    else:
        sources = []
        for field in (
            "active_next_action_executable_items",
            "first_executable_items",
            "executable_backlog_items",
        ):
            items = agent_todo_summary.get(field)
            if isinstance(items, list):
                sources.append(items)

    candidates: list[dict[str, Any]] = []
    for items in sources:
        for item in items:
            if not isinstance(item, Mapping):
                continue
            candidate = dict(item)
            claimed_by = normalize_todo_claimed_by(candidate.get("claimed_by"))
            if (
                not todo_item_is_actionable_open(candidate)
                or todo_item_task_class(candidate) != TODO_TASK_CLASS_ADVANCEMENT
                or (claimed_by is not None and claimed_by != agent_id)
            ):
                continue
            compact = _compact_candidate(candidate)
            if compact is None:
                continue
            if claimed_by is None:
                compact["claim_required_before_work"] = True
            candidates.append(compact)
    return candidates


def _unavailable_higher_priority_candidates(
    blocked_priority_fallback: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(blocked_priority_fallback, Mapping):
        return []
    items = blocked_priority_fallback.get("blocked_items")
    unavailable: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, Mapping):
            continue
        candidate = dict(item)
        task_class = todo_item_task_class(candidate)
        if task_class == TODO_TASK_CLASS_MONITOR and candidate.get("next_due_at"):
            candidate["availability_reason"] = "scheduled_for_future"
        elif candidate.get("status"):
            candidate["availability_reason"] = (
                f"status_{str(candidate['status']).strip().lower()}"
            )
        else:
            candidate["availability_reason"] = "not_currently_executable"
        compact = _compact_candidate(candidate)
        if compact is not None:
            unavailable.append(compact)
    return unavailable


def build_quota_action_portfolio(
    *,
    primary: Mapping[str, Any] | None,
    agent_id: str | None,
    agent_todo_summary: Mapping[str, Any] | None,
    capability_gate: Mapping[str, Any] | None,
    blocked_priority_fallback: Mapping[str, Any] | None,
    max_fallback_actions: int = 2,
) -> dict[str, Any] | None:
    """Adapt gated Python projections into the TypeScript-owned portfolio."""

    safe_agent_id = normalize_todo_claimed_by(agent_id)
    compact_primary = _compact_candidate(primary) if primary is not None else None
    if not safe_agent_id or compact_primary is None:
        return None
    try:
        projected = effect_runtime_result(
            "work_item.action_portfolio.project",
            {
                "schema_version": ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
                "primary": compact_primary,
                "candidates": _runnable_candidates(
                    agent_id=safe_agent_id,
                    agent_todo_summary=agent_todo_summary,
                    capability_gate=capability_gate,
                ),
                "unavailable_higher_priority": (
                    _unavailable_higher_priority_candidates(
                        blocked_priority_fallback
                    )
                ),
                "max_fallback_actions": max_fallback_actions,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if projected is None:
        return None
    if not isinstance(projected, Mapping) or (
        projected.get("schema_version") != ACTION_PORTFOLIO_SCHEMA_VERSION
    ):
        raise RuntimeError("TypeScript quota action portfolio shape mismatch")
    return dict(projected)

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .action_portfolio import build_quota_action_portfolio
from .planning_horizon import build_quota_planning_horizon
from .planning_inventory import (
    build_quota_planning_inventory,
    build_quota_planning_inventory_detail,
)


def build_quota_planning_projections(
    *,
    projection_enabled: bool,
    include_detail: bool,
    goal_id: str,
    selected: Mapping[str, Any] | None,
    agent_id: str | None,
    agent_todo_summary: Mapping[str, Any] | None,
    agent_todo_source_items: list[dict[str, Any]],
    capability_gate: Mapping[str, Any] | None,
    blocked_priority_fallback: Mapping[str, Any] | None,
    goal_frontier_projection: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build all Todo planning lenses from one typed inventory."""

    if not projection_enabled and not include_detail:
        return {}
    inventory = build_quota_planning_inventory(
        goal_id=goal_id,
        selected=selected,
        agent_id=agent_id,
        agent_todo_summary=agent_todo_summary,
        agent_todo_source_items=agent_todo_source_items,
        capability_gate=capability_gate,
        blocked_priority_fallback=blocked_priority_fallback,
    )
    if inventory is None:
        return {}
    projected: dict[str, Any] = {}
    if projection_enabled:
        portfolio = build_quota_action_portfolio(planning_inventory=inventory)
        if portfolio is not None:
            projected["action_portfolio"] = portfolio
        horizon = build_quota_planning_horizon(
            planning_inventory=inventory,
            goal_frontier_projection=goal_frontier_projection,
        )
        if horizon is not None:
            projected["planning_horizon"] = horizon
    if include_detail:
        projected["agent_todo_planning_inventory"] = (
            build_quota_planning_inventory_detail(inventory)
        )
    return projected

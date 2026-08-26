from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from .planning_inventory import (
    compact_planning_candidate,
)


ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION = "quota_action_portfolio_request_v1"
ACTION_PORTFOLIO_SCHEMA_VERSION = "quota_action_portfolio_v2"
ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION = (
    "action_selection_qualification_request_v0"
)
ACTION_SELECTION_QUALIFICATION_SCHEMA_VERSION = "action_selection_qualification_v0"


def _compact_candidate(value: Mapping[str, Any]) -> dict[str, Any] | None:
    return compact_planning_candidate(value)


def build_quota_action_portfolio(
    *,
    planning_inventory: Mapping[str, Any] | None,
    max_alternative_actions: int = 2,
) -> dict[str, Any] | None:
    """Project action choice from the shared TypeScript-owned inventory."""

    if not isinstance(planning_inventory, Mapping):
        return None
    try:
        projected = effect_runtime_result(
            "work_item.action_portfolio.project",
            {
                "schema_version": ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
                "planning_inventory": dict(planning_inventory),
                "max_alternative_actions": max_alternative_actions,
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


def qualify_action_selection(
    *,
    requested_todo_id: str,
    candidate: Mapping[str, Any] | None,
    should_run: bool,
    normal_delivery_allowed: bool,
    delivery_preemptions: list[str],
) -> dict[str, Any]:
    """Adapt current Python projections into the TS-owned selection reducer."""

    compact_candidate = _compact_candidate(candidate) if candidate is not None else None
    try:
        result = effect_runtime_result(
            "work_item.action_selection.qualify",
            {
                "schema_version": ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
                "requested_todo_id": requested_todo_id,
                "candidate": compact_candidate,
                "should_run": should_run,
                "normal_delivery_allowed": normal_delivery_allowed,
                "delivery_preemptions": delivery_preemptions,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping) or (
        result.get("schema_version") != ACTION_SELECTION_QUALIFICATION_SCHEMA_VERSION
    ):
        raise RuntimeError("TypeScript action-selection qualification shape mismatch")
    return dict(result)

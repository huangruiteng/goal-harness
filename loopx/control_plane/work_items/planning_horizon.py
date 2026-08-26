from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result


PLANNING_HORIZON_REQUEST_SCHEMA_VERSION = "quota_planning_horizon_request_v1"
PLANNING_HORIZON_SCHEMA_VERSION = "quota_planning_horizon_v0"


def _frontier_acceptance_gaps(
    projection: Mapping[str, Any] | None,
) -> list[Any]:
    if not isinstance(projection, Mapping):
        return []
    acceptance_gaps = projection.get("acceptance_gaps")
    return acceptance_gaps if isinstance(acceptance_gaps, list) else []


def build_quota_planning_horizon(
    *,
    planning_inventory: Mapping[str, Any] | None,
    goal_frontier_projection: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Project the bounded hot-path lens from one typed Todo inventory."""

    if not isinstance(planning_inventory, Mapping):
        return None
    try:
        projected = effect_runtime_result(
            "work_item.planning_horizon.project",
            {
                "schema_version": PLANNING_HORIZON_REQUEST_SCHEMA_VERSION,
                "planning_inventory": dict(planning_inventory),
                "acceptance_gaps": _frontier_acceptance_gaps(
                    goal_frontier_projection
                ),
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

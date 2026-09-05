from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .delivery_batch_scale import UNKNOWN_DELIVERY_BATCH_SCALE, normalize_delivery_batch_scale
from .delivery_outcome import (
    DELIVERY_OUTCOME_NOT_CONFIGURED,
    DELIVERY_OUTCOME_UNKNOWN,
    FOLLOWTHROUGH_REQUIRED_DELIVERY_OUTCOMES,
    normalize_delivery_outcome,
)


def delivery_batch_scale_for_run(run: dict[str, Any]) -> str:
    explicit = normalize_delivery_batch_scale(run.get("delivery_batch_scale"))
    return explicit.value if explicit else UNKNOWN_DELIVERY_BATCH_SCALE


def delivery_outcome_for_run(
    run: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    execution_profile_outcome_floor: Callable[[dict[str, Any] | None], dict[str, Any]],
) -> str:
    explicit = normalize_delivery_outcome(run.get("delivery_outcome"))
    if explicit:
        return explicit.value
    if str(run.get("delivery_outcome") or "").strip():
        return DELIVERY_OUTCOME_UNKNOWN
    if not outcome_floor_configured(
        profile, execution_profile_outcome_floor=execution_profile_outcome_floor
    ):
        return DELIVERY_OUTCOME_NOT_CONFIGURED
    return DELIVERY_OUTCOME_UNKNOWN


def outcome_floor_configured(
    profile: dict[str, Any] | None,
    *,
    execution_profile_outcome_floor: Callable[[dict[str, Any] | None], dict[str, Any]],
) -> bool:
    floor = execution_profile_outcome_floor(profile)
    return bool(floor.get("outcome_markers") or floor.get("surface_only_hints"))


def outcome_gap_streak(
    runs: list[dict[str, Any]],
    profile: dict[str, Any] | None = None,
    *,
    delivery_outcome_for_run: Callable[[dict[str, Any], dict[str, Any] | None], str],
    outcome_floor_configured: Callable[[dict[str, Any] | None], bool],
) -> int:
    if not outcome_floor_configured(profile):
        return 0
    streak = 0
    for run in runs:
        outcome = delivery_outcome_for_run(run, profile)
        normalized = normalize_delivery_outcome(outcome)
        if normalized not in FOLLOWTHROUGH_REQUIRED_DELIVERY_OUTCOMES:
            break
        streak += 1
    return streak


def small_delivery_batch_scale_streak(
    runs: list[dict[str, Any]],
    *,
    delivery_batch_scale_for_run: Callable[[dict[str, Any]], str],
    small_delivery_batch_scales: set[str],
) -> int:
    streak = 0
    for run in runs:
        if delivery_batch_scale_for_run(run) not in small_delivery_batch_scales:
            break
        streak += 1
    return streak

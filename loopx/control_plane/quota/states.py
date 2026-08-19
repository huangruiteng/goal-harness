from __future__ import annotations

from enum import Enum
from typing import Any


QUOTA_STATE_ORDER = (
    "blocked_health",
    "operator_gate",
    "focus_wait",
    "eligible",
    "waiting",
    "throttled",
    "paused",
)


class AutomaticTurnPauseCause(str, Enum):
    """Typed owner-policy reason that hard-pauses automatic Goal turns."""

    GOAL_STOPPED = "goal_stopped"
    COMPUTE_QUOTA_ZERO = "compute_quota_zero"


def automatic_turn_pause_cause(item: dict[str, Any]) -> AutomaticTurnPauseCause | None:
    raw_quota = item.get("quota")
    quota = raw_quota if isinstance(raw_quota, dict) else {}
    raw_cause = str(quota.get("pause_cause") or "").strip()
    if raw_cause:
        try:
            return AutomaticTurnPauseCause(raw_cause)
        except ValueError:
            return None
    if str(quota.get("goal_activation_state") or "") == "stopped":
        return AutomaticTurnPauseCause.GOAL_STOPPED
    compute = quota.get("compute")
    if (
        isinstance(compute, (int, float))
        and not isinstance(compute, bool)
        and compute <= 0
    ):
        return AutomaticTurnPauseCause.COMPUTE_QUOTA_ZERO
    return None


def quota_item_is_paused(item: dict[str, Any]) -> bool:
    """Return True when a plan item carries a Goal-level hard pause."""

    raw_quota = item.get("quota")
    quota = raw_quota if isinstance(raw_quota, dict) else {}
    if str(quota.get("state") or "") == "paused":
        return True
    return automatic_turn_pause_cause(item) is not None

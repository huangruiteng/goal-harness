from __future__ import annotations

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


def quota_item_is_paused(item: dict[str, Any]) -> bool:
    """Return True when a plan item carries a Goal-level hard pause."""

    raw_quota = item.get("quota")
    quota = raw_quota if isinstance(raw_quota, dict) else {}
    if str(quota.get("state") or "") == "paused":
        return True
    compute = quota.get("compute")
    return (
        isinstance(compute, (int, float))
        and not isinstance(compute, bool)
        and compute <= 0
    )

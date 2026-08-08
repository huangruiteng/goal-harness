from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import Any

from ..runtime.time import now_utc
from ..todos.frontier_deadline import todo_summary_frontier_deadline
from .monitor_todo import monitor_cadence_delta
from .time import parse_scheduler_timestamp

MONITOR_WAIT_PROGRESSION_MINUTES = [15, 30, 60]
MONITOR_WAIT_HOST_FLOOR_MINUTES = 15
MONITOR_WAIT_NEAR_WINDOW_LEAD_MINUTES = 60


class MonitorWaitPhase(str, Enum):
    EXPIRED = "expired"
    ACTIVE_WINDOW = "active_window"
    NEAR_WINDOW = "near_window"
    FAR_WINDOW = "far_window"
    CADENCE_ONLY = "cadence_only"


MONITOR_WAIT_PHASE_RANK = {
    MonitorWaitPhase.ACTIVE_WINDOW.value: 0,
    MonitorWaitPhase.NEAR_WINDOW.value: 1,
    MonitorWaitPhase.CADENCE_ONLY.value: 2,
    MonitorWaitPhase.FAR_WINDOW.value: 3,
}


def _parse_monitor_timestamp(value: Any) -> datetime | None:
    return parse_scheduler_timestamp(value)


def _monitor_cadence_minutes(value: Any) -> int | None:
    cadence_delta = monitor_cadence_delta(value)
    if cadence_delta is None:
        return None
    return max(1, math.ceil(cadence_delta.total_seconds() / 60))


def _monitor_wait_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summary = payload.get("agent_todo_summary")
    if not isinstance(summary, dict):
        return []
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for key in ("current_agent_claimed_monitor_items", "monitor_open_items"):
        values = summary.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            todo_id = str(value.get("todo_id") or "")
            if todo_id and todo_id in seen_ids:
                continue
            if todo_id:
                seen_ids.add(todo_id)
            items.append(value)
    return items


def _monitor_item_identity(item: dict[str, Any]) -> str:
    for key in ("todo_id", "target_key", "action_kind", "title"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return str(item.get("index") or "monitor")


def _minutes_until(value: datetime, current_time: datetime) -> int:
    return max(1, math.ceil((value - current_time).total_seconds() / 60))


def _cap_monitor_progression(*, cap_minutes: int, host_floor_minutes: int) -> list[int]:
    safe_cap = max(1, int(cap_minutes))
    safe_floor = max(1, int(host_floor_minutes))
    # Keep host RRULEs on stable buckets; the exact due horizon still gates routing.
    progression = [
        max(safe_floor, interval)
        for interval in MONITOR_WAIT_PROGRESSION_MINUTES
        if interval <= safe_cap
    ]
    return progression or [safe_floor]


def _monitor_wait_item_plan(
    item: dict[str, Any],
    *,
    current_time: datetime,
) -> dict[str, Any] | None:
    expires_at = _parse_monitor_timestamp(item.get("expires_at"))
    if expires_at is not None and expires_at <= current_time:
        return {
            "phase": MonitorWaitPhase.EXPIRED.value,
            "selected_monitor_identity": _monitor_item_identity(item),
        }

    next_due_at = _parse_monitor_timestamp(item.get("next_due_at"))
    last_checked_at = _parse_monitor_timestamp(item.get("last_checked_at"))
    cadence_minutes = _monitor_cadence_minutes(item.get("cadence"))
    host_floor = MONITOR_WAIT_HOST_FLOOR_MINUTES
    phase: MonitorWaitPhase | None = None
    cap_candidates: list[int] = []
    include_next_due_in_reset = False

    if expires_at is not None and last_checked_at is not None and last_checked_at <= current_time:
        phase = MonitorWaitPhase.ACTIVE_WINDOW
        if cadence_minutes is not None:
            cap_candidates.append(cadence_minutes)
        if next_due_at is not None and next_due_at > current_time:
            cap_candidates.append(_minutes_until(next_due_at, current_time))
    elif next_due_at is not None and next_due_at > current_time:
        minutes_until_due = _minutes_until(next_due_at, current_time)
        phase = (
            MonitorWaitPhase.NEAR_WINDOW
            if minutes_until_due <= MONITOR_WAIT_NEAR_WINDOW_LEAD_MINUTES
            else MonitorWaitPhase.FAR_WINDOW
        )
        cap_candidates.append(minutes_until_due)
        include_next_due_in_reset = True
    elif cadence_minutes is not None:
        phase = MonitorWaitPhase.CADENCE_ONLY
        cap_candidates.append(cadence_minutes)

    if phase is None or not cap_candidates:
        return None

    # Fifteen minutes is the quiet-monitor backoff floor, not a deadline floor.
    # A tighter explicit cadence or due horizon must wake the host in time.
    cap_minutes = min(cap_candidates)
    host_floor = min(host_floor, cap_minutes)
    selected_identity = _monitor_item_identity(item)
    reset_profile = {
        "monitor_wait_phase": phase.value,
        "monitor_wait_host_floor_minutes": host_floor,
        "monitor_wait_selected_identity": selected_identity,
        "monitor_wait_cadence_minutes": cadence_minutes,
        "monitor_wait_window_start_at": (
            next_due_at.isoformat()
            if include_next_due_in_reset and next_due_at is not None
            else None
        ),
        "monitor_wait_window_end_at": expires_at.isoformat() if expires_at is not None else None,
    }
    progression = _cap_monitor_progression(
        cap_minutes=cap_minutes,
        host_floor_minutes=host_floor,
    )
    return {
        "phase": phase.value,
        "selected_monitor_identity": selected_identity,
        "selected_todo_id": item.get("todo_id"),
        "selected_target_key": item.get("target_key"),
        "host_floor_minutes": host_floor,
        "cap_minutes": cap_minutes,
        "cadence_minutes": cadence_minutes,
        "next_due_at": next_due_at.isoformat() if next_due_at is not None else None,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
        "last_checked_at": last_checked_at.isoformat() if last_checked_at is not None else None,
        "progression_minutes": progression,
        "reset_profile": reset_profile,
    }


def build_monitor_wait_cadence_plan(
    payload: dict[str, Any],
    *,
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    """Build phase-aware monitor backoff without turning due horizon into identity."""

    current_time = current_time or now_utc()
    plans: list[dict[str, Any]] = []
    expired_count = 0
    for item in _monitor_wait_items(payload):
        plan = _monitor_wait_item_plan(item, current_time=current_time)
        if not plan:
            continue
        if plan.get("phase") == MonitorWaitPhase.EXPIRED.value:
            expired_count += 1
            continue
        plans.append(plan)

    frontier_deadline = todo_summary_frontier_deadline(
        payload.get("agent_todo_summary"),
        current_time=current_time,
    )
    if (
        isinstance(frontier_deadline, dict)
        and frontier_deadline.get("source") == "continuous_monitor"
    ):
        frontier_plan = _monitor_wait_item_plan(
            {
                "title": frontier_deadline.get("identity"),
                "next_due_at": frontier_deadline.get("next_due_at"),
            },
            current_time=current_time,
        )
        if frontier_plan and not any(
            plan.get("selected_monitor_identity")
            == frontier_plan.get("selected_monitor_identity")
            and plan.get("next_due_at") == frontier_plan.get("next_due_at")
            for plan in plans
        ):
            plans.append(frontier_plan)

    if not plans:
        if expired_count:
            return {
                "phase": MonitorWaitPhase.EXPIRED.value,
                "expired_monitor_count": expired_count,
                "host_floor_minutes": MONITOR_WAIT_HOST_FLOOR_MINUTES,
                "base_progression_minutes": MONITOR_WAIT_PROGRESSION_MINUTES,
                "progression_minutes": None,
                "reset_profile": None,
            }
        return None

    selected = min(
        plans,
        key=lambda plan: (
            int(plan.get("cap_minutes") or 10**9),
            MONITOR_WAIT_PHASE_RANK.get(str(plan.get("phase") or ""), 99),
            str(plan.get("selected_monitor_identity") or ""),
        ),
    )
    return {
        **selected,
        "base_progression_minutes": MONITOR_WAIT_PROGRESSION_MINUTES,
        "candidate_count": len(plans),
        "expired_monitor_count": expired_count,
    }

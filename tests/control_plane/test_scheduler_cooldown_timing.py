from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from loopx.control_plane.scheduler import scheduler_hint as scheduler_hint_module
from loopx.control_plane.scheduler.scheduler_hint import (
    _user_gate_notification_cooldown,
)


CURRENT_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


COOLDOWN_TIMING_CASES = [
    {
        "id": "initial_failure_is_suppressed",
        "elapsed_minutes": 1,
        "notification_due": False,
    },
    {
        "id": "reminder_is_due_inside_the_next_host_window",
        "elapsed_minutes": 31,
        "notification_due": True,
    },
    {
        "id": "reminder_is_suppressed_after_the_host_window",
        "elapsed_minutes": 34,
        "notification_due": False,
    },
]


@pytest.mark.parametrize(
    "case",
    COOLDOWN_TIMING_CASES,
    ids=[case["id"] for case in COOLDOWN_TIMING_CASES],
)
def test_user_gate_notification_cooldown_timing(monkeypatch, case: dict) -> None:
    monkeypatch.setattr(scheduler_hint_module, "now_utc", lambda: CURRENT_TIME)
    failed_at = CURRENT_TIME - timedelta(minutes=case["elapsed_minutes"])

    cooldown = _user_gate_notification_cooldown(
        cadence_class="human_gate",
        host_failure_suppressed=True,
        current_interval_minutes=30,
        effective_host_rrule="FREQ=MINUTELY;INTERVAL=3",
        recorded_host_failure={"failed_at": failed_at.isoformat()},
    )

    assert cooldown is not None
    assert cooldown["cooldown_minutes"] == 30
    assert cooldown["reminder_window_minutes"] == 3
    assert cooldown["notification_due"] is case["notification_due"]
    assert cooldown["notification_suppressed"] is not case["notification_due"]

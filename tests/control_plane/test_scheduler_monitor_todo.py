from __future__ import annotations

from loopx.control_plane.scheduler.monitor_todo import monitor_todo_missing_schedule
from loopx.control_plane.testing.quota_fixtures import quota_todo_summary


def test_watch_only_monitor_without_schedule_is_not_a_schedule_gap() -> None:
    monitor = {
        "status": "open",
        "task_class": "continuous_monitor",
        "watch_only": "true",
    }

    assert monitor_todo_missing_schedule(monitor) is False

    summary = quota_todo_summary([monitor])
    assert summary["monitor_schedule_gap_count"] == 0
    assert summary["monitor_schedule_gap_items"] == []


def test_actionable_monitor_without_schedule_remains_a_schedule_gap() -> None:
    monitor = {
        "status": "open",
        "task_class": "continuous_monitor",
    }

    assert monitor_todo_missing_schedule(monitor) is True

from __future__ import annotations

from loopx.control_plane.scheduler.scheduler_hint import (
    MONITOR_WAIT_PHASE_RANK,
    MonitorWaitPhase,
)


def test_monitor_phase_enum_preserves_serialized_string_values() -> None:
    assert MonitorWaitPhase.EXPIRED == "expired"
    assert MonitorWaitPhase.ACTIVE_WINDOW == "active_window"
    assert MonitorWaitPhase.NEAR_WINDOW == "near_window"
    assert MonitorWaitPhase.FAR_WINDOW == "far_window"
    assert MonitorWaitPhase.CADENCE_ONLY == "cadence_only"
    assert all(isinstance(phase, str) for phase in MonitorWaitPhase)


def test_monitor_phase_rank_uses_serialized_values() -> None:
    assert MONITOR_WAIT_PHASE_RANK == {
        "active_window": 0,
        "near_window": 1,
        "cadence_only": 2,
        "far_window": 3,
    }

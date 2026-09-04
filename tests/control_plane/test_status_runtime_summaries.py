from __future__ import annotations

from typing import Any

from loopx.control_plane.runtime.run_history import build_run_history


def _history() -> dict[str, Any]:
    return {
        "goals": [],
        "runs": [
            {
                "goal_id": "goal-one",
                "generated_at": f"2026-01-01T00:00:0{index}Z",
                "classification": "state_refreshed",
            }
            for index in range(3)
        ],
    }


def _build(*, display_limit: int, recent_run_limit: int | None = None) -> dict[str, Any]:
    return build_run_history(
        _history(),
        latest_run=lambda _goal: None,
        goal_lifecycle_fields=lambda _goal, _run: {
            "lifecycle_phase": "registered",
            "lifecycle_flags": [],
        },
        subagent_activity_for_goal=lambda _goal: None,
        compact_run=lambda run: dict(run),
        quota_status=lambda _goal: {},
        display_limit=display_limit,
        recent_run_limit=recent_run_limit,
    )


def test_recent_run_limit_is_separate_from_display_limit() -> None:
    default = _build(display_limit=1)
    extended = _build(display_limit=1, recent_run_limit=3)

    assert len(default["recent_runs"]) == 1
    assert len(extended["recent_runs"]) == 3

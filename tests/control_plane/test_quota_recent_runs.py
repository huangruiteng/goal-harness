from __future__ import annotations

from loopx.control_plane.quota.recent_runs import goal_latest_run


def test_goal_latest_run_returns_first_compact_run() -> None:
    assert goal_latest_run({}) == {}
    assert goal_latest_run({"latest_runs": []}) == {}
    assert goal_latest_run(
        {
            "latest_runs": [
                {"generated_at": "2026-08-08T00:00:00+00:00"},
                {"generated_at": "2026-08-07T00:00:00+00:00"},
            ]
        }
    ) == {"generated_at": "2026-08-08T00:00:00+00:00"}

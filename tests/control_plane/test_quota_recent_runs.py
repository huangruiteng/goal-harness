from __future__ import annotations

from loopx.control_plane.quota.recent_runs import (
    goal_latest_run,
    latest_accountable_agent_delivery,
)


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


def _status_with_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    return {
        "run_history": {
            "goals": [
                {
                    "id": "continuity-goal",
                    "latest_runs": runs,
                }
            ]
        }
    }


def test_latest_delivery_ignores_controller_and_peer_rows() -> None:
    anchor = latest_accountable_agent_delivery(
        _status_with_runs(
            [
                {
                    "classification": "quota_scheduler_ack",
                    "agent_id": "codex-main",
                },
                {
                    "classification": "peer_progress",
                    "agent_id": "codex-peer",
                    "todo_id": "todo_peer001",
                    "delivery_outcome": "outcome_progress",
                },
                {
                    "classification": "bounded_progress",
                    "agent_id": "codex-main",
                    "todo_id": "todo_current001",
                    "delivery_outcome": "outcome_progress",
                },
            ]
        ),
        goal_id="continuity-goal",
        agent_id="codex-main",
    )

    assert anchor == {
        "todo_id": "todo_current001",
        "delivery_outcome": "outcome_progress",
        "generated_at": None,
    }


def test_newer_unbound_same_agent_work_breaks_continuity() -> None:
    anchor = latest_accountable_agent_delivery(
        _status_with_runs(
            [
                {
                    "classification": "unbound_material_work",
                    "agent_id": "codex-main",
                    "delivery_outcome": "outcome_progress",
                },
                {
                    "classification": "bounded_progress",
                    "agent_id": "codex-main",
                    "todo_id": "todo_current001",
                    "delivery_outcome": "outcome_progress",
                },
            ]
        ),
        goal_id="continuity-goal",
        agent_id="codex-main",
    )

    assert anchor is None

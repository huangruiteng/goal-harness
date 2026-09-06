from __future__ import annotations

from loopx.cli_commands.status import (
    _status_collection_limit_for_agent_lane,
    _trim_run_history_for_status_display,
)
from loopx.control_plane.goals.goal_frontier.ack_policy import (
    autonomous_replan_ack_satisfies_obligation,
)
from loopx.status import (
    AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK,
    AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD,
    autonomous_replan_periodic_review_from_runs,
)


def _periodic_runs(*, minute_offset: int = 0) -> list[dict[str, object]]:
    return [
        {
            "classification": f"bounded_delivery_{index:02d}",
            "generated_at": (
                f"2026-08-27T{minute_offset // 60:02d}:"
                f"{minute_offset % 60:02d}:{59 - index:02d}Z"
            ),
            "agent_id": "codex-fixture",
        }
        for index in range(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD)
    ]


def test_periodic_replan_lookback_survives_interleaved_neutral_runs() -> None:
    latest_runs: list[dict[str, object]] = []
    for index in range(AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD):
        latest_runs.extend(
            [
                {
                    "classification": "quota_slot_spent",
                    "generated_at": f"2026-08-27T00:{59 - index:02d}:01Z",
                    "agent_id": "codex-fixture",
                },
                {
                    "classification": f"bounded_delivery_{index:02d}",
                    "generated_at": f"2026-08-27T00:{59 - index:02d}:00Z",
                    "agent_id": "codex-fixture",
                },
            ]
        )

    selected_runs = latest_runs[:AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK]
    obligation = autonomous_replan_periodic_review_from_runs(
        selected_runs,
        agent_todos=None,
    )

    assert len(selected_runs) == len(latest_runs)
    assert obligation is not None
    trigger = obligation["triggers"][0]
    assert trigger["kind"] == "periodic_review_due"
    assert trigger["run_count"] == AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD


def test_periodic_replan_obligation_rotates_with_the_review_window() -> None:
    first = autonomous_replan_periodic_review_from_runs(
        _periodic_runs(minute_offset=0),
        agent_todos=None,
    )
    replay = autonomous_replan_periodic_review_from_runs(
        _periodic_runs(minute_offset=0),
        agent_todos=None,
    )
    later = autonomous_replan_periodic_review_from_runs(
        _periodic_runs(minute_offset=60),
        agent_todos=None,
    )

    assert first is not None
    assert replay is not None
    assert later is not None
    assert replay["obligation_id"] == first["obligation_id"]
    assert later["obligation_id"] != first["obligation_id"]
    assert not autonomous_replan_ack_satisfies_obligation(
        {
            "recorded": True,
            "semantic_delta": {
                "accepted": True,
                "obligation_id": first["obligation_id"],
                "outcomes": ["new_runnable_successor"],
            },
        },
        replan_obligation=later,
        acceptance_gaps=[],
    )


def test_agent_lane_keeps_periodic_control_history_off_the_display_path() -> None:
    display_limit = 5
    collection_limit = _status_collection_limit_for_agent_lane(
        requested_limit=display_limit,
        agent_id="codex-fixture",
    )
    rows = [
        {"classification": f"bounded_delivery_{index:02d}"}
        for index in range(collection_limit)
    ]
    payload: dict[str, object] = {
        "run_history": {
            "recent_runs": list(rows),
            "goals": [{"id": "fixture-goal", "latest_runs": list(rows)}],
        }
    }

    _trim_run_history_for_status_display(
        payload,
        display_limit=display_limit,
        collection_limit=collection_limit,
    )

    run_history = payload["run_history"]
    assert isinstance(run_history, dict)
    assert len(run_history["recent_runs"]) == display_limit
    assert len(run_history["goals"][0]["latest_runs"]) == display_limit
    assert payload["agent_lane_projection_lookback"] == {
        "schema_version": "agent_lane_projection_lookback_v0",
        "collection_limit": AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK,
        "display_limit": display_limit,
        "reason": (
            "status --agent-id collected quota-equivalent run history for "
            "agent-lane frontier projection, then restored the requested "
            "status display limit"
        ),
    }

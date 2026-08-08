from __future__ import annotations

from loopx.control_plane.testing.quota_fixtures import quota_status_payload
from loopx.control_plane.work_items.work_lane_context import (
    item_progress_scope,
    latest_run_progress_scope,
)
from loopx.quota import build_quota_should_run

GOAL_ID = "work-lane-policy-fixture"
PAST_DUE_AT = "2000-01-01T00:00:00+00:00"


def _status(
    *,
    agent_todo_items: list[dict],
    status: str = "monitor_backlog_fairness",
    next_action: str = "Observe dependency state and then advance backlog if unchanged.",
    latest_runs: list[dict] | None = None,
) -> dict:
    return quota_status_payload(
        goal_id=GOAL_ID,
        status=status,
        agent_todo_items=agent_todo_items,
        recommended_action=next_action,
        next_action=next_action,
        latest_runs=latest_runs,
    )


def _monitor_and_advancement() -> list[dict]:
    return [
        {
            "index": 1,
            "text": "[P0] Monitor one overdue dependency.",
            "role": "agent",
            "status": "open",
            "priority": "P0",
            "task_class": "continuous_monitor",
            "action_kind": "monitor",
            "next_due_at": PAST_DUE_AT,
        },
        {
            "index": 2,
            "text": "[P1] Advance the bounded product slice.",
            "role": "agent",
            "status": "open",
            "priority": "P1",
            "task_class": "advancement_task",
        },
    ]


def test_unchanged_monitor_attempt_yields_to_advancement() -> None:
    unchanged_poll = {
        "classification": "quota_monitor_poll",
        "agent_id": "codex-fixture",
        "health_check": "due monitor observation unchanged; no quota spend",
        "monitor_event": {
            "monitor_mode": "due_monitor_observed_without_material_transition",
            "material_change": False,
        },
    }
    payload = _status(
        agent_todo_items=_monitor_and_advancement(),
        next_action="Advance the bounded product slice.",
        latest_runs=[unchanged_poll],
    )
    guard = build_quota_should_run(payload, goal_id=GOAL_ID)
    lane = guard["work_lane_contract"]

    assert lane["lane"] == "advancement_task"
    assert lane["reason_codes"] == [
        "open_agent_todo",
        "due_monitor_context",
        "monitor_attempt_already_recorded",
    ]
    assert guard["recommended_action"] == "[P1] Advance the bounded product slice."


def test_due_monitor_preempts_lower_priority_advancement() -> None:
    payload = _status(agent_todo_items=_monitor_and_advancement())
    guard = build_quota_should_run(payload, goal_id=GOAL_ID)
    lane = guard["work_lane_contract"]

    assert lane["lane"] == "continuous_monitor"
    assert lane["monitor_due_count"] == 1
    assert lane["selected_todo_id"]
    assert guard["recommended_action"] == "[P0] Monitor one overdue dependency."


def test_work_lane_context_progress_scope_sources() -> None:
    payload = _status(
        agent_todo_items=_monitor_and_advancement(),
        status="side_bypass_dependency_observation",
        next_action="Observe dependency state and then advance backlog if unchanged.",
    )
    item = payload["attention_queue"]["items"][0]

    assert item_progress_scope(item) == "dependency_observation"
    assert latest_run_progress_scope(
        {"classification": "runner_dependency_observed"}
    ) == "dependency_observation"
    assert latest_run_progress_scope(
        {
            "classification": "runner_dependency_observed",
            "progress_scope": "primary_goal",
        }
    ) == "primary_goal"

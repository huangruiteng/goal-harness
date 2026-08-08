from __future__ import annotations

from loopx.control_plane.effect_program import (
    interpret_quota_should_run_packet,
)
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
)
from loopx.quota import build_quota_should_run

GOAL_ID = "effect-interpreter-fixture"


def test_due_monitor_replan_routes_through_effect_turn() -> None:
    items = [
        quota_todo_item(
            todo_id="todo_monitor_route",
            text="[P2] Watch the target",
            task_class="continuous_monitor",
            action_kind="watch",
            next_due_at="2026-08-08T00:00:00+00:00",
            target_key="route-target",
        )
    ]
    payload = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=items,
        recommended_action="Watch the target",
        next_action="Watch the target",
    )
    packet = build_quota_should_run(payload, goal_id=GOAL_ID)
    turn = interpret_quota_should_run_packet(
        packet,
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
    )

    assert turn.interpretation.route == "continuous_monitor"
    assert turn.interpretation.obligation == "attempt_due_monitor"
    assert turn.observation.decision == "autonomous_replan_required"
    assert turn.observation.effective_action == "autonomous_replan_required"
    assert turn.next_effect.cli_actions

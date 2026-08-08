from __future__ import annotations

from loopx.control_plane.effect_program import (
    interpret_quota_should_run_packet,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload
from loopx.quota import build_quota_should_run

GOAL_ID = "effect-interpreter-fixture"


def _advancement_payload() -> dict:
    todo_text = "[P1] Advance the bounded slice."
    return quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[
            {
                "index": 1,
                "text": todo_text,
                "role": "agent",
                "status": "open",
                "priority": "P1",
                "task_class": "advancement_task",
            }
        ],
        recommended_action=todo_text,
        next_action=todo_text,
    )


def test_quota_should_run_exposes_canonical_effect_slots() -> None:
    packet = build_quota_should_run(_advancement_payload(), goal_id=GOAL_ID)
    turn = interpret_quota_should_run_packet(
        packet,
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
        capabilities=["shell", "filesystem_write"],
    )

    # interpretation
    assert turn.request.kind == "quota_should_run"
    assert turn.request.goal_id == GOAL_ID
    assert turn.request.agent_id == "codex-fixture"
    assert turn.request.capabilities == ("shell", "filesystem_write")
    assert turn.interpretation.route == "advancement_task"
    assert turn.interpretation.obligation == "advance_one_bounded_segment"
    assert turn.interpretation.interaction_mode == "bounded_delivery"

    # observation
    assert turn.observation.decision == "run"
    assert turn.observation.should_run is True
    assert turn.observation.effective_action == "normal_run"
    assert turn.observation.recommended_action == "[P1] Advance the bounded slice."
    assert "lane=advancement_task" in turn.observation.protocol_summary

    # next effect
    assert turn.observation.next_cli_actions

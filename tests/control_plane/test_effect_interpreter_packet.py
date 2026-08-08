from __future__ import annotations

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

    # interpretation
    assert packet["work_lane_contract"]["lane"] == "advancement_task"
    assert packet["work_lane_contract"]["obligation"] == (
        "advance_one_bounded_segment"
    )
    assert packet["interaction_contract"]["mode"] == "bounded_delivery"

    # observation
    assert packet["decision"] == "run"
    assert packet["should_run"] is True
    assert packet["effective_action"] == "normal_run"
    assert packet["recommended_action"] == "[P1] Advance the bounded slice."
    assert "lane=advancement_task" in packet["protocol_action_packet"]["summary"]

    # next effect
    assert isinstance(
        packet["interaction_contract"]["cli_channel"]["next_cli_actions"],
        list,
    )
    assert packet["interaction_contract"]["cli_channel"]["next_cli_actions"]

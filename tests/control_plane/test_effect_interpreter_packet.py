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
    assert turn.next_effect.cli_actions
    assert turn.next_effect.cli_actions[0].startswith("loopx refresh-state")
    assert turn.next_effect.scheduler_action
    assert turn.next_effect.cadence_class


def test_quota_should_run_capability_gate_is_structured_around_decision() -> None:
    todo_text = "[P1] Network-only slice."
    payload = quota_status_payload(
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
                "required_capabilities": ["network"],
            }
        ],
        recommended_action=todo_text,
        next_action=todo_text,
    )
    packet = build_quota_should_run(payload, goal_id=GOAL_ID)
    turn = interpret_quota_should_run_packet(
        packet,
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
        capabilities=["shell"],
    )

    # The gate is an around decision: it short-circuits the original effect
    # and rewrites the next effect, but permission semantics stay visible.
    assert turn.interpretation.capability_action == "repair_bridge"
    assert turn.observation.decision == "repair_bridge"
    assert turn.observation.effective_action == "capability_bridge_repair"
    assert packet.get("capability_gate", {}).get("action") == "repair_bridge"
    assert packet.get("capability_gate", {}).get("owner_missing") == []
    assert turn.next_effect.cli_actions
    assert any(
        "--target-capability network" in action
        for action in turn.next_effect.cli_actions
    )


def test_effect_turn_keeps_monitor_quiet_around_decision_data_visible() -> None:
    packet = {
        "decision": "skip",
        "should_run": False,
        "effective_action": "monitor_quiet_skip",
        "recommended_action": "quiet until the next material transition",
        "interaction_contract": {
            "mode": "monitor_quiet_skip",
            "user_channel": {"notify": "DONT_NOTIFY", "action_required": False},
            "cli_channel": {"next_cli_actions": []},
        },
        "work_lane_contract": {
            "lane": "continuous_monitor",
            "obligation": "attempt_due_monitor",
            "must_attempt_work": False,
        },
        "scheduler_hint": {
            "action": "no_spend",
            "cadence_class": "monitor_wait",
        },
    }
    turn = interpret_quota_should_run_packet(
        packet,
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
        capabilities=["network", "external_evidence_poll"],
    )

    # A quiet turn must not be rewritten into a runnable next effect or a
    # spend. The around decision stays visible in typed packet slots.
    assert turn.interpretation.interaction_mode == "monitor_quiet_skip"
    assert turn.interpretation.route == "continuous_monitor"
    assert turn.observation.decision == "skip"
    assert turn.observation.should_run is False
    assert turn.observation.effective_action == "monitor_quiet_skip"
    assert turn.next_effect.cli_actions == ()
    assert turn.next_effect.scheduler_action == "no_spend"
    assert turn.next_effect.cadence_class == "monitor_wait"
    assert turn.next_effect.ack_cli_args == ()
    assert turn.next_effect.failure_cli_args == ()


def test_effect_turn_carries_scheduler_ack_and_failure_hints() -> None:
    packet = {
        "decision": "run",
        "should_run": True,
        "execution_mode": "interleaved",
        "effective_action": "normal_run",
        "recommended_action": "advance the bounded segment",
        "interaction_contract": {
            "mode": "bounded_delivery",
            "cli_channel": {
                "next_cli_actions": [
                    "loopx refresh-state --goal-id effect-interpreter-fixture",
                    "loopx quota spend-slot --goal-id effect-interpreter-fixture",
                ]
            },
        },
        "work_lane_contract": {
            "lane": "advancement_task",
            "obligation": "advance_one_bounded_segment",
            "must_attempt_work": True,
        },
        "scheduler_hint": {
            "action": "apply_rrule",
            "cadence_class": "active_work",
            "codex_app": {
                "ack_hint": {
                    "cli_args": [
                        "quota",
                        "scheduler-ack-current",
                        "--goal-id",
                        "effect-interpreter-fixture",
                        "--execute",
                    ]
                },
                "failure_hint": {
                    "cli_args": [
                        "quota",
                        "scheduler-ack-current",
                        "--goal-id",
                        "effect-interpreter-fixture",
                        "--failure",
                        "--execute",
                    ]
                },
            },
        },
    }
    turn = interpret_quota_should_run_packet(
        packet,
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
    )

    assert turn.next_effect.cli_actions == (
        "loopx refresh-state --goal-id effect-interpreter-fixture",
        "loopx quota spend-slot --goal-id effect-interpreter-fixture",
    )
    assert turn.next_effect.execution_mode == "interleaved"
    assert turn.next_effect.scheduler_action == "apply_rrule"
    assert turn.next_effect.cadence_class == "active_work"
    assert turn.next_effect.ack_cli_args == (
        "quota",
        "scheduler-ack-current",
        "--goal-id",
        "effect-interpreter-fixture",
        "--execute",
    )
    assert turn.next_effect.failure_cli_args == (
        "quota",
        "scheduler-ack-current",
        "--goal-id",
        "effect-interpreter-fixture",
        "--failure",
        "--execute",
    )

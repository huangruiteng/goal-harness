from __future__ import annotations

from loopx.control_plane.effect_program import interpret_turn_result_packet

GOAL_ID = "effect-interpreter-fixture"


def _result_packet(
    *,
    result_kind: str,
    failed_phase: str | None = None,
) -> dict:
    packet: dict = {
        "schema_version": "loopx_turn_result_v0",
        "turn_key": "sha256:fixture",
        "result_kind": result_kind,
        "execution_mode": "serial",
        "completed_phases": ["host_execute", "typed_result"],
        "classification": "fixture_progress",
        "recommended_action": "Continue the public fixture.",
        "delivery_outcome": "outcome_progress",
        "summary": "One public fixture advanced.",
        "next_cli_actions": [
            "loopx refresh-state --goal-id effect-interpreter-fixture"
        ],
    }
    if failed_phase:
        packet["failed_phase"] = failed_phase
    return packet


def test_turn_result_packet_maps_to_effect_turn() -> None:
    turn = interpret_turn_result_packet(
        _result_packet(result_kind="validated_progress"),
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
    )

    assert turn.request.kind == "turn_result"
    assert turn.request.source == "host"
    assert turn.request.goal_id == GOAL_ID
    assert turn.request.agent_id == "codex-fixture"
    assert turn.request.context["completed_phases"] == (
        "host_execute",
        "typed_result",
    )
    assert turn.interpretation.route == "turn_result_settlement"
    assert turn.interpretation.obligation == "settle_turn_receipt"
    assert turn.observation.decision == "validated_progress"
    assert turn.observation.should_run is False
    assert turn.observation.recommended_action == "Continue the public fixture."
    assert turn.next_effect.cli_actions == (
        "loopx refresh-state --goal-id effect-interpreter-fixture",
    )
    assert turn.next_effect.execution_mode == "serial"


def test_turn_result_failure_preserves_failed_phase() -> None:
    packet = _result_packet(
        result_kind="host_failure",
        failed_phase="host_execute",
    )
    packet["scheduler_hint"] = {
        "action": "failure_settle",
        "cadence_class": "repair",
        "codex_app": {
            "failure_hint": {
                "cli_args": [
                    "quota",
                    "scheduler-ack-current",
                    "--failure",
                    "--execute",
                ]
            }
        },
    }
    turn = interpret_turn_result_packet(packet, goal_id=GOAL_ID)

    assert turn.request.context["failed_phase"] == "host_execute"
    assert turn.observation.decision == "host_failure"
    assert turn.observation.should_run is False
    assert turn.next_effect.scheduler_action == "failure_settle"
    assert turn.next_effect.cadence_class == "repair"
    assert turn.next_effect.failure_cli_args == (
        "quota",
        "scheduler-ack-current",
        "--failure",
        "--execute",
    )

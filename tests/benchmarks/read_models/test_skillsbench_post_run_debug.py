from __future__ import annotations

from loopx import status
from loopx.benchmarks.read_models.skillsbench_post_run_debug import (
    build_skillsbench_post_run_debug_gate,
)


def _typed_repair_exhausted_compact() -> dict[str, object]:
    failed_turn = {
        "schema_version": "loopx_turn_execution_v0",
        "mode": "run_once",
        "status": "failed",
        "result_kind": "validation_failed",
        "validation": {
            "status": "failed",
            "recovery_kind": "repair_required",
        },
        "receipt": {
            "status": "failed",
            "failed_phase": "validation",
        },
        "effects": {
            "host_invoked": True,
            "state_written": False,
            "quota_spent": False,
            "scheduler_acknowledged": False,
        },
    }
    return {
        "benchmark_id": "skillsbench@1.1",
        "product_mode": True,
        "official_score_status": "missing",
        "official_task_score": {"passed": False},
        "score_failure_attribution": "verifier_infrastructure_failure",
        "product_mode_lifecycle_contract": {
            "required": False,
            "satisfied": True,
            "closeout_satisfied": False,
            "state_read_count": 0,
            "state_write_count": 0,
        },
        "loopx_turn_executions": [failed_turn, dict(failed_turn)],
        "interaction_counters": {
            "product_mode_typed_repair_terminal": True,
            "product_mode_typed_repair_terminal_receipt_consistent": True,
            "product_mode_typed_repair_terminal_reason": (
                "turn_repair_round_without_todo_or_committed_validation_delta"
            ),
        },
        "case_event_timeline": {
            "schema_version": "skillsbench_case_event_timeline_v0",
            "source": "compact_public_signals",
            "raw_material_recorded": False,
            "events": [
                {
                    "phase": "goal_init",
                    "event": "case_goal_state_init",
                    "status": "passed",
                },
                {
                    "phase": "lifecycle",
                    "event": "orchestrated_loopx_lifecycle",
                    "status": "not_observed",
                },
                {
                    "phase": "bridge",
                    "event": "remote_command_bridge_consumption",
                    "status": "consumed",
                },
                {
                    "phase": "activity",
                    "event": "task_facing_activity",
                    "status": "task_activity_observed",
                },
                {
                    "phase": "controller",
                    "event": "controller_decision_loop",
                    "status": "typed_repair_terminal",
                },
                {
                    "phase": "scoring",
                    "event": "official_score_closeout",
                    "status": "missing",
                    "official_score_passed": False,
                },
                {
                    "phase": "closeout",
                    "event": "agent_bridge_closeout",
                    "status": "missing",
                },
            ],
        },
    }


def _turn_plan_repair_exhausted_compact() -> dict[str, object]:
    compact = _typed_repair_exhausted_compact()
    executions = compact["loopx_turn_executions"]
    assert isinstance(executions, list)
    executions[:] = [
        {
            "schema_version": "loopx_turn_execution_v0",
            "mode": "run_once",
            "status": "committed",
            "result_kind": "validated_progress",
            "validation": {"status": "passed"},
            "receipt": {"status": "committed"},
            "effects": {
                "host_invoked": True,
                "state_written": True,
                "quota_spent": True,
                "scheduler_acknowledged": False,
            },
        },
        {
            "schema_version": "loopx_turn_execution_v0",
            "mode": "run_once",
            "status": "failed",
            "result_kind": "repair_required",
            "receipt": {
                "status": "failed",
                "result_kind": "repair_required",
                "failed_phase": "turn_plan",
            },
            "effects": {
                "host_invoked": False,
                "state_written": False,
                "quota_spent": False,
                "scheduler_acknowledged": False,
            },
        },
    ]
    return compact


def test_status_preserves_skillsbench_post_run_debug_import() -> None:
    assert (
        status.build_skillsbench_post_run_debug_gate
        is build_skillsbench_post_run_debug_gate
    )


def test_non_skillsbench_rows_do_not_project_a_debug_gate() -> None:
    assert build_skillsbench_post_run_debug_gate({"benchmark_id": "other"}) == {}
    assert build_skillsbench_post_run_debug_gate({}) == {}


def test_missing_timeline_blocks_progress_with_public_boundary() -> None:
    gate = build_skillsbench_post_run_debug_gate(
        {
            "benchmark_id": "skillsbench@1.1",
            "official_task_score": {"passed": False, "value": 0.0},
        }
    )

    assert gate["packet_complete"] is False
    assert gate["case_closeout_complete"] is False
    assert gate["next_case_gate"] == "blocked_missing_debug_packet"
    assert gate["first_blocker"] == "case_event_timeline"
    assert gate["raw_material_recorded"] is False
    assert gate["boundary"] == {
        "task_text_read": False,
        "logs_read": False,
        "trajectory_read": False,
        "verifier_output_tail_public": False,
    }


def test_countable_zero_keeps_solution_level_attribution() -> None:
    gate = build_skillsbench_post_run_debug_gate(
        {
            "benchmark_id": "skillsbench@1.1",
            "official_score_status": "completed",
            "official_task_score": {"passed": False, "value": 0.0},
            "score_failure_attribution": "official_verifier_solution_failure",
            "failure_attribution_labels": ["official_verifier_solution_failure"],
            "case_event_timeline": {
                "schema_version": "skillsbench_case_event_timeline_v0",
                "source": "compact_public_signals",
                "raw_material_recorded": False,
                "events": [
                    {
                        "phase": "controller",
                        "event": "controller_decision_loop",
                        "status": "stopped_after_one_round",
                    },
                    {
                        "phase": "scoring",
                        "event": "official_score_closeout",
                        "status": "completed",
                        "official_score_passed": False,
                    },
                    {
                        "phase": "closeout",
                        "event": "agent_bridge_closeout",
                        "status": "missing",
                    },
                ],
            },
            "interaction_counters": {
                "remote_command_file_bridge_agent_task_facing_operation_count": 15,
            },
        }
    )

    assert gate["packet_complete"] is True
    assert gate["case_closeout_complete"] is True
    assert gate["normal_progress_allowed"] is True
    assert gate["next_case_gate"] == "open_with_attribution"
    assert gate["attribution_layer"] == "solution_level_unknown"
    assert gate["first_blocker"] == "official_verifier_solution_failure"


def test_typed_repair_exhaustion_opens_rotation_without_qualifying_turn() -> None:
    gate = build_skillsbench_post_run_debug_gate(
        _typed_repair_exhausted_compact()
    )

    transaction = gate["loopx_turn_transaction"]
    assert transaction["status"] == "validation_failed_typed_repair_exhausted"
    assert transaction["progress_blocked"] is True
    assert transaction["next_case_blocked"] is False
    assert transaction["typed_repair_exhausted"] is True
    assert transaction["case_exclusion_required"] is True
    assert transaction["recovery_status"] == "case_exclusion_required"
    assert gate["loopx_lifecycle"]["satisfied"] is False
    assert gate["loopx_lifecycle"]["closeout_status"] == (
        "turn_transaction_unqualified_case_excluded"
    )
    assert gate["attribution_layer"] == "loopx_turn_transaction"
    assert gate["first_blocker"] == "loopx_turn_validation_failed"
    assert gate["next_case_gate"] == "open_with_exclusion"
    assert gate["normal_progress_allowed"] is True
    assert gate["next_action"] == (
        "record_unqualified_case_arm_and_continue_after_protocol_rerun"
    )


def test_committed_prefix_does_not_hide_effect_free_typed_repair_exhaustion() -> None:
    compact = _typed_repair_exhausted_compact()
    executions = compact["loopx_turn_executions"]
    assert isinstance(executions, list)
    executions.insert(
        0,
        {
            "schema_version": "loopx_turn_execution_v0",
            "mode": "run_once",
            "status": "committed",
            "result_kind": "validated_progress",
            "validation": {"status": "progress"},
            "receipt": {"status": "committed"},
            "effects": {
                "host_invoked": True,
                "state_written": True,
                "quota_spent": True,
                "scheduler_acknowledged": False,
            },
        },
    )

    gate = build_skillsbench_post_run_debug_gate(compact)

    transaction = gate["loopx_turn_transaction"]
    assert transaction["committed_count"] == 1
    assert transaction["validation_failed_count"] == 2
    assert transaction["state_written_count"] == 1
    assert transaction["quota_spent_count"] == 1
    assert transaction["failed_transaction_with_durable_effect_count"] == 0
    assert transaction["typed_repair_exhausted"] is True
    assert transaction["next_case_blocked"] is False
    assert gate["next_case_gate"] == "open_with_exclusion"
    assert gate["normal_progress_allowed"] is True


def test_effect_free_turn_plan_repair_exhaustion_opens_rotation() -> None:
    gate = build_skillsbench_post_run_debug_gate(
        _turn_plan_repair_exhausted_compact()
    )

    transaction = gate["loopx_turn_transaction"]
    assert transaction["status"] == "recovery_required_typed_repair_exhausted"
    assert transaction["validation_failed_count"] == 0
    assert transaction["recovery_required_count"] == 1
    assert transaction["repair_required_count"] == 1
    assert transaction["typed_repair_exhausted"] is True
    assert transaction["case_exclusion_required"] is True
    assert transaction["first_blocker"] == "loopx_turn_repair_required"
    assert transaction["next_case_blocked"] is False
    assert gate["next_case_gate"] == "open_with_exclusion"
    assert gate["normal_progress_allowed"] is True


def test_turn_plan_repair_with_durable_effects_keeps_rotation_blocked() -> None:
    compact = _turn_plan_repair_exhausted_compact()
    executions = compact["loopx_turn_executions"]
    assert isinstance(executions, list)
    failed_execution = executions[-1]
    assert isinstance(failed_execution, dict)
    effects = failed_execution["effects"]
    assert isinstance(effects, dict)
    effects["state_written"] = True

    gate = build_skillsbench_post_run_debug_gate(compact)

    transaction = gate["loopx_turn_transaction"]
    assert transaction["status"] == (
        "inconsistent_failed_transaction_has_durable_effects"
    )
    assert transaction["failed_transaction_with_durable_effect_count"] == 1
    assert transaction["typed_repair_exhausted"] is False
    assert transaction["next_case_blocked"] is True
    assert gate["next_case_gate"] == "blocked_turn_transaction_repair"
    assert gate["normal_progress_allowed"] is False


def test_unrecognized_typed_repair_terminal_reason_keeps_rotation_blocked() -> None:
    compact = _typed_repair_exhausted_compact()
    counters = compact["interaction_counters"]
    assert isinstance(counters, dict)
    counters["product_mode_typed_repair_terminal_reason"] = "repair_pending"

    gate = build_skillsbench_post_run_debug_gate(compact)

    transaction = gate["loopx_turn_transaction"]
    assert transaction["typed_repair_exhausted"] is False
    assert transaction["next_case_blocked"] is True
    assert gate["next_case_gate"] == "blocked_turn_transaction_repair"
    assert gate["normal_progress_allowed"] is False


def test_failed_turn_durable_effect_keeps_rotation_blocked() -> None:
    compact = _typed_repair_exhausted_compact()
    executions = compact["loopx_turn_executions"]
    assert isinstance(executions, list)
    execution = executions[0]
    assert isinstance(execution, dict)
    effects = execution["effects"]
    assert isinstance(effects, dict)
    effects["state_written"] = True

    gate = build_skillsbench_post_run_debug_gate(compact)

    transaction = gate["loopx_turn_transaction"]
    assert transaction["status"] == (
        "inconsistent_failed_transaction_has_durable_effects"
    )
    assert transaction["typed_repair_exhausted"] is False
    assert transaction["next_case_blocked"] is True
    assert gate["next_case_gate"] == "blocked_turn_transaction_repair"
    assert gate["normal_progress_allowed"] is False

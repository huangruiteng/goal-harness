#!/usr/bin/env python3
"""Smoke-test SkillsBench post-run debug gate attribution edges."""

from __future__ import annotations

import copy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.status import build_skillsbench_post_run_debug_gate  # noqa: E402


def test_countable_zero_keeps_solution_attribution() -> None:
    compact = {
        "benchmark_id": "skillsbench@1.1",
        "official_score": 0.0,
        "official_score_status": "completed",
        "official_task_score": {
            "kind": "skillsbench_verifier_reward",
            "passed": False,
            "value": 0.0,
        },
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
            "remote_command_file_bridge_agent_task_facing_success_count": 15,
        },
    }

    gate = build_skillsbench_post_run_debug_gate(compact)

    assert gate["packet_complete"] is True, gate
    assert gate["case_closeout_complete"] is True, gate
    assert gate["normal_progress_allowed"] is True, gate
    assert gate["next_case_gate"] == "open_with_attribution", gate
    assert gate["attribution_layer"] == "solution_level_unknown", gate
    assert gate["first_blocker"] == "official_verifier_solution_failure", gate
    assert gate["missing_field_count"] == 0, gate


def test_failed_turn_receipts_qualify_direct_lifecycle_success() -> None:
    turn_execution = {
        "schema_version": "loopx_turn_execution_v0",
        "mode": "run_once",
        "status": "failed",
        "result_kind": "repair_required",
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
    compact = {
        "benchmark_id": "skillsbench@1.1",
        "product_mode": True,
        "official_score": 0.0,
        "official_score_status": "completed",
        "official_task_score": {
            "kind": "skillsbench_verifier_reward",
            "passed": False,
            "value": 0.0,
        },
        "score_failure_attribution": "official_score_zero_case_failure",
        "failure_attribution_labels": [
            "skillsbench_runner_error",
            "official_score_zero_case_failure",
            "partial_trajectory",
        ],
        "product_mode_lifecycle_contract": {
            "required": True,
            "satisfied": True,
            "closeout_satisfied": True,
            "state_read_count": 8,
            "state_write_count": 8,
            "agent_bridge_todo_closeout_count": 1,
            "agent_bridge_refresh_state_count": 4,
            "agent_bridge_quota_spend_slot_count": 1,
        },
        "loopx_turn_executions": [dict(turn_execution), dict(turn_execution)],
        "case_event_timeline": {
            "schema_version": "skillsbench_case_event_timeline_v0",
            "source": "compact_public_signals",
            "raw_material_recorded": False,
            "events": [
                {
                    "phase": "goal_init",
                    "event": "case_goal_state_init",
                    "status": "satisfied",
                },
                {
                    "phase": "controller",
                    "event": "controller_decision_loop",
                    "status": "stopped_after_two_rounds",
                },
                {
                    "phase": "lifecycle",
                    "event": "orchestrated_loopx_lifecycle",
                    "status": "satisfied",
                    "state_read_count": 8,
                    "state_write_count": 8,
                },
                {
                    "phase": "bridge",
                    "event": "remote_command_bridge_consumption",
                    "status": "satisfied",
                },
                {
                    "phase": "activity",
                    "event": "task_facing_activity",
                    "status": "satisfied",
                    "agent_bridge_task_facing_operation_count": 48,
                },
                {
                    "phase": "closeout",
                    "event": "agent_bridge_closeout",
                    "status": "satisfied",
                    "todo_closeout_count": 1,
                    "refresh_state_count": 4,
                    "quota_spend_slot_count": 1,
                },
                {
                    "phase": "scoring",
                    "event": "official_score_closeout",
                    "status": "completed",
                    "official_score_passed": False,
                },
            ],
        },
    }

    gate = build_skillsbench_post_run_debug_gate(compact)

    assert gate["packet_complete"] is True, gate
    assert gate["case_closeout_complete"] is True, gate
    assert gate["normal_progress_allowed"] is False, gate
    assert gate["next_case_gate"] == "blocked_turn_transaction_repair", gate
    assert gate["attribution_layer"] == "loopx_turn_transaction", gate
    assert gate["first_blocker"] == "loopx_turn_validation_failed", gate
    assert gate["loopx_lifecycle"]["direct_lifecycle_satisfied"] is True, gate
    assert gate["loopx_lifecycle"]["satisfied"] is False, gate
    assert gate["loopx_lifecycle"]["direct_closeout_status"] == "satisfied", gate
    assert (
        gate["loopx_lifecycle"]["closeout_status"]
        == "turn_transaction_repair_required"
    ), gate
    transaction = gate["loopx_turn_transaction"]
    assert transaction["status"] == "validation_failed", transaction
    assert transaction["causal_consistency"] == (
        "validation_failure_effects_not_committed"
    ), transaction
    assert transaction["recovery_status"] == "repair_required", transaction
    assert transaction["execution_count"] == 2, transaction
    assert transaction["validation_failed_count"] == 2, transaction
    assert transaction["committed_count"] == 0, transaction
    assert transaction["state_written_count"] == 0, transaction
    assert transaction["quota_spent_count"] == 0, transaction

    committed_compact = copy.deepcopy(compact)
    for execution in committed_compact["loopx_turn_executions"]:
        execution["status"] = "committed"
        execution["result_kind"] = "validated_progress"
        execution["validation"] = {"status": "passed"}
        execution["receipt"] = {"status": "committed"}
        execution["effects"]["state_written"] = True
        execution["effects"]["quota_spent"] = True
    committed_gate = build_skillsbench_post_run_debug_gate(committed_compact)
    assert committed_gate["normal_progress_allowed"] is True, committed_gate
    assert committed_gate["loopx_lifecycle"]["satisfied"] is True, committed_gate
    assert committed_gate["loopx_lifecycle"]["closeout_status"] == "satisfied", (
        committed_gate
    )
    assert committed_gate["loopx_turn_transaction"]["status"] == "committed", (
        committed_gate
    )


def test_fatal_provider_turn_has_complete_capacity_blocked_closeout() -> None:
    compact = {
        "benchmark_id": "skillsbench@1.1",
        "product_mode": True,
        "official_score_status": "missing",
        "score_failure_attribution": (
            "skillsbench_host_local_acp_codex_exec_failed_codex_usage_limit"
        ),
        "failure_attribution_labels": [
            "skillsbench_host_local_acp_codex_exec_failed_codex_usage_limit"
        ],
        "product_mode_lifecycle_contract": {
            "required": True,
            "satisfied": False,
            "closeout_satisfied": False,
            "state_read_count": 0,
            "state_write_count": 0,
        },
        "loopx_turn_executions": [
            {
                "schema_version": "loopx_turn_execution_v0",
                "mode": "run_once",
                "status": "failed",
                "result_kind": "host_failure",
                "validation": {},
                "receipt": {
                    "status": "failed",
                    "failed_phase": "host_execute",
                },
                "effects": {
                    "host_invoked": True,
                    "state_written": False,
                    "quota_spent": False,
                    "scheduler_acknowledged": False,
                },
            }
        ],
        "interaction_counters": {
            "host_local_acp_codex_exec_failure_trace_present": True,
            "host_local_acp_codex_exec_failure_trace_count": 1,
            "host_local_acp_codex_exec_fatal_failure_trace_count": 1,
            "host_local_acp_codex_exec_recoverable_failure_trace_count": 0,
            "host_local_acp_codex_exec_failure_categories": [
                "codex_usage_limit"
            ],
            "host_local_acp_codex_exec_failure_category": "codex_usage_limit",
            "product_mode_typed_repair_terminal": True,
            "product_mode_typed_repair_terminal_receipt_consistent": True,
            "product_mode_typed_repair_terminal_reason": (
                "nonrecoverable_turn_host_failure"
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
                    "status": "satisfied",
                },
                {
                    "phase": "controller",
                    "event": "controller_decision_loop",
                    "status": "stopped_after_fatal_provider_failure",
                    "action_decision_count": 2,
                    "initial_prompt_count": 1,
                    "followup_prompt_count": 0,
                    "stop_decision_count": 1,
                },
                {
                    "phase": "lifecycle",
                    "event": "orchestrated_loopx_lifecycle",
                    "status": "not_started",
                    "state_read_count": 0,
                    "state_write_count": 0,
                },
                {
                    "phase": "bridge",
                    "event": "remote_command_bridge_consumption",
                    "status": "satisfied",
                },
                {
                    "phase": "activity",
                    "event": "task_facing_activity",
                    "status": "missing_agent_operation_trace",
                    "agent_bridge_task_facing_operation_count": 0,
                },
                {
                    "phase": "closeout",
                    "event": "agent_bridge_closeout",
                    "status": "missing",
                },
                {
                    "phase": "scoring",
                    "event": "official_score_closeout",
                    "status": "missing",
                    "official_score_passed": None,
                },
            ],
        },
    }

    gate = build_skillsbench_post_run_debug_gate(compact)

    assert gate["packet_complete"] is True, gate
    assert gate["case_closeout_complete"] is True, gate
    assert gate["normal_progress_allowed"] is False, gate
    assert gate["next_case_gate"] == "blocked_external_provider_capacity", gate
    assert gate["next_action"] == (
        "retry_same_case_after_host_provider_capacity"
    ), gate
    assert gate["attribution_layer"] == "host_provider", gate
    assert gate["first_blocker"] == (
        "skillsbench_host_local_acp_codex_exec_failed_codex_usage_limit"
    ), gate
    assert gate["loopx_lifecycle"]["direct_lifecycle_satisfied"] is False, gate
    assert gate["loopx_lifecycle"]["satisfied"] is True, gate
    assert gate["loopx_lifecycle"]["closeout_status"] == (
        "host_provider_failure_terminal"
    ), gate
    transaction = gate["loopx_turn_transaction"]
    assert transaction["status"] == "host_failure_terminal", transaction
    assert transaction["progress_blocked"] is False, transaction
    assert transaction["recovery_status"] == (
        "retry_after_provider_capacity"
    ), transaction
    assert transaction["execution_count"] == 1, transaction
    assert transaction["host_failure_count"] == 1, transaction
    assert transaction["committed_count"] == 0, transaction
    assert transaction["state_written_count"] == 0, transaction
    assert transaction["quota_spent_count"] == 0, transaction


def test_exhausted_typed_repair_opens_case_rotation_with_exclusion() -> None:
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
    compact = {
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

    gate = build_skillsbench_post_run_debug_gate(compact)

    assert gate["normal_progress_allowed"] is True, gate
    assert gate["next_case_gate"] == "open_with_exclusion", gate
    assert gate["loopx_lifecycle"]["satisfied"] is False, gate
    transaction = gate["loopx_turn_transaction"]
    assert transaction["progress_blocked"] is True, transaction
    assert transaction["next_case_blocked"] is False, transaction
    assert transaction["case_exclusion_required"] is True, transaction


def main() -> None:
    test_countable_zero_keeps_solution_attribution()
    test_failed_turn_receipts_qualify_direct_lifecycle_success()
    test_fatal_provider_turn_has_complete_capacity_blocked_closeout()
    test_exhausted_typed_repair_opens_case_rotation_with_exclusion()
    print("skillsbench-post-run-debug-gate-smoke: ok")


if __name__ == "__main__":
    main()

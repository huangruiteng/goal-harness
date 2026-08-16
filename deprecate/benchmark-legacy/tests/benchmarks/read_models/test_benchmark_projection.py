from __future__ import annotations

from loopx.benchmark_adapters.skillsbench_signals import (
    build_skillsbench_solution_quality_signals,
)
from loopx.benchmarks.read_models.benchmark_projection import (
    build_benchmark_solution_quality_signals,
    compact_benchmark_run_trials,
    compact_benchmark_run_validation,
)
from loopx.benchmarks.read_models.benchmark_run_execution_contract import (
    compact_benchmark_run_execution_contract,
)
from loopx.benchmarks.read_models.benchmark_run_pre_execution import (
    compact_benchmark_run_pre_execution_metadata,
)
from loopx.status import compact_benchmark_run


def test_generic_solution_quality_projection_preserves_legacy_adapter_parity() -> None:
    benchmark_run = {
        "benchmark_id": "terminal-bench@2.0",
        "official_score": 0.5,
        "interaction_counters": {
            "remote_command_file_bridge_agent_task_facing_operation_count": 2,
        },
        "failure_attribution_labels": ["partial_trajectory"],
    }

    generic = build_benchmark_solution_quality_signals(benchmark_run)

    assert generic == build_skillsbench_solution_quality_signals(benchmark_run)
    assert generic["schema_version"] == "skillsbench_solution_quality_signals_v0"
    assert generic["outcome_class"] == "partial_nonpass"
    assert generic["worker_activity"]["task_facing_activity_observed"] is True
    assert generic["solution_action_labels"] == [
        "partial_nonpass_official_score",
        "partial_trajectory_public_label_present",
        "rubric_miss_labels_unavailable_compact_only",
    ]


def test_benchmark_validation_projection_preserves_neutral_false_and_failures() -> None:
    validation = {
        "validation_scope": "public compact",
        "case_success_claimed": False,
        "bridge_connected": True,
        "patch_applied_in_container": False,
        "native_goal_worker_trace_count": 2,
    }

    compact = compact_benchmark_run_validation(
        validation,
        pre_agent_setup_materialization_blocked=False,
        max_list_items=8,
    )

    assert compact == {
        "all_passed": False,
        "failed_checks": ["patch_applied_in_container"],
        "validation_scope": "public compact",
        "native_goal_worker_trace_count": 2,
        "bridge_connected": True,
        "case_success_claimed": False,
        "patch_applied_in_container": False,
    }


def test_benchmark_validation_projection_attributes_missing_trace_or_setup() -> None:
    validation = {
        "native_goal_worker_route": True,
        "native_goal_worker_trace_status": "worker_connected_no_turn_trace",
    }

    missing_trace = compact_benchmark_run_validation(
        validation,
        pre_agent_setup_materialization_blocked=False,
        max_list_items=8,
    )
    setup_blocked = compact_benchmark_run_validation(
        validation,
        pre_agent_setup_materialization_blocked=True,
        max_list_items=8,
    )

    assert missing_trace["failed_checks"] == ["native_goal_worker_public_trace_missing"]
    assert setup_blocked["failed_checks"] == ["pre_agent_setup_materialization_blocked"]
    assert missing_trace["all_passed"] is False
    assert setup_blocked["all_passed"] is False


def test_benchmark_trial_projection_is_bounded_and_public_safe() -> None:
    trials = [
        "ignored",
        {
            "task_id": "task-1",
            "reward": {"score": 1, "invalid": "drop"},
            "metrics": {"input_tokens": 4, "extra": 9},
            "trajectory_present": False,
            "verifier_failure_attribution_labels": ["first", "second"],
            "official_zero_observation": {
                "schema_version": "official_zero_observation_v0",
                "reward_value": 0,
                "detected": True,
                "raw_logs_read": False,
            },
        },
        {"task_id": "task-2"},
    ]

    compact = compact_benchmark_run_trials(
        trials,
        max_trials=1,
        max_list_items=1,
    )

    assert compact == [
        {
            "task_id": "task-1",
            "verifier_failure_attribution_labels": ["first"],
            "reward": {"score": 1},
            "metrics": {"input_tokens": 4},
            "trajectory_present": False,
            "official_zero_observation": {
                "schema_version": "official_zero_observation_v0",
                "reward_value": 0,
                "detected": True,
                "raw_logs_read": False,
            },
        }
    ]


def test_status_facade_uses_benchmark_validation_and_trial_read_models() -> None:
    source = {
        "schema_version": "benchmark_run_v0",
        "source_runner": "fixture",
        "validation": {
            "bridge_connected": False,
            "case_success_claimed": False,
        },
        "trials": [
            {
                "task_id": "task-1",
                "metrics": {"input_tokens": 3},
                "trial_result_present": True,
            }
        ],
    }

    compact = compact_benchmark_run(source)

    assert compact is not None
    assert compact["validation"]["failed_checks"] == ["bridge_connected"]
    assert compact["validation"]["case_success_claimed"] is False
    assert compact["trials"] == [
        {
            "task_id": "task-1",
            "metrics": {"input_tokens": 3},
            "trial_result_present": True,
        }
    ]
    assert compact["trial_count"] == 1


def test_status_facade_compacts_benchmark_execution_contract_metadata() -> None:
    source = {
        "schema_version": "benchmark_run_v0",
        "official_score": 0.5,
        "official_task_score": {"kind": "pass", "value": 1, "passed": True},
        "benchmark_loop_contract": {
            "schema_version": "benchmark_loop_contract_v0",
            "route": "native-goal-worker",
            "protocol_id": "protocol-1",
            "claim_blocker": "official feedback remains blinded",
            "official_feedback_forwarded": False,
            "official_feedback_blinded": True,
            "blind_loop": True,
            "product_mode": True,
            "strict_treatment_claim_allowed": False,
            "max_rounds_budget": 3,
            "private_note": "drop",
        },
        "claim_boundary": {
            "public_claim_allowed": "connectivity only",
            "bridge_connectivity_claim_allowed": True,
            "case_success_claim_allowed": False,
            "official_score_claim_allowed": False,
            "leaderboard_claim_allowed": False,
            "forbidden_claims": [f"claim-{index}" for index in range(9)],
            "private_note": "drop",
        },
        "agent": {
            "name": "loopx-agent",
            "import_path": "loopx.agent:Agent",
            "model": "model-1",
            "kwargs_keys": [f"key-{index}" for index in range(9)],
            "private_note": "drop",
        },
        "model_control": {
            "schema_version": "model_control_v0",
            "requested_model": "model-1",
            "reported_model": "model-1",
            "control_method": "explicit",
            "control_status": "verified",
            "actual_model_source": "runner",
            "actual_model_verified": True,
            "warning_labels": [f"warning-{index}" for index in range(9)],
            "private_note": "drop",
        },
    }

    expected = {
        "benchmark_loop_contract": {
            "schema_version": "benchmark_loop_contract_v0",
            "route": "native-goal-worker",
            "protocol_id": "protocol-1",
            "claim_blocker": "official feedback remains blinded",
            "official_feedback_forwarded": False,
            "official_feedback_blinded": True,
            "blind_loop": True,
            "product_mode": True,
            "strict_treatment_claim_allowed": False,
            "max_rounds_budget": 3,
        },
        "claim_boundary": {
            "public_claim_allowed": "connectivity only",
            "bridge_connectivity_claim_allowed": True,
            "case_success_claim_allowed": False,
            "official_score_claim_allowed": False,
            "leaderboard_claim_allowed": False,
            "forbidden_claims": [f"claim-{index}" for index in range(5)],
        },
        "agent": {
            "name": "loopx-agent",
            "import_path": "loopx.agent:Agent",
            "model": "model-1",
            "kwargs_keys": [f"key-{index}" for index in range(5)],
        },
        "model_control": {
            "schema_version": "model_control_v0",
            "requested_model": "model-1",
            "reported_model": "model-1",
            "control_method": "explicit",
            "control_status": "verified",
            "actual_model_source": "runner",
            "actual_model_verified": True,
            "warning_labels": [f"warning-{index}" for index in range(5)],
        },
    }

    assert (
        compact_benchmark_run_execution_contract(source, max_list_items=5) == expected
    )
    compact = compact_benchmark_run(source)
    assert compact is not None
    assert {key: compact[key] for key in expected} == expected
    keys = list(compact)
    assert keys.index("benchmark_loop_contract") < keys.index("official_score")
    assert keys.index("official_task_score") < keys.index("claim_boundary")
    assert (
        keys.index("claim_boundary") < keys.index("agent") < keys.index("model_control")
    )


def test_status_facade_preserves_benchmark_pre_execution_metadata_order() -> None:
    source = {
        "schema_version": "benchmark_run_v0",
        "benchmark_loop_contract": {"schema_version": "benchmark_loop_contract_v0"},
        "official_score": 0.5,
        "failure_attribution_labels": [f"failure-{index}" for index in range(6)],
        "worker_startup_blockers": ["startup-blocker"],
        "worker_setup_diagnostic_blockers": ["setup-blocker"],
        "runner_warning_labels": ["runner-warning"],
        "runner_prerequisites": {
            "schema_version": "runner_prerequisites_v0",
            "host_local_acp_launch": True,
            "benchmark_live_worker_phase": {
                "schema_version": "benchmark_live_worker_phase_v0",
                "current_phase": "worker_running",
                "next_required_phase": "agent_active",
                "phase_ready": {
                    "runtime_preparing": True,
                    "worker_prepared": True,
                    "worker_running": True,
                    "agent_active": False,
                },
                "worker_live": True,
                "agent_active_observed": False,
                "terminal": False,
                "terminal_disposition": "open",
                "public_evidence_only": True,
                "private_detail": "drop",
            },
            "private_detail": "drop",
        },
        "result_discovery": {
            "schema_version": "result_discovery_v0",
            "candidate_count": 2,
            "selection_reasons": [f"reason-{index}" for index in range(6)],
            "private_detail": "drop",
        },
        "task_setup_preflight": {
            "schema_version": "task_setup_preflight_v0",
            "status": "ready",
            "raw_logs_read": False,
            "nearest_canonical_task_ids": [f"task-{index}" for index in range(6)],
            "private_detail": "drop",
        },
        "task_staging": {
            "schema_version": "task_staging_v0",
            "staged": True,
            "resource_cap_patch": {
                "schema_version": "resource_cap_patch_v0",
                "applied": True,
                "host_cpus": 8,
                "private_detail": "drop",
            },
            "private_detail": "drop",
        },
        "attempt_accounting": {
            "schema_version": "attempt_accounting_v0",
            "lifecycle_phase": "solver",
            "solver_attempt_countable": True,
            "attempts": {
                "solver": {"attempted": True, "countable": True, "private": True}
            },
            "private_detail": "drop",
        },
        "official_task_score": {
            "kind": "pass",
            "value": 1,
            "passed": True,
            "private_detail": "drop",
        },
        "claim_boundary": {"public_claim_allowed": "connectivity only"},
    }

    compact = compact_benchmark_run(source)
    pre_execution = compact_benchmark_run_pre_execution_metadata(
        source,
        max_list_items=5,
    )

    assert compact is not None
    assert {key: compact[key] for key in pre_execution} == pre_execution
    assert compact["failure_attribution_labels"] == [
        f"failure-{index}" for index in range(5)
    ]
    assert compact["runner_prerequisites"] == {
        "schema_version": "runner_prerequisites_v0",
        "host_local_acp_launch": True,
    }
    assert compact["result_discovery"] == {
        "schema_version": "result_discovery_v0",
        "candidate_count": 2,
        "selection_reasons": [f"reason-{index}" for index in range(5)],
    }
    assert compact["task_setup_preflight"] == {
        "schema_version": "task_setup_preflight_v0",
        "status": "ready",
        "raw_logs_read": False,
        "nearest_canonical_task_ids": [f"task-{index}" for index in range(5)],
    }
    assert compact["task_staging"] == {
        "schema_version": "task_staging_v0",
        "staged": True,
        "resource_cap_patch": {
            "schema_version": "resource_cap_patch_v0",
            "applied": True,
            "host_cpus": 8,
        },
    }
    assert compact["attempt_accounting"] == {
        "schema_version": "attempt_accounting_v0",
        "lifecycle_phase": "solver",
        "solver_attempt_countable": True,
        "attempts": {"solver": {"attempted": True, "countable": True}},
    }
    assert compact["official_task_score"] == {
        "kind": "pass",
        "value": 1,
        "passed": True,
    }
    expected_order = [
        "benchmark_loop_contract",
        "official_score",
        "failure_attribution_labels",
        "worker_startup_blockers",
        "worker_setup_diagnostic_blockers",
        "runner_warning_labels",
        "runner_prerequisites",
        "benchmark_live_worker_phase",
        "result_discovery",
        "task_setup_preflight",
        "task_staging",
        "attempt_accounting",
        "official_task_score",
        "claim_boundary",
    ]
    keys = list(compact)
    assert [key for key in keys if key in expected_order] == expected_order

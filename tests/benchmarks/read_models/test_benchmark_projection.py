from __future__ import annotations

from loopx.benchmark_adapters.skillsbench_signals import (
    build_skillsbench_solution_quality_signals,
)
from loopx.benchmarks.read_models.benchmark_projection import (
    build_benchmark_solution_quality_signals,
    compact_benchmark_run_trials,
    compact_benchmark_run_validation,
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

from __future__ import annotations

from loopx.benchmarks.read_models.benchmark_run_post_execution import (
    compact_benchmark_run_post_execution_metadata,
)
from loopx.status import compact_benchmark_run


def test_post_execution_lifecycle_repair_runs_after_interaction_projection() -> None:
    compact = compact_benchmark_run(
        {
            "schema_version": "benchmark_run_v0",
            "official_score": 0,
            "score_failure_attribution": ("skillsbench_product_mode_lifecycle_missing"),
            "failure_attribution_labels": [
                "skillsbench_product_mode_lifecycle_missing",
                "official_score_zero_case_failure",
            ],
            "interaction_counters": {
                "product_mode_solver_activity_gap": True,
                "product_mode_solver_activity_missing_reason": (
                    "missing_task_facing_activity_or_agent_closeout_before_declared_done"
                ),
            },
            "product_mode_lifecycle_contract": {
                "required": True,
                "satisfied": True,
                "countable_treatment": True,
            },
        }
    )

    assert compact is not None
    assert (
        compact["score_failure_attribution"]
        == "skillsbench_product_mode_solver_activity_gap"
    )
    assert compact["failure_attribution_labels"] == [
        "skillsbench_product_mode_solver_activity_gap"
    ]


def test_benchmark_post_execution_metadata_preserves_order_and_boundaries() -> None:
    source = {
        "schema_version": "benchmark_run_v0",
        "runner_failure": {
            "schema_version": "runner_failure_v0",
            "failure_class": "runner_error",
            "private_detail": "drop",
        },
        "runner_failure_fingerprint": {
            "schema_version": "runner_failure_fingerprint_v0",
            "matched_patterns": [f"pattern-{index}" for index in range(6)],
            "private_detail": "drop",
        },
        "compose_setup_diagnostic": {
            "schema_version": "compose_setup_diagnostic_v0",
            "status": "observed",
        },
        "progress": {"n_total_trials": 2, "n_completed_trials": 1, "extra": 9},
        "metrics": {"input_tokens": 4, "cost_usd": 0.1, "extra": 9},
        "interaction_counters": {
            "schema_version": "interaction_counters_v0",
            "product_mode": True,
        },
        "episode_policy": {
            "schema_version": "episode_policy_v0",
            "mode": "bounded",
            "private_detail": "drop",
        },
        "product_mode_lifecycle_contract": {
            "schema_version": "product_mode_lifecycle_contract_v0",
            "required": False,
            "private_detail": "drop",
        },
        "native_goal_worker_contract": {
            "schema_version": "native_goal_worker_contract_v0",
            "required": True,
            "private_detail": "drop",
        },
        "app_server_goal_round_semantics": {
            "schema_version": "app_server_goal_round_semantics_v0",
            "route": "native",
            "private_detail": "drop",
        },
        "preflight_guard": {
            "schema_version": "preflight_guard_v0",
            "runner_surface_checked": True,
        },
        "active_user_assisted_treatment_preflight": {
            "schema_version": "active_user_preflight_v0",
            "proactive_intervention_allowed": True,
            "private_detail": "drop",
        },
        "active_user_private_launcher_plan": {
            "schema_version": "active_user_launcher_v0",
            "ready": False,
            "private_detail": "drop",
        },
        "active_user_observation": {
            "schema_version": "active_user_observation_v0",
            "feed_present": True,
            "private_detail": "drop",
        },
        "claim_gate": {
            "schema_version": "claim_gate_v0",
            "uplift_claim_allowed": False,
            "private_detail": "drop",
        },
        "private_runner_launch_summary": {
            "schema_version": "private_runner_launch_v0",
            "ready": False,
        },
        "setup_timeout_repair_profile": {
            "schema_version": "setup_timeout_repair_profile_v0",
            "enabled": True,
        },
        "environment_setup_failure_context": {
            "schema_version": "environment_setup_failure_context_v0",
            "surface": "worker_startup",
            "private_detail": "drop",
        },
        "worker_bridge_outcome": {
            "schema_version": "worker_bridge_outcome_v0",
            "worker_bridge_verified": True,
            "private_detail": "drop",
        },
    }

    metadata = compact_benchmark_run_post_execution_metadata(
        source,
        max_list_items=1,
    )

    assert list(metadata.failure) == [
        "runner_failure",
        "runner_failure_fingerprint",
    ]
    assert metadata.progress_metrics == {
        "progress": {"n_total_trials": 2, "n_completed_trials": 1},
        "metrics": {"input_tokens": 4, "cost_usd": 0.1},
    }
    assert list(metadata.lifecycle) == [
        "episode_policy",
        "product_mode_lifecycle_contract",
        "native_goal_worker_contract",
        "app_server_goal_round_semantics",
    ]
    assert list(metadata.active_user_and_claim) == [
        "active_user_assisted_treatment_preflight",
        "active_user_private_launcher_plan",
        "active_user_observation",
        "claim_gate",
    ]
    assert list(metadata.worker_outcome) == [
        "environment_setup_failure_context",
        "worker_bridge_outcome",
    ]
    assert metadata.failure["runner_failure_fingerprint"]["matched_patterns"] == [
        f"pattern-{index}" for index in range(4)
    ]
    assert all(
        "private_detail" not in section
        for group in (
            metadata.failure,
            metadata.lifecycle,
            metadata.active_user_and_claim,
            metadata.worker_outcome,
        )
        for section in group.values()
    )

    compact = compact_benchmark_run(source)
    assert compact is not None
    expected_order = [
        "runner_failure",
        "runner_failure_fingerprint",
        "compose_setup_diagnostic",
        "progress",
        "metrics",
        "interaction_counters",
        "episode_policy",
        "product_mode_lifecycle_contract",
        "native_goal_worker_contract",
        "app_server_goal_round_semantics",
        "preflight_guard",
        "active_user_assisted_treatment_preflight",
        "active_user_private_launcher_plan",
        "active_user_observation",
        "claim_gate",
        "private_runner_launch_summary",
        "setup_timeout_repair_profile",
        "environment_setup_failure_context",
        "worker_bridge_outcome",
    ]
    keys = list(compact)
    assert [key for key in keys if key in expected_order] == expected_order

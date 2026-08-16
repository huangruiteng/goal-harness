from __future__ import annotations

from loopx.status import compact_benchmark_run


def test_status_facade_compacts_benchmark_runner_failure_diagnostics() -> None:
    compact = compact_benchmark_run(
        {
            "schema_version": "benchmark_run_v0",
            "runner_failure": {
                "schema_version": "runner_failure_v0",
                "exception_type": "RuntimeError",
                "failure_class": "runner_timeout",
                "raw_error_recorded": False,
                "raw_logs_read": False,
                "raw_task_text_read": False,
                "raw_trajectory_read": False,
                "controller_cutoff": {
                    "schema_version": "controller_cutoff_v0",
                    "reason": "followup_budget_exhausted",
                    "cutoff_before_followup": True,
                    "max_rounds_budget": 3,
                    "initial_prompt_count": 1,
                    "followup_prompt_count": 2,
                    "stop_decision_count": 1,
                    "private_detail": "drop",
                },
                "user_loop_recovery": {
                    "schema_version": "user_loop_recovery_v0",
                    "stage": "soft_verify",
                    "exception_type": "TimeoutError",
                    "preserved_final_verify": True,
                    "raw_error_recorded": False,
                    "round": 2,
                    "delta_events": 4,
                    "delta_tool_calls": 3,
                    "private_detail": "drop",
                },
                "native_goal_worker": {
                    "schema_version": "native_goal_worker_failure_v0",
                    "trace_status": "worker_failed",
                    "failure_label": "first_action_timeout",
                    "failure_category": "codex_exec_timeout",
                    "first_blocker": "task_output_quiet_timeout",
                    "trace_count": 4,
                    "raw_transcript_recorded": False,
                    "raw_assistant_message_recorded": False,
                    "private_detail": "drop",
                },
                "private_detail": "drop",
            },
            "runner_failure_fingerprint": {
                "schema_version": "runner_failure_fingerprint_v0",
                "error_len_bucket": "short",
                "fingerprint_confidence": "high",
                "apt_failure_subtype": "repository_unreachable",
                "pip_failure_subtype": "index_unreachable",
                "retryability": "retryable",
                "line_count": 7,
                "matched_patterns": ["timeout", "network"],
                "failure_line_dependency_classes": ["apt", "pip"],
                "failure_reason_codes": ["egress_blocked"],
                "terminal_failure_dependency_classes": ["network"],
                "terminal_failure_reason_codes": ["timeout"],
                "failure_dependency_endpoints": ["package-index"],
                "terminal_failure_dependency_endpoints": ["package-index"],
                "error_present": True,
                "has_host_paths": False,
                "has_urls": False,
                "has_secret_like_tokens": False,
                "raw_error_recorded": False,
                "private_detail": "drop",
            },
        }
    )

    assert compact is not None
    assert compact["runner_failure"] == {
        "schema_version": "runner_failure_v0",
        "exception_type": "RuntimeError",
        "failure_class": "runner_timeout",
        "raw_error_recorded": False,
        "raw_logs_read": False,
        "raw_task_text_read": False,
        "raw_trajectory_read": False,
        "controller_cutoff": {
            "schema_version": "controller_cutoff_v0",
            "reason": "followup_budget_exhausted",
            "cutoff_before_followup": True,
            "max_rounds_budget": 3,
            "initial_prompt_count": 1,
            "followup_prompt_count": 2,
            "stop_decision_count": 1,
        },
        "user_loop_recovery": {
            "schema_version": "user_loop_recovery_v0",
            "stage": "soft_verify",
            "exception_type": "TimeoutError",
            "preserved_final_verify": True,
            "raw_error_recorded": False,
            "round": 2,
            "delta_events": 4,
            "delta_tool_calls": 3,
        },
        "native_goal_worker": {
            "schema_version": "native_goal_worker_failure_v0",
            "trace_status": "worker_failed",
            "failure_label": "first_action_timeout",
            "failure_category": "codex_exec_timeout",
            "first_blocker": "task_output_quiet_timeout",
            "trace_count": 4,
            "raw_transcript_recorded": False,
            "raw_assistant_message_recorded": False,
        },
    }
    assert compact["runner_failure_fingerprint"] == {
        "schema_version": "runner_failure_fingerprint_v0",
        "error_len_bucket": "short",
        "fingerprint_confidence": "high",
        "apt_failure_subtype": "repository_unreachable",
        "pip_failure_subtype": "index_unreachable",
        "retryability": "retryable",
        "line_count": 7,
        "matched_patterns": ["timeout", "network"],
        "failure_line_dependency_classes": ["apt", "pip"],
        "failure_reason_codes": ["egress_blocked"],
        "terminal_failure_dependency_classes": ["network"],
        "terminal_failure_reason_codes": ["timeout"],
        "failure_dependency_endpoints": ["package-index"],
        "terminal_failure_dependency_endpoints": ["package-index"],
        "error_present": True,
        "has_host_paths": False,
        "has_urls": False,
        "has_secret_like_tokens": False,
        "raw_error_recorded": False,
    }


def test_status_facade_rejects_invalid_runner_failure_diagnostic_types() -> None:
    compact = compact_benchmark_run(
        {
            "schema_version": "benchmark_run_v0",
            "runner_failure": {
                "raw_error_recorded": "false",
                "controller_cutoff": {"max_rounds_budget": True},
                "user_loop_recovery": {"round": False},
                "native_goal_worker": {"trace_count": True},
            },
            "runner_failure_fingerprint": {
                "line_count": False,
                "error_present": 1,
            },
        }
    )

    assert compact is not None
    assert "runner_failure" not in compact
    assert "runner_failure_fingerprint" not in compact

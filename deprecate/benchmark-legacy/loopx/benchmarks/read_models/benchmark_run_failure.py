from __future__ import annotations

from typing import Any

from ...control_plane.runtime.public_safety import (
    public_safe_compact_list,
    public_safe_compact_text,
)


def compact_benchmark_runner_failure(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact = _compact_fields(
        value,
        text_fields=("schema_version", "exception_type", "failure_class"),
        bool_fields=(
            "raw_error_recorded",
            "raw_logs_read",
            "raw_task_text_read",
            "raw_trajectory_read",
        ),
    )
    for field, compactor in (
        ("controller_cutoff", _compact_controller_cutoff),
        ("user_loop_recovery", _compact_user_loop_recovery),
        ("native_goal_worker", _compact_native_goal_worker),
    ):
        nested = compactor(value.get(field))
        if nested:
            compact[field] = nested
    return compact


def compact_benchmark_runner_failure_fingerprint(
    value: Any,
    *,
    max_list_items: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact = _compact_fields(
        value,
        text_fields=(
            "schema_version",
            "error_len_bucket",
            "fingerprint_confidence",
            "apt_failure_subtype",
            "pip_failure_subtype",
            "retryability",
        ),
        int_fields=("line_count",),
        text_limit=100,
    )
    for field, limit in (
        ("matched_patterns", max_list_items * 4),
        ("failure_line_dependency_classes", max_list_items * 2),
        ("failure_reason_codes", max_list_items * 2),
        ("terminal_failure_dependency_classes", max_list_items * 2),
        ("terminal_failure_reason_codes", max_list_items * 2),
        ("failure_dependency_endpoints", max_list_items * 2),
        ("terminal_failure_dependency_endpoints", max_list_items * 2),
    ):
        items = public_safe_compact_list(value.get(field), limit=limit)
        if items:
            compact[field] = items
    compact.update(
        _compact_fields(
            value,
            bool_fields=(
                "error_present",
                "has_host_paths",
                "has_urls",
                "has_secret_like_tokens",
                "raw_error_recorded",
            ),
        )
    )
    return compact


def _compact_controller_cutoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _compact_fields(
        value,
        text_fields=("schema_version", "reason"),
        bool_fields=("cutoff_before_followup",),
        int_fields=(
            "max_rounds_budget",
            "initial_prompt_count",
            "followup_prompt_count",
            "stop_decision_count",
        ),
    )


def _compact_user_loop_recovery(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _compact_fields(
        value,
        text_fields=("schema_version", "stage", "exception_type"),
        bool_fields=("preserved_final_verify", "raw_error_recorded"),
        int_fields=("round", "delta_events", "delta_tool_calls"),
    )


def _compact_native_goal_worker(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact = _compact_fields(
        value,
        text_fields=(
            "schema_version",
            "trace_status",
            "failure_label",
            "failure_category",
            "first_blocker",
        ),
        int_fields=("trace_count",),
    )
    compact.update(
        _compact_fields(
            value,
            bool_fields=(
                "raw_transcript_recorded",
                "raw_assistant_message_recorded",
            ),
        )
    )
    return compact


def _compact_fields(
    value: dict[str, Any],
    *,
    text_fields: tuple[str, ...] = (),
    bool_fields: tuple[str, ...] = (),
    int_fields: tuple[str, ...] = (),
    text_limit: int = 140,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for field in text_fields:
        text = public_safe_compact_text(value.get(field), limit=text_limit)
        if text:
            compact[field] = text
    for field in bool_fields:
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in int_fields:
        number = value.get(field)
        if isinstance(number, int) and not isinstance(number, bool):
            compact[field] = number
    return compact

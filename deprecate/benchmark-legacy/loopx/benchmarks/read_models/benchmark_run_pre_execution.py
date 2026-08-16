from __future__ import annotations

from typing import Any

from ...benchmark_core.lifecycle import (
    compact_benchmark_canonical_lifecycle,
    compact_benchmark_live_worker_phase_from_run,
)
from ...control_plane.runtime.public_safety import (
    compact_loopx_command_records,
    compact_numeric_map,
    public_safe_compact_list,
    public_safe_compact_text,
)
from .benchmark_attempt_accounting import compact_benchmark_attempt_accounting

_RUNNER_PREREQUISITE_TEXT_FIELDS = (
    "schema_version",
    "codex_acp_runtime_launch_preflight_stage",
    "codex_acp_runtime_launch_preflight_status",
    "agent_execution_mode",
    "benchflow_run_stage",
    "benchflow_agent_runtime_layer_status",
    "benchflow_agent_runtime_layer_mount_target",
    "loopx_source_mount_status",
    "loopx_source_mount_target",
    "codex_app_server_goal_worker_plan_schema",
    "benchflow_user_loop_recovery_exception_type",
    "benchflow_user_loop_recovery_stage",
    "benchflow_intermediate_soft_verify_policy",
    "benchflow_intermediate_soft_verify_timeout_stage",
    "benchflow_intermediate_soft_verify_timeout_cleanup_status",
    "benchflow_intermediate_soft_verify_orphan_cleanup_status",
    "benchflow_setup_stall_cleanup_status",
    "codex_api_egress_preflight_status",
    "codex_api_egress_preflight_error_kind",
    "codex_api_egress_mode_requested",
    "codex_api_egress_mode_resolved",
    "codex_api_reverse_tunnel_proxy_source",
    "codex_api_reverse_tunnel_proxy_scheme",
    "codex_api_reverse_tunnel_proxy_endpoint_kind",
    "loopx_runner_source_fingerprint_status",
    "loopx_runner_source_first_blocker",
    "loopx_runner_source_git_head",
    "loopx_runner_source_expected_git_head",
    "loopx_runner_source_error_kind",
    "remote_command_file_bridge_consumption_status",
    "remote_command_file_bridge_agent_operation_trace_status",
    "remote_command_file_bridge_driver_lifecycle_execution_style",
    "runner_interruption_kind",
    "runner_interruption_status",
)

_RUNNER_PREREQUISITE_BOOL_FIELDS = (
    "codex_acp_runtime_container_bootstrap",
    "codex_acp_runtime_dependency_preflight",
    "codex_acp_runtime_dependency_setup_skipped",
    "codex_acp_runtime_launch_preflight",
    "codex_acp_runtime_launch_preflight_raw_logs_read",
    "container_codex_acp_install_skipped",
    "benchflow_agent_install_skipped_by_runtime_layer",
    "preinstalled_benchflow_agent_runtime_required",
    "benchflow_agent_runtime_layer_ready",
    "benchflow_agent_runtime_mount_injected",
    "benchflow_agent_runtime_mount_read_only",
    "benchflow_agent_runtime_mount_source_recorded",
    "host_local_acp_launch",
    "remote_command_file_bridge_materialized",
    "remote_command_file_bridge_command_configured",
    "remote_command_file_bridge_agent_command_configured",
    "remote_command_file_bridge_agent_command_instrumented",
    "remote_command_file_bridge_probe_command_configured",
    "remote_command_file_bridge_solver_wiring_configured",
    "remote_command_file_bridge_consumed_by_solver",
    "remote_command_file_bridge_solver_trace_dir_present",
    "remote_command_file_bridge_solver_public_trace_read",
    "remote_command_file_bridge_solver_raw_material_recorded",
    "remote_command_file_bridge_agent_operation_trace_required",
    "remote_command_file_bridge_agent_operation_trace_satisfied",
    "remote_command_file_bridge_agent_operation_trace_present",
    "remote_command_file_bridge_driver_lifecycle_trace_present",
    "remote_command_file_bridge_driver_lifecycle_raw_material_recorded",
    "codex_app_server_goal_worker_adapter_present",
    "codex_app_server_goal_worker_turn_start_required",
    "codex_app_server_goal_worker_goal_get_required",
    "codex_app_server_goal_worker_runner_integration_ready",
    "benchflow_user_loop_final_verify_recovery_enabled",
    "benchflow_user_loop_final_verify_recovery_triggered",
    "benchflow_user_loop_recovery_after_agent_activity",
    "benchflow_user_loop_recovery_raw_error_recorded",
    "benchflow_user_loop_recovery_preserved_final_verify",
    "benchflow_intermediate_soft_verify_final_only",
    "benchflow_intermediate_soft_verify_raw_output_recorded",
    "benchflow_intermediate_soft_verify_timeout_enabled",
    "benchflow_intermediate_soft_verify_timeout_triggered",
    "benchflow_intermediate_soft_verify_timeout_raw_output_recorded",
    "benchflow_intermediate_soft_verify_timeout_cleanup_requested",
    "benchflow_intermediate_soft_verify_timeout_cleanup_raw_logs_read",
    "benchflow_intermediate_soft_verify_orphan_cleanup_requested",
    "benchflow_intermediate_soft_verify_orphan_cleanup_raw_logs_read",
    "goal_start_product_mode",
    "goal_start_plan_required",
    "goal_start_guided_command_required",
    "goal_start_agent_authored_plan_required",
    "goal_start_host_preseed_forbidden",
    "goal_start_selected_p0_lifecycle_required",
    "verifier_failure_feedback_todo_route",
    "verifier_failure_feedback_forwarded_to_agent",
    "verifier_failure_todo_required",
    "benchflow_verifier_prep_timeout_override_enabled",
    "benchflow_verifier_prep_timeout_raw_command_recorded",
    "benchflow_final_verifier_timeout_enabled",
    "benchflow_final_verifier_timeout_triggered",
    "benchflow_final_verifier_timeout_raw_command_recorded",
    "benchflow_final_verifier_timeout_raw_output_recorded",
    "loopx_source_mount_requested",
    "loopx_source_mount_ready",
    "loopx_source_mount_injected",
    "loopx_source_mount_read_only",
    "loopx_source_mount_source_recorded",
    "benchflow_setup_stall_timeout_enabled",
    "benchflow_setup_stall_timeout_triggered",
    "benchflow_setup_stall_raw_logs_read",
    "benchflow_setup_stall_before_agent_lifecycle",
    "benchflow_agent_install_started",
    "codex_api_egress_preflight_required",
    "codex_api_egress_preflight_ready",
    "codex_api_reverse_tunnel_required",
    "codex_api_reverse_tunnel_proxy_configured",
    "codex_api_reverse_tunnel_proxy_url_recorded",
    "benchflow_setup_stall_task_cancel_requested",
    "benchflow_setup_stall_task_cancel_acknowledged",
    "benchflow_setup_stall_task_cancel_timeout",
    "benchflow_setup_stall_cleanup_requested",
    "benchflow_setup_stall_cleanup_raw_logs_read",
    "runner_interrupted_before_official_result",
    "runner_interruption_compact_closeout_expected",
    "runner_interruption_raw_material_recorded",
    "loopx_runner_source_git_head_recorded",
    "loopx_runner_source_expected_git_head_recorded",
    "loopx_runner_source_matches_expected",
    "loopx_runner_source_path_recorded",
    "loopx_runner_source_raw_git_output_recorded",
)

_RUNNER_PREREQUISITE_INT_FIELDS = (
    "codex_acp_runtime_launch_preflight_rc",
    "benchflow_user_loop_recovery_round",
    "benchflow_user_loop_recovery_delta_events",
    "benchflow_user_loop_recovery_delta_tool_calls",
    "benchflow_intermediate_soft_verify_call_count",
    "benchflow_intermediate_soft_verify_skipped_count",
    "benchflow_intermediate_soft_verify_timeout_sec",
    "benchflow_intermediate_soft_verify_timeout_override_count",
    "benchflow_intermediate_soft_verify_timeout_cleanup_container_count",
    "benchflow_intermediate_soft_verify_timeout_cleanup_match_count",
    "benchflow_intermediate_soft_verify_timeout_cleanup_term_sent_count",
    "benchflow_intermediate_soft_verify_timeout_cleanup_kill_sent_count",
    "benchflow_intermediate_soft_verify_timeout_cleanup_alive_after_count",
    "benchflow_intermediate_soft_verify_orphan_cleanup_container_count",
    "benchflow_intermediate_soft_verify_orphan_cleanup_match_count",
    "benchflow_intermediate_soft_verify_orphan_cleanup_term_sent_count",
    "benchflow_intermediate_soft_verify_orphan_cleanup_kill_sent_count",
    "benchflow_intermediate_soft_verify_orphan_cleanup_alive_after_count",
    "benchflow_verifier_prep_timeout_sec",
    "benchflow_final_verifier_timeout_sec",
    "benchflow_final_verifier_timeout_override_count",
    "benchflow_final_verifier_outer_timeout_override_count",
    "benchflow_verifier_prep_timeout_override_count",
    "benchflow_verify_prep_timeout_override_count",
    "benchflow_soft_verify_prep_timeout_override_count",
    "benchflow_setup_stall_timeout_requested_sec",
    "benchflow_setup_stall_timeout_sec",
    "codex_api_reverse_tunnel_proxy_endpoint_port",
    "benchflow_setup_stall_cleanup_match_count",
    "benchflow_setup_stall_cleanup_term_sent_count",
    "benchflow_setup_stall_cleanup_kill_sent_count",
    "benchflow_setup_stall_cleanup_alive_after_count",
    "goal_start_planned_todo_count_expected",
    "remote_command_file_bridge_solver_trace_count",
    "remote_command_file_bridge_solver_probe_ready_count",
    "remote_command_file_bridge_solver_operation_count",
    "remote_command_file_bridge_agent_operation_trace_count",
    "remote_command_file_bridge_agent_request_count",
    "remote_command_file_bridge_agent_success_count",
    "remote_command_file_bridge_agent_failure_count",
    "remote_command_file_bridge_agent_loopx_cli_call_count",
    "remote_command_file_bridge_agent_loopx_state_read_count",
    "remote_command_file_bridge_agent_loopx_state_write_count",
    "remote_command_file_bridge_agent_task_facing_operation_count",
    "remote_command_file_bridge_agent_todo_closeout_count",
    "remote_command_file_bridge_agent_refresh_state_count",
    "remote_command_file_bridge_agent_quota_spend_slot_count",
    "remote_command_file_bridge_driver_lifecycle_trace_count",
    "remote_command_file_bridge_driver_lifecycle_checkpoint_count",
    "remote_command_file_bridge_driver_lifecycle_request_count",
    "remote_command_file_bridge_driver_lifecycle_success_count",
    "remote_command_file_bridge_driver_lifecycle_failure_count",
    "remote_command_file_bridge_driver_lifecycle_loopx_cli_call_count",
    "remote_command_file_bridge_driver_lifecycle_loopx_state_read_count",
    "remote_command_file_bridge_driver_lifecycle_loopx_state_write_count",
)

_RUNNER_PREREQUISITE_MAP_FIELDS = (
    "remote_command_file_bridge_agent_operation_counts",
    "remote_command_file_bridge_agent_loopx_subcommand_counts",
    "remote_command_file_bridge_agent_successful_loopx_subcommand_counts",
    "remote_command_file_bridge_driver_lifecycle_command_counts",
    "remote_command_file_bridge_driver_lifecycle_returncode_counts",
)

_TASK_STAGING_BOOL_FIELDS = (
    "staged",
    "include_task_skills",
    "apt_setup_risk_detected",
    "apt_retry_patch_required",
    "dockerfile_pip_install_risk_detected",
    "dockerfile_pip_bootstrap_patch_required",
    "dockerfile_pip_bootstrap_patch_applied",
    "dockerfile_package_bootstrap_risk_preflight_blocked",
    "dockerfile_uv_bootstrap_risk_detected",
    "dockerfile_uv_bootstrap_mirror_patch_required",
    "dockerfile_uv_bootstrap_mirror_patch_applied",
    "dockerfile_uv_bootstrap_pip_fallback_patch_applied",
    "apt_retry_patch_applied",
    "apt_risk_preflight_blocked",
    "bootstrap_light_preflight_blocked",
    "bootstrap_light_fail_fast_defaulted",
    "verifier_bootstrap_risk_detected",
    "verifier_uv_bootstrap_risk_detected",
    "verifier_uv_bootstrap_mirror_patch_required",
    "verifier_uv_bootstrap_mirror_patch_applied",
    "dockerfile_apache_archive_mirror_patch_required",
    "dockerfile_apache_archive_mirror_patch_applied",
    "dockerfile_apache_archive_raw_url_recorded",
    "dockerfile_maven_mirror_patch_required",
    "dockerfile_maven_mirror_patch_applied",
    "dockerfile_maven_mirror_raw_url_recorded",
    "benchmark_egress_proxy_dockerfile_env_patch_required",
    "benchmark_egress_proxy_dockerfile_env_patch_applied",
    "benchmark_egress_proxy_dockerfile_java_opts_patch_applied",
    "benchmark_egress_proxy_dockerfile_env_raw_proxy_recorded",
    "verifier_bootstrap_risk_preflight_blocked",
    "verifier_bootstrap_fail_fast_defaulted",
    "app_skills_mount_patch_applied",
    "codex_acp_runtime_tools_patch_applied",
    "task_skills_removed",
    "original_task_mutated",
)

_TASK_SETUP_TEXT_FIELDS = (
    "schema_version",
    "status",
    "sandbox",
    "task_id",
    "first_blocker",
    "alternate_source_kind",
    "canonical_equivalent_status",
    "registry_source_kind",
    "registry_source_status",
    "registry_task_path",
    "selection_recommendation",
)

_TASK_SETUP_BOOL_FIELDS = (
    "raw_task_text_read",
    "raw_logs_read",
    "raw_trajectory_read",
    "apt_setup_risk_detected",
    "apt_retry_patch_required",
    "dockerfile_pip_install_risk_detected",
    "dockerfile_pip_bootstrap_patch_required",
    "verifier_present",
    "verifier_bootstrap_risk_detected",
    "verifier_uv_bootstrap_risk_detected",
    "verifier_external_download_risk_detected",
    "verifier_package_install_risk_detected",
    "dockerfile_present",
    "canonical_task_present",
    "alternate_source_supported_by_runner",
    "registry_task_present",
    "registry_task_path_recorded",
    "registry_excluded",
    "task_source_path_recorded",
    "task_source_content_recorded",
    "bootstrap_light_candidate_eligible",
)


def compact_benchmark_run_pre_execution_metadata(
    source: dict[str, Any],
    *,
    max_list_items: int,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    score = source.get("official_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        compact["official_score"] = score

    for field in (
        "failure_attribution_labels",
        "worker_startup_blockers",
        "worker_setup_diagnostic_blockers",
        "runner_warning_labels",
    ):
        items = public_safe_compact_list(source.get(field), limit=max_list_items)
        if items:
            compact[field] = items

    runner_prerequisites = _compact_runner_prerequisites(
        source.get("runner_prerequisites")
    )
    if runner_prerequisites:
        compact["runner_prerequisites"] = runner_prerequisites
    live_worker_phase = compact_benchmark_live_worker_phase_from_run(source)
    if live_worker_phase:
        compact["benchmark_live_worker_phase"] = live_worker_phase

    result_discovery = _compact_result_discovery(
        source.get("result_discovery"),
        max_list_items=max_list_items,
    )
    if result_discovery:
        compact["result_discovery"] = result_discovery
    task_setup = _compact_task_setup_preflight(
        source.get("task_setup_preflight"),
        max_list_items=max_list_items,
    )
    if task_setup:
        compact["task_setup_preflight"] = task_setup
    task_staging = _compact_task_staging(source.get("task_staging"))
    if task_staging:
        compact["task_staging"] = task_staging
    attempt_accounting = compact_benchmark_attempt_accounting(
        source.get("attempt_accounting")
    )
    if attempt_accounting:
        compact["attempt_accounting"] = attempt_accounting

    official_task_score = _compact_official_task_score(
        source.get("official_task_score")
    )
    if official_task_score:
        compact["official_task_score"] = official_task_score
    return compact


def _compact_runner_prerequisites(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(compact, value, _RUNNER_PREREQUISITE_TEXT_FIELDS)
    _copy_bool_fields(compact, value, _RUNNER_PREREQUISITE_BOOL_FIELDS)
    lifecycle = compact_benchmark_canonical_lifecycle(
        value.get("benchmark_canonical_lifecycle")
    )
    if lifecycle:
        compact["benchmark_canonical_lifecycle"] = lifecycle
    _copy_int_fields(compact, value, _RUNNER_PREREQUISITE_INT_FIELDS)
    for field in _RUNNER_PREREQUISITE_MAP_FIELDS:
        numeric_map = compact_numeric_map(value.get(field))
        if numeric_map:
            compact[field] = numeric_map
    for field in ("planned_todo_ids", "planned_todo_texts_public_safe"):
        items = public_safe_compact_list(value.get(field), limit=8)
        if items:
            compact[field] = items
    records = compact_loopx_command_records(
        value.get("remote_command_file_bridge_agent_successful_loopx_command_records")
    )
    if records:
        compact["remote_command_file_bridge_agent_successful_loopx_command_records"] = (
            records
        )
    return compact


def _compact_result_discovery(
    value: Any,
    *,
    max_list_items: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(
        compact,
        value,
        (
            "schema_version",
            "status",
            "selection_policy",
            "tie_breaker",
            "selected_relative_to_root",
            "selected_relative_to_job",
        ),
    )
    _copy_int_fields(
        compact,
        value,
        ("candidate_count", "matched_candidate_count", "top_score_candidate_count"),
    )
    _copy_bool_fields(
        compact,
        value,
        ("raw_logs_read", "raw_task_text_read", "raw_trajectory_read"),
    )
    reasons = public_safe_compact_list(
        value.get("selection_reasons"),
        limit=max_list_items,
    )
    if reasons:
        compact["selection_reasons"] = reasons
    return compact


def _compact_task_setup_preflight(
    value: Any,
    *,
    max_list_items: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(compact, value, _TASK_SETUP_TEXT_FIELDS)
    _copy_bool_fields(compact, value, _TASK_SETUP_BOOL_FIELDS)
    version = public_safe_compact_text(
        value.get("verifier_uv_bootstrap_version"),
        limit=180,
    )
    if version:
        compact["verifier_uv_bootstrap_version"] = version
    for field in (
        "nearest_canonical_task_ids",
        "verifier_bootstrap_risk_categories",
        "bootstrap_light_blocking_fields",
    ):
        items = public_safe_compact_list(value.get(field), limit=max_list_items)
        if items:
            compact[field] = items
    return compact


def _compact_task_staging(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(compact, value, ("schema_version",))
    _copy_bool_fields(compact, value, _TASK_STAGING_BOOL_FIELDS)
    _copy_text_fields(
        compact,
        value,
        (
            "dockerfile_pip_index_host",
            "bootstrap_light_blocker_kind",
            "dockerfile_uv_bootstrap_version",
            "dockerfile_uv_bootstrap_mirror_host",
            "verifier_uv_bootstrap_version",
            "verifier_uv_bootstrap_mirror_host",
            "dockerfile_apache_archive_mirror_host",
            "dockerfile_maven_mirror_host",
        ),
    )
    for field in (
        "bootstrap_light_blocking_field_count",
        "benchmark_egress_proxy_dockerfile_env_key_count",
    ):
        count = value.get(field)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            compact[field] = count

    resource_cap = value.get("resource_cap_patch")
    if isinstance(resource_cap, dict):
        compact_resource_cap: dict[str, Any] = {}
        _copy_text_fields(
            compact_resource_cap,
            resource_cap,
            ("schema_version", "reason"),
        )
        _copy_bool_fields(
            compact_resource_cap,
            resource_cap,
            ("applied", "original_task_mutated"),
        )
        for field in ("host_cpus", "requested_cpus", "effective_cpus"):
            number = resource_cap.get(field)
            if isinstance(number, (int, float)) and not isinstance(number, bool):
                compact_resource_cap[field] = number
        if compact_resource_cap:
            compact["resource_cap_patch"] = compact_resource_cap
    return compact


def _compact_official_task_score(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    kind = public_safe_compact_text(value.get("kind"), limit=80)
    if kind:
        compact["kind"] = kind
    for field in ("value", "passed"):
        if isinstance(value.get(field), (bool, int, float)):
            compact[field] = value[field]
    return compact


def _copy_text_fields(
    compact: dict[str, Any],
    value: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        text = public_safe_compact_text(value.get(field), limit=180)
        if text:
            compact[field] = text


def _copy_bool_fields(
    compact: dict[str, Any],
    value: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if isinstance(value.get(field), bool):
            compact[field] = value[field]


def _copy_int_fields(
    compact: dict[str, Any],
    value: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        number = value.get(field)
        if isinstance(number, int) and not isinstance(number, bool):
            compact[field] = number

"""Benchmark status runner compaction helpers."""

from __future__ import annotations

import re
from typing import Any

from .benchmark_status_compaction import (
    _apply_skillsbench_benchmark_egress_preflight_compact_projection,
    _apply_skillsbench_pre_agent_setup_compact_projection,
    _apply_skillsbench_runner_source_fingerprint_compact_projection,
    _compact_benchmark_compose_setup_diagnostic,
    _compact_benchmark_interaction_counters,
    _compact_benchmark_preflight_guard,
    _sync_skillsbench_runner_failure_root_blockers,
)
from ...benchmarks.read_models.skillsbench_verifier_attribution import (
    apply_skillsbench_verifier_bootstrap_missing_score_attribution,
)
from ...control_plane.work_items.delivery_batch_scale import (
    SMALL_DELIVERY_BATCH_SCALES as STRUCTURED_SMALL_DELIVERY_BATCH_SCALES,
    UNKNOWN_DELIVERY_BATCH_SCALE,
)
from ...history import STATUS_NEUTRAL_CLASSIFICATIONS as HISTORY_STATUS_NEUTRAL_CLASSIFICATIONS
from ...control_plane.work_items.project_asset import (
    TODO_PROJECTION_DETAIL_POINTER_SCHEMA_VERSION as TODO_PROJECTION_DETAIL_POINTER_SCHEMA_VERSION,
    TODO_PROJECTION_VIEW_SCHEMA_VERSION as TODO_PROJECTION_VIEW_SCHEMA_VERSION,
    project_asset_summary_is_public_safe as project_asset_summary_is_public_safe,
)
from ...control_plane.work_items.autonomous_candidates import (
    MAX_AUTONOMOUS_TODO_CANDIDATES as _MAX_AUTONOMOUS_TODO_CANDIDATES,
)
from ...control_plane.todos.active_state_todos import (
    MONITOR_WRITEBACK_CONTRACT_SCHEMA_VERSION as _MONITOR_WRITEBACK_CONTRACT_SCHEMA_VERSION,
)
from ...control_plane.work_items.autonomous_replan_ack import (
    AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW,
)
from ...control_plane.work_items.autonomous_replan_obligation import (
    AUTONOMOUS_REPLAN_STALL_THRESHOLD as _AUTONOMOUS_REPLAN_STALL_THRESHOLD_READ_MODEL,
    MAX_AUTONOMOUS_REPLAN_TRIGGERS as _MAX_AUTONOMOUS_REPLAN_TRIGGERS_READ_MODEL,
)
from ...control_plane.work_items.backlog_hygiene import (
    MAX_BACKLOG_HYGIENE_EVIDENCE_ITEMS as _MAX_BACKLOG_HYGIENE_EVIDENCE_ITEMS_READ_MODEL,
)
from ...control_plane.runtime.run_compaction import (
    RUN_BASE_COMPACT_FIELDS,
)
from ...control_plane.runtime.status_classifications import (
    DREAMING_ADVISORY_CLASSIFICATIONS,  # noqa: F401
    USER_OR_CONTROLLER_CLASSIFICATIONS,
)
from ...benchmarks.read_models.benchmark_projection import (
    benchmark_run_source as _benchmark_run_source_read_model,
    build_benchmark_solution_quality_signals,
    compact_benchmark_run_core as _compact_benchmark_run_core_read_model,
    compact_benchmark_run_trials as _compact_benchmark_run_trials_read_model,
    compact_benchmark_run_validation as _compact_benchmark_run_validation_read_model,
)
from ...benchmarks.read_models.benchmark_attempt_accounting import (
    compact_benchmark_attempt_accounting as _compact_benchmark_attempt_accounting,
)
from ...benchmarks.read_models.benchmark_run_execution_contract import (
    compact_benchmark_run_execution_contract as _compact_benchmark_run_execution_contract,
)
from ...benchmarks.read_models.benchmark_run_post_execution import (
    compact_benchmark_run_post_execution_metadata as _compact_benchmark_run_post_execution_metadata,
    repair_product_mode_lifecycle_missing_attribution as _repair_product_mode_lifecycle_missing_attribution_read_model,
)
from ...benchmarks.read_models.benchmark_run_pre_execution import (
    compact_benchmark_run_pre_execution_metadata as _compact_benchmark_run_pre_execution_metadata,
)
from ...control_plane.runtime.public_safety import (
    public_safe_compact_list,
    public_safe_compact_text,
)
from ...benchmarks.read_models.skillsbench_post_run_debug import (
    build_skillsbench_post_run_debug_gate,
)
from ...control_plane.todos.todo_summary import (
    MAX_DEFERRED_TODO_VISIBILITY_ITEMS as _TODO_SUMMARY_MAX_DEFERRED_TODO_VISIBILITY_ITEMS,
    MAX_DEPENDENCY_BLOCKERS as _TODO_SUMMARY_MAX_DEPENDENCY_BLOCKERS,
    MAX_MONITOR_DUE_ITEMS as _TODO_SUMMARY_MAX_MONITOR_DUE_ITEMS,
    MAX_PROJECT_ASSET_TODO_BACKLOG_ITEMS as _TODO_SUMMARY_MAX_PROJECT_ASSET_TODO_BACKLOG_ITEMS,
    MAX_PROJECT_ASSET_TODO_ITEMS as _TODO_SUMMARY_MAX_PROJECT_ASSET_TODO_ITEMS,
    MAX_STATUS_TODOS_PER_ROLE as _TODO_SUMMARY_MAX_STATUS_TODOS_PER_ROLE,
    MAX_TODO_VISIBILITY_LANE_ITEMS as _TODO_SUMMARY_MAX_TODO_VISIBILITY_LANE_ITEMS,
    claimed_visibility_items as claimed_visibility_items,
    compact_todo_group as compact_todo_group,
    compact_todo_item as compact_todo_item,
    todo_lane_items as todo_lane_items,
    todo_item_is_deferred as todo_item_is_deferred,
    todo_item_is_due_monitor as todo_item_is_due_monitor,
    todo_item_missing_monitor_schedule as todo_item_missing_monitor_schedule,
    todo_item_next_due_at as todo_item_next_due_at,
    todo_projection_sort_key as todo_projection_sort_key,
)
from ...control_plane.todos.contract import (
    normalize_todo_task_class as normalize_todo_task_class,
)
from ...control_plane.todos.projection import (
    todo_item_is_expired_monitor as todo_item_is_expired_monitor,
)


_PUBLIC_COMPAT_REEXPORTS = {
    "DREAMING_ADVISORY_CLASSIFICATIONS": "loopx.control_plane.runtime.status_classifications",
    "TODO_PROJECTION_DETAIL_POINTER_SCHEMA_VERSION": "loopx.control_plane.work_items.project_asset",
    "TODO_PROJECTION_VIEW_SCHEMA_VERSION": "loopx.control_plane.work_items.project_asset",
    "project_asset_summary_is_public_safe": "loopx.control_plane.work_items.project_asset",
    "claimed_visibility_items": "loopx.control_plane.todos.todo_summary",
    "compact_todo_group": "loopx.control_plane.todos.todo_summary",
    "compact_todo_item": "loopx.control_plane.todos.todo_summary",
    "todo_lane_items": "loopx.control_plane.todos.todo_summary",
    "todo_item_is_deferred": "loopx.control_plane.todos.todo_summary",
    "todo_item_is_due_monitor": "loopx.control_plane.todos.todo_summary",
    "todo_item_missing_monitor_schedule": "loopx.control_plane.todos.todo_summary",
    "todo_item_next_due_at": "loopx.control_plane.todos.todo_summary",
    "todo_projection_sort_key": "loopx.control_plane.todos.todo_summary",
    "normalize_todo_task_class": "loopx.control_plane.todos.contract",
    "todo_item_is_expired_monitor": "loopx.control_plane.todos.projection",
}


STATUS_NEUTRAL_CLASSIFICATIONS = HISTORY_STATUS_NEUTRAL_CLASSIFICATIONS
STATE_EVENT_LOG_BASENAME = "events.jsonl"
STATUS_CONTROL_PLANE_CONTEXT_LIMIT = 20
AGENT_LANE_PROGRESS_SCOPE = "agent_lane"
REGISTRY_WAITING_ON_OVERRIDES = {
    "user_or_controller",
    "controller",
    "codex",
    "external_evidence",
}
LEGACY_EXTERNAL_EVIDENCE_CLASSIFICATION_PREFIXES = (
    "await_",
    "external_evidence_observation_",
)
MONITOR_SIGNAL_WAITING_ON = "monitor_signal"
MONITOR_DISPLAY_SCHEMA_VERSION = "monitor_quiet_display_v0"
MONITOR_DISPLAY_STOP_CONDITION = (
    "stop until a material monitor transition, regression, or concrete blocker appears"
)
MONITOR_DISPLAY_FALLBACK_ACTION = (
    "No immediate agent work; keep the monitor quiet until a material monitor "
    "transition, regression, or concrete blocker appears."
)
BENCHMARK_RUN_SCHEMA_VERSION = "benchmark_run_v0"
MAX_BENCHMARK_RUN_TRIALS = 3
MAX_BENCHMARK_RUN_LIST_ITEMS = 5
STATUS_CONTRACT_SCHEMA_VERSION = 2
MINIMUM_DASHBOARD_STATUS_CONTRACT_SCHEMA_VERSION = 2
STATUS_CONTRACT_RELOAD_HINT = "scripts/macos-dashboard-launchagent.sh restart"
STATUS_CONTRACT_SIGNAL_LIMIT = 3
MONITOR_WRITEBACK_CONTRACT_SCHEMA_VERSION = _MONITOR_WRITEBACK_CONTRACT_SCHEMA_VERSION
EVENT_LEDGER_DECISION_CLASSIFICATIONS = USER_OR_CONTROLLER_CLASSIFICATIONS | {
    "operator_gate_approved",
}
EVENT_LEDGER_STATE_CLASSIFICATIONS = {
    "state_refreshed",
    "public_harness_healthy",
}
EVENT_LEDGER_EVIDENCE_CLASSIFICATIONS = {
    "inspect_eval_result",
    "inspect_result",
    "needs_more_read_only_evidence",
    "read_only_project_map",
}
EVENT_LEDGER_EVIDENCE_HINTS = (
    "artifact",
    "blocker",
    "ci",
    "data",
    "deploy",
    "done",
    "eval",
    "evidence",
    "failure",
    "fail",
    "metric",
    "monitor",
    "validation",
)


DELIVERY_BATCH_SCALE_TEST_ONLY_CLASSIFICATION_HINTS = (
    "_test",
    "_smoke",
    "readiness_test",
    "integrity_test",
)
DELIVERY_BATCH_SCALE_MULTI_SURFACE_CLASSIFICATION_HINTS = (
    "batch",
    "cross_benchmark",
    "downstream_pack",
    "matrix",
    "owner_handoff_consumer",
)
DELIVERY_BATCH_SCALE_IMPLEMENTATION_CLASSIFICATION_HINTS = (
    "adapter",
    "builder",
    "consumer",
    "implementation",
    "runner",
)
SMALL_DELIVERY_BATCH_SCALES = {
    *(scale.value for scale in STRUCTURED_SMALL_DELIVERY_BATCH_SCALES),
    UNKNOWN_DELIVERY_BATCH_SCALE,
}
CONNECTED_ADAPTER_STATUSES = {
    "connected",
    "connected-read-only",
    "pre-tick-runnable",
}
CONNECTED_DELIVERY_ADAPTER_STATUSES = {
    "connected-delivery",
}
SOURCE_REGISTRY_SHADOW_FINDINGS = {
    "source_registry_missing",
    "stale_source_registry",
}
PLANNED_CONTROLLER_OPT_IN_RECOMMENDED_ACTION = (
    "先在 LoopX 完成 operator 判断；同意后项目 Agent 只执行 read-only map dry-run"
)
RUN_COMPACT_FIELDS = RUN_BASE_COMPACT_FIELDS
LIFECYCLE_PRIORITY = (
    "controller_ready",
    "reward_judged",
    "operator_approved",
    "controller_gated",
    "operator_gated",
    "adapter_inspected",
    "mapped",
    "refreshed",
    "connected",
    "registered",
    "planned",
    "run_recorded",
)
SECTION_HEADING_PATTERN = re.compile(r"^##+\s+(.+?)\s*$")
MAX_STATUS_TODOS_PER_ROLE = _TODO_SUMMARY_MAX_STATUS_TODOS_PER_ROLE
MAX_ACTIVE_DONE_TODOS_BEFORE_ARCHIVE = MAX_STATUS_TODOS_PER_ROLE
MAX_PROJECT_ASSET_TODO_ITEMS = _TODO_SUMMARY_MAX_PROJECT_ASSET_TODO_ITEMS
MAX_PROJECT_ASSET_TODO_BACKLOG_ITEMS = _TODO_SUMMARY_MAX_PROJECT_ASSET_TODO_BACKLOG_ITEMS
MAX_TODO_VISIBILITY_LANE_ITEMS = _TODO_SUMMARY_MAX_TODO_VISIBILITY_LANE_ITEMS
MAX_DEFERRED_TODO_VISIBILITY_ITEMS = _TODO_SUMMARY_MAX_DEFERRED_TODO_VISIBILITY_ITEMS
MAX_MONITOR_DUE_ITEMS = _TODO_SUMMARY_MAX_MONITOR_DUE_ITEMS
MAX_DEPENDENCY_BLOCKERS = _TODO_SUMMARY_MAX_DEPENDENCY_BLOCKERS
MAX_AUTONOMOUS_BACKLOG_CANDIDATES = _MAX_AUTONOMOUS_TODO_CANDIDATES
MAX_BACKLOG_HYGIENE_EVIDENCE_ITEMS = _MAX_BACKLOG_HYGIENE_EVIDENCE_ITEMS_READ_MODEL
MAX_AUTONOMOUS_REPLAN_TRIGGERS = _MAX_AUTONOMOUS_REPLAN_TRIGGERS_READ_MODEL
AUTONOMOUS_REPLAN_STALL_THRESHOLD = _AUTONOMOUS_REPLAN_STALL_THRESHOLD_READ_MODEL
DEAD_MONITOR_REPEAT_THRESHOLD = 6
AUTONOMOUS_REPLAN_PERIODIC_RUN_THRESHOLD = AUTONOMOUS_REPLAN_ACK_MATERIAL_RUN_WINDOW
AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK = 30
BACKLOG_HYGIENE_SECTION_HEADINGS = ("Next Action", "Operating Lessons")
BACKLOG_HYGIENE_BULLET_PATTERN = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$")
BACKLOG_HYGIENE_HINT_PATTERN = re.compile(
    r"(?i)(?:\[p[0-4]\]|todo|backlog|follow[- ]?up|queue|audit|regression|smoke|cadence|mirror|monitor|sub-?agent|待办|回归|审计|修复|检查|推进)"
)
AUTONOMOUS_REPLAN_SCHEMA_VERSION = "autonomous_replan_obligation_v0"
DEAD_MONITOR_REPEAT_SCHEMA_VERSION = "dead_monitor_repeat_v0"
AUTONOMOUS_RUN_HISTORY_NEUTRAL_CLASSIFICATIONS = {
    "quota_slot_spent",
    "quota_slot_voided",
    "delivery_completion_spend_accounted_v0",
}


def _compact_benchmark_private_runner_launch(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in (
        "schema_version",
        "launch_schema_version",
        "first_blocker",
        "argv_binary_name",
        "codex_goal_mode_invocation_surface",
        "codex_goal_mode_required_invocation_surface",
        "codex_goal_mode_baseline_claim_blocker",
        "codex_app_server_goal_worker_plan_schema",
        "task_material_readiness_status",
        "task_material_first_blocker",
    ):
        text = public_safe_compact_text(value.get(field), limit=120)
        if text:
            compact[field] = text
    for field in (
        "uses_private_runner_env",
        "ready",
        "argv_present",
        "argv_binary_resolved_for_private_launch",
        "no_upload_boundary",
        "submit_eligible",
        "env_path_present",
        "active_user_writable_mount_requested",
        "active_user_writable_mount_target_present",
        "agent_import_path_present",
        "loopx_agent_kwargs_present",
        "codex_goal_mode_baseline_requested",
        "codex_app_server_goal_baseline_requested",
        "codex_app_server_goal_worker_adapter_present",
        "codex_app_server_goal_worker_turn_start_required",
        "codex_app_server_goal_proof_present",
        "codex_goal_mode_baseline_claim_allowed",
        "loopx_access_packet_absent",
        "loopx_worker_bridge_requested",
        "worker_materialization_probe_only",
        "task_material_readiness_checked",
        "task_material_ready_required",
        "task_material_ready",
        "setup_timeout_repair_profile",
        "auth_values_recorded",
        "raw_env_recorded",
        "raw_paths_recorded",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in (
        "env_probe_path_coverage_count",
        "task_material_candidate_count",
        "task_material_instruction_md_present_count",
        "task_material_task_toml_present_count",
    ):
        count = value.get(field)
        if isinstance(count, int) and not isinstance(count, bool):
            compact[field] = count
    active_user_mount_count = value.get("active_user_writable_mount_count")
    if isinstance(active_user_mount_count, int) and not isinstance(active_user_mount_count, bool):
        compact["active_user_writable_mount_count"] = active_user_mount_count
    coverage = value.get("env_probe_path_coverage")
    compact_coverage: dict[str, bool] = {}
    if isinstance(coverage, dict):
        compact_coverage = {
            str(key): ready
            for key, ready in coverage.items()
            if isinstance(key, str) and isinstance(ready, bool)
        }
    if compact_coverage:
        compact["env_probe_path_coverage"] = compact_coverage
    policy = value.get("timeout_multiplier_policy")
    if isinstance(policy, dict):
        compact_policy: dict[str, Any] = {}
        schema = public_safe_compact_text(policy.get("schema_version"), limit=120)
        if schema:
            compact_policy["schema_version"] = schema
        for field in (
            "any_timeout_multiplier_present",
            "non_default_timeout_multiplier_present",
            "agent_setup_timeout_multiplier_present",
            "changes_official_benchmark_timeout",
            "leaderboard_claim_allowed",
            "raw_argv_recorded",
        ):
            if isinstance(policy.get(field), bool):
                compact_policy[field] = policy[field]
        multipliers = policy.get("multipliers")
        if isinstance(multipliers, dict):
            compact_multipliers = {
                str(key): value
                for key, value in multipliers.items()
                if isinstance(key, str)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            }
            if compact_multipliers:
                compact_policy["multipliers"] = compact_multipliers
        if compact_policy:
            compact["timeout_multiplier_policy"] = compact_policy
    repair_profile = _compact_benchmark_repair_profile(value.get("repair_profile"))
    if repair_profile:
        compact["repair_profile"] = repair_profile
    readiness = _compact_agent_setup_readiness(value.get("agent_setup_readiness"))
    if readiness:
        compact["agent_setup_readiness"] = readiness
    names = public_safe_compact_list(
        value.get("auth_surface_names_present"),
        limit=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    if names:
        compact["auth_surface_names_present"] = names
    materialization = _compact_benchmark_post_launch_materialization(
        value.get("post_launch_materialization")
    )
    if materialization:
        compact["post_launch_materialization"] = materialization
    closeout = value.get("closeout_command_templates")
    if isinstance(closeout, dict):
        compact_closeout: dict[str, Any] = {}
        for field in (
            "schema_version",
            "display_command",
            "post_run_rule",
        ):
            text = public_safe_compact_text(closeout.get(field), limit=320)
            if text:
                compact_closeout[field] = text
        for field in (
            "history_append",
            "run_ledger_update",
            "atomic_ledger_upsert",
            "raw_paths_recorded",
            "raw_logs_read",
            "raw_task_text_read",
        ):
            if isinstance(closeout.get(field), bool):
                compact_closeout[field] = closeout[field]
        argv_template = public_safe_compact_list(
            closeout.get("argv_template"),
            limit=MAX_BENCHMARK_RUN_LIST_ITEMS * 4,
        )
        if argv_template:
            compact_closeout["argv_template"] = argv_template
        if compact_closeout:
            compact["closeout_command_templates"] = compact_closeout
    return compact


def _compact_benchmark_repair_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in ("schema_version", "repair_class"):
        text = public_safe_compact_text(value.get(field), limit=140)
        if text:
            compact[field] = text
    for field in (
        "enabled",
        "rerun_allowed_after_profile_applied",
        "raw_logs_required",
        "raw_task_text_required",
        "credential_values_recorded",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]

    for source_field in (
        "required_launch_overrides",
        "disallowed_launch_overrides",
    ):
        source = value.get(source_field)
        if not isinstance(source, dict):
            continue
        compact_source: dict[str, Any] = {}
        for key, raw_value in source.items():
            safe_key = public_safe_compact_text(key, limit=100)
            if not safe_key:
                continue
            if isinstance(raw_value, str):
                text_value = public_safe_compact_text(raw_value, limit=140)
                if text_value:
                    compact_source[safe_key] = text_value
            elif isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
                compact_source[safe_key] = raw_value
            elif isinstance(raw_value, bool):
                compact_source[safe_key] = raw_value
        if compact_source:
            compact[source_field] = compact_source
    return compact


def _compact_agent_setup_readiness(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in (
        "schema_version",
        "codex_install_strategy",
        "first_blocker",
        "next_action_after_setup_timeout",
    ):
        text = public_safe_compact_text(value.get(field), limit=180)
        if text:
            compact[field] = text
    for field in (
        "managed_codex_agent",
        "worker_bridge_requested",
        "worker_materialization_probe_only",
        "runtime_codex_install_allowed",
        "fail_fast_install_strategy",
        "setup_timeout_budget_explicit",
        "setup_timeout_repair_profile",
        "same_task_repeat_after_setup_timeout_allowed",
        "setup_failure_before_worker_counts_as_case_progress",
        "raw_argv_recorded",
        "raw_env_recorded",
        "raw_logs_read",
        "task_text_read",
        "trajectory_read",
        "credential_values_recorded",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    multiplier = value.get("agent_setup_timeout_multiplier")
    if isinstance(multiplier, (int, float)) and not isinstance(multiplier, bool):
        compact["agent_setup_timeout_multiplier"] = multiplier
    return compact


def _compact_benchmark_post_launch_materialization(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in (
        "schema_version",
        "first_blocker",
        "job_name",
        "external_handle_kind",
        "external_handle_state",
        "compact_monitor_class",
        "compact_failure_class",
    ):
        text = public_safe_compact_text(value.get(field), limit=140)
        if text:
            compact[field] = text
    for field in (
        "checked",
        "ready_for_launch_state",
        "ready_for_compact_result_ingest",
        "jobs_dir_present",
        "job_root_present",
        "job_lock_present",
        "job_result_present",
        "ready_for_compact_failure_marker",
        "external_handle_observed",
        "external_handle_terminal",
        "job_result_finished",
        "job_active_without_trial_result",
        "job_stale_active_without_trial_result",
        "job_result_updated_at_present",
        "stale_active_reconcile_requested",
        "raw_paths_recorded",
        "raw_logs_read",
        "raw_task_text_read",
        "trajectory_read",
        "raw_external_handle_payload_recorded",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in (
        "trial_result_present_count",
        "candidate_job_root_count",
        "job_running_trial_count",
        "job_pending_trial_count",
        "job_active_stale_seconds_threshold",
    ):
        count = value.get(field)
        if isinstance(count, int) and not isinstance(count, bool):
            compact[field] = count
    age = value.get("job_updated_age_seconds")
    if isinstance(age, (int, float)) and not isinstance(age, bool):
        compact["job_updated_age_seconds"] = round(float(age), 3)
    marker = value.get("compact_failure_marker")
    if isinstance(marker, dict):
        compact_marker: dict[str, Any] = {}
        for field in (
            "schema_version",
            "failure_class",
            "evidence_kind",
            "external_handle_kind",
            "external_handle_state",
            "terminal_state",
            "lifecycle_stage",
            "ledger_attempt_kind",
            "next_allowed_action",
        ):
            text = public_safe_compact_text(marker.get(field), limit=140)
            if text:
                compact_marker[field] = text
        for field in (
            "external_handle_terminal",
            "terminal_closeout",
            "runner_attempt_countable",
            "launch_state_countable",
            "case_attempt_countable",
            "benchmark_budget_countable",
            "job_result_present",
            "job_result_finished",
            "job_result_updated_at_present",
            "raw_paths_recorded",
            "raw_logs_read",
            "raw_task_text_read",
            "trajectory_read",
            "raw_external_handle_payload_recorded",
        ):
            if isinstance(marker.get(field), bool):
                compact_marker[field] = marker[field]
        trial_result_count = marker.get("trial_result_present_count")
        if isinstance(trial_result_count, int) and not isinstance(
            trial_result_count, bool
        ):
            compact_marker["trial_result_present_count"] = trial_result_count
        for field in (
            "job_running_trial_count",
            "job_pending_trial_count",
            "job_active_stale_seconds_threshold",
        ):
            count = marker.get(field)
            if isinstance(count, int) and not isinstance(count, bool):
                compact_marker[field] = count
        age = marker.get("job_updated_age_seconds")
        if isinstance(age, (int, float)) and not isinstance(age, bool):
            compact_marker["job_updated_age_seconds"] = round(float(age), 3)
        attempt_accounting = _compact_benchmark_attempt_accounting(
            marker.get("attempt_accounting")
        )
        if attempt_accounting:
            compact_marker["attempt_accounting"] = attempt_accounting
        if compact_marker:
            compact["compact_failure_marker"] = compact_marker
    return compact


def compact_benchmark_post_launch_materialization(value: Any) -> dict[str, Any] | None:
    compact = _compact_benchmark_post_launch_materialization(value)
    return compact or None


def compact_benchmark_run(run: dict[str, Any]) -> dict[str, Any] | None:
    source = _benchmark_run_source_read_model(
        run,
        schema_version=BENCHMARK_RUN_SCHEMA_VERSION,
    )
    if not source:
        return None

    trials_source = (
        source.get("trials") if isinstance(source.get("trials"), list) else []
    )
    compact = _compact_benchmark_run_core_read_model(
        source,
        schema_version=BENCHMARK_RUN_SCHEMA_VERSION,
        max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    execution_contract = _compact_benchmark_run_execution_contract(
        source,
        max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    loop_contract = execution_contract.get("benchmark_loop_contract")
    if loop_contract:
        compact["benchmark_loop_contract"] = loop_contract
    compact.update(
        _compact_benchmark_run_pre_execution_metadata(
            source,
            max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
        )
    )

    compact.update(
        {
            field: execution_contract[field]
            for field in ("claim_boundary", "agent", "model_control")
            if field in execution_contract
        }
    )

    post_execution = _compact_benchmark_run_post_execution_metadata(
        source,
        max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    compact.update(post_execution.failure)

    compose_setup_diagnostic = _compact_benchmark_compose_setup_diagnostic(
        source.get("compose_setup_diagnostic")
    )
    if compose_setup_diagnostic:
        compact["compose_setup_diagnostic"] = compose_setup_diagnostic
        _apply_skillsbench_pre_agent_setup_compact_projection(compact)

    compact.update(post_execution.progress_metrics)

    interaction_counters = _compact_benchmark_interaction_counters(
        source.get("interaction_counters")
    )
    if interaction_counters:
        compact["interaction_counters"] = interaction_counters

    compact.update(post_execution.lifecycle)
    _repair_product_mode_lifecycle_missing_attribution_read_model(
        compact,
        max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )

    preflight_guard = _compact_benchmark_preflight_guard(source.get("preflight_guard"))
    if preflight_guard:
        compact["preflight_guard"] = preflight_guard

    compact.update(post_execution.active_user_and_claim)

    private_runner_launch = _compact_benchmark_private_runner_launch(
        source.get("private_runner_launch_summary")
    )
    if private_runner_launch:
        compact["private_runner_launch_summary"] = private_runner_launch

    setup_timeout_repair_profile = _compact_benchmark_repair_profile(
        source.get("setup_timeout_repair_profile")
    )
    if setup_timeout_repair_profile:
        compact["setup_timeout_repair_profile"] = setup_timeout_repair_profile

    compact.update(post_execution.worker_outcome)

    compact_validation = _compact_benchmark_run_validation_read_model(
        source.get("validation"),
        pre_agent_setup_materialization_blocked=(
            compact.get("pre_agent_setup_materialization_blocked") is True
        ),
        max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    if compact_validation:
        compact["validation"] = compact_validation
        _apply_skillsbench_pre_agent_setup_compact_projection(compact)

    _apply_skillsbench_runner_source_fingerprint_compact_projection(
        compact,
        source=source,
    )
    _apply_skillsbench_benchmark_egress_preflight_compact_projection(
        compact,
        source=source,
    )
    apply_skillsbench_verifier_bootstrap_missing_score_attribution(
        compact,
        task_staging=compact.get("task_staging"),
        setup_preflight=compact.get("task_setup_preflight"),
    )

    _sync_skillsbench_runner_failure_root_blockers(compact)

    if solution_quality := build_benchmark_solution_quality_signals(compact):
        compact["solution_quality_signals"] = solution_quality

    post_run_debug_gate = build_skillsbench_post_run_debug_gate(compact)
    if post_run_debug_gate:
        compact["post_run_debug_gate"] = post_run_debug_gate

    trials = _compact_benchmark_run_trials_read_model(
        trials_source,
        max_trials=MAX_BENCHMARK_RUN_TRIALS,
        max_list_items=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    if trials:
        compact["trials"] = trials
        raw_trials = source.get("trials")
        if isinstance(raw_trials, list):
            compact["trial_count"] = len(raw_trials)

    for field in ("evidence_files", "resume_or_inspect_commands", "stop_conditions"):
        values = public_safe_compact_list(source.get(field), limit=MAX_BENCHMARK_RUN_LIST_ITEMS)
        if values:
            compact[field] = values

    read_boundary = source.get("read_boundary")
    if isinstance(read_boundary, dict):
        compact_boundary: dict[str, bool] = {}
        for field in (
            "compact_only",
            "raw_artifacts_read",
            "task_text_read",
            "trajectory_read",
            "controller_trace_read",
            "local_paths_recorded",
            "docker_invoked",
            "model_api_invoked",
            "upload_invoked",
        ):
            if isinstance(read_boundary.get(field), bool):
                compact_boundary[field] = read_boundary[field]
        if compact_boundary:
            compact["read_boundary"] = compact_boundary

    if set(compact.keys()) == {"schema_version"}:
        return None
    return compact

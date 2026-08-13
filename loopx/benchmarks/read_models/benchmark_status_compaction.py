"""Benchmark status compaction helpers."""

from __future__ import annotations

import re
from typing import Any

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
from ...control_plane.runtime.public_safety import (
    compact_loopx_command_records as _compact_loopx_command_records,
    compact_numeric_map as _compact_numeric_map,
    public_safe_compact_list,
    public_safe_compact_text,
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



def _compact_benchmark_interaction_counters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    schema = public_safe_compact_text(value.get("schema_version"), limit=100)
    if schema:
        compact["schema_version"] = schema
    for field in (
        "prompt_policy_injected",
        "harness_skill_or_packet_injected",
        "raw_trace_recorded",
        "raw_task_prompt_recorded",
        "controller_trace_present",
        "loopx_automation_loop",
        "inner_codex_goal_mode",
        "curated_skills_visible",
        "product_mode",
        "goal_start_product_mode",
        "verifier_failure_feedback_todo_route",
        "verifier_failure_feedback_forwarded_to_agent",
        "verifier_failure_todo_required",
        "goal_start_plan_observed",
        "planner_before_todo_write",
        "same_priority_order_preserved",
        "selected_todo_claimed",
        "selected_todo_updated_before_solver",
        "selected_todo_completed_before_spend",
        "selected_todo_completed_observed",
        "non_selected_todos_preserved_open_or_deferred",
        "quota_spend_missing_after_repeated_complete",
        "blind_loop",
        "case_goal_state_packet_present",
        "case_goal_state_init_required",
        "case_goal_state_initialized_before_agent",
        "declared_done_requires_no_remaining_goals",
        "product_mode_lifecycle_checkpoint_required",
        "product_mode_solver_activity_required",
        "product_mode_solver_activity_gap",
        "product_mode_declared_done_below_passing_reward",
        "product_mode_no_open_todo_below_passing_reward_stop",
        "product_mode_typed_repair_required",
        "product_mode_typed_repair_pending",
        "product_mode_typed_repair_todo_identity_observed",
        "product_mode_typed_repair_task_or_validation_delta",
        "product_mode_typed_repair_delta_observed",
        "product_mode_typed_repair_terminal",
        "product_mode_typed_repair_terminal_receipt_consistent",
        "product_mode_host_local_idle_no_task_output_progress",
        "product_mode_host_local_idle_no_task_output_progress_stop",
        "product_mode_final_closeout_superseded_by_official_success",
        "product_mode_no_tool_call_lifecycle_abort",
        "agent_declared_done",
        "agent_declared_no_remaining_goals",
        "official_feedback_blinded",
        "reward_feedback_forwarded",
        "controller_official_feedback_forwarded",
        "controller_blind_loop",
        "controller_official_success_observed",
        "controller_budget_cutoff_before_followup",
        "benchflow_user_loop_final_verify_recovery_enabled",
        "benchflow_user_loop_final_verify_recovery_triggered",
        "benchflow_user_loop_recovery_after_agent_activity",
        "benchflow_user_loop_recovery_preserved_final_verify",
        "benchflow_user_loop_recovery_raw_error_recorded",
        "benchflow_intermediate_soft_verify_final_only",
        "benchflow_intermediate_soft_verify_raw_output_recorded",
        "benchflow_intermediate_soft_verify_timeout_enabled",
        "benchflow_intermediate_soft_verify_timeout_triggered",
        "benchflow_intermediate_soft_verify_timeout_raw_output_recorded",
        "benchflow_intermediate_soft_verify_timeout_cleanup_requested",
        "benchflow_intermediate_soft_verify_timeout_cleanup_raw_logs_read",
        "benchflow_intermediate_soft_verify_orphan_cleanup_requested",
        "benchflow_intermediate_soft_verify_orphan_cleanup_raw_logs_read",
        "private_trajectory_summary_present",
        "native_goal_worker_route",
        "native_goal_worker_connected",
        "native_goal_worker_trace_dir_present",
        "native_goal_worker_public_trace_read",
        "native_goal_worker_raw_material_recorded",
        "remote_command_file_bridge_consumed_by_solver",
        "remote_command_file_bridge_solver_trace_dir_present",
        "remote_command_file_bridge_solver_public_trace_read",
        "remote_command_file_bridge_solver_raw_material_recorded",
        "remote_command_file_bridge_agent_operation_trace_required",
        "remote_command_file_bridge_agent_operation_trace_satisfied",
        "remote_command_file_bridge_driver_lifecycle_trace_present",
        "remote_command_file_bridge_driver_lifecycle_raw_material_recorded",
        "host_local_acp_codex_exec_failure_trace_present",
        "host_local_acp_codex_exec_failure_raw_material_recorded",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in (
        "loopx_state_reads",
        "loopx_state_writes",
        "loopx_case_state_reads",
        "loopx_case_state_writes",
        "heartbeat_count",
        "controller_action_decisions",
        "controller_initial_prompt_count",
        "controller_followup_prompt_count",
        "controller_stop_decision_count",
        "controller_reward_observation_count",
        "controller_round_reward_count",
        "controller_official_success_observation_count",
        "controller_first_success_round",
        "declared_done_round",
        "planned_todo_count",
        "planned_p0_count",
        "agent_todo_complete_unique_todo_count",
        "selected_todo_complete_count",
        "selected_todo_duplicate_complete_count",
        "non_selected_todo_complete_count",
        "todo_complete_without_todo_id_count",
        "product_mode_lifecycle_checkpoint_count",
        "product_mode_lifecycle_checkpoint_round",
        "product_mode_solver_activity_gap_count",
        "product_mode_solver_activity_gap_round",
        "product_mode_declared_done_below_passing_reward_count",
        "product_mode_declared_done_below_passing_reward_round",
        "verifier_failure_feedback_todo_prompt_count",
        "verifier_failure_feedback_todo_round",
        "open_todo_count",
        "product_mode_no_open_todo_below_passing_reward_streak",
        "product_mode_no_open_todo_below_passing_reward_streak_threshold",
        "product_mode_no_open_todo_below_passing_reward_round",
        "product_mode_no_open_todo_below_passing_reward_stop_count",
        "product_mode_no_open_todo_below_passing_reward_stop_round",
        "product_mode_no_open_todo_below_passing_reward_open_todo_count_public",
        "product_mode_typed_repair_trigger_round",
        "product_mode_typed_repair_round_entered",
        "product_mode_typed_repair_round_entered_count",
        "product_mode_typed_repair_resolved_round",
        "product_mode_typed_repair_task_facing_success_delta",
        "product_mode_typed_repair_terminal_round",
        "product_mode_typed_repair_open_todo_count_public",
        "product_mode_host_local_idle_no_task_output_progress_streak",
        "product_mode_host_local_idle_no_task_output_progress_streak_threshold",
        "product_mode_host_local_idle_no_task_output_progress_round",
        "product_mode_host_local_idle_no_task_output_progress_stop_count",
        "product_mode_host_local_idle_no_task_output_progress_stop_round",
        "product_mode_host_local_idle_no_task_output_progress_last_failure_trace_count",
        "product_mode_host_local_idle_no_task_output_progress_acp_tool_calls",
        "product_mode_host_local_idle_no_task_output_progress_bridge_task_ops",
        "product_mode_host_local_idle_no_task_output_progress_bridge_task_successes",
        "product_mode_final_closeout_superseded_round",
        "product_mode_no_tool_call_lifecycle_abort_count",
        "product_mode_no_tool_call_lifecycle_abort_round",
        "controller_verifier_feedback_observation_count",
        "controller_official_feedback_blinded_count",
        "controller_official_feedback_forwarded_count",
        "controller_max_rounds_budget",
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
        "private_trajectory_event_count",
        "private_trajectory_round_count",
        "private_trajectory_tool_call_count",
        "loopx_cli_call_count",
        "loopx_cli_state_read_count",
        "loopx_cli_state_write_count",
        "loopx_case_state_path_count",
        "loopx_case_state_read_count",
        "loopx_case_state_write_count",
        "protected_path_mention_count",
        "protected_path_edit_signal_count",
        "codex_acp_text_bytes",
        "append_benchmark_run_success_count",
        "append_benchmark_run_schema_rejected_count",
        "worker_counter_trace_trial_count",
        "worker_benchmark_run_file_count",
        "worker_benchmark_run_schema_ok_count",
        "worker_self_validation_official_score_mismatch_count",
        "worker_validation_scope_ambiguous_official_score_failure_count",
        "worker_bridge_connected_official_score_failure_count",
        "worker_startup_blocker_count",
        "worker_setup_diagnostic_file_count",
        "worker_setup_diagnostic_schema_ok_count",
        "worker_submit_eligible_mismatch_count",
        "worker_bridge_writeback_loss_count",
        "environment_setup_failure_before_worker_count",
        "pre_worker_agent_setup_failure_count",
        "codex_runtime_goal_tool_trial_count",
        "native_goal_worker_connect_count",
        "native_goal_worker_trace_count",
        "native_goal_worker_lifecycle_trace_count",
        "native_goal_worker_prompt_received_count",
        "native_goal_worker_ok_count",
        "native_goal_worker_goal_get_count",
        "native_goal_worker_turn_start_count",
        "native_goal_worker_turn_completed_observed_count",
        "native_goal_worker_assistant_message_present_count",
        "native_goal_worker_assistant_context_only_count",
        "native_goal_worker_context_only_recovery_attempted_count",
        "native_goal_worker_context_only_recovery_succeeded_count",
        "native_goal_worker_context_only_followup_start_attempted_count",
        "native_goal_worker_context_only_followup_start_succeeded_count",
        "native_goal_worker_normal_followup_attempted_count",
        "native_goal_worker_normal_followup_succeeded_count",
        "native_goal_worker_normal_followup_start_attempted_count",
        "native_goal_worker_normal_followup_start_succeeded_count",
        "native_goal_worker_finish_guard_followup_attempted_count",
        "native_goal_worker_finish_guard_followup_succeeded_count",
        "native_goal_worker_finish_guard_followup_start_attempted_count",
        "native_goal_worker_finish_guard_followup_start_succeeded_count",
        "native_goal_worker_incomplete_turn_status_count",
        "native_goal_worker_incomplete_after_completion_event_count",
        "native_goal_worker_transport_reconnect_attempted_count",
        "native_goal_worker_transport_reconnect_succeeded_count",
        "native_goal_worker_goal_reactivation_attempted_count",
        "native_goal_worker_goal_reactivation_succeeded_count",
        "native_goal_worker_post_context_assistant_chars_total",
        "native_goal_worker_first_action_observed_count",
        "native_goal_worker_effective_action_observed_count",
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
        "remote_command_file_bridge_agent_todo_closeout_count",
        "remote_command_file_bridge_agent_refresh_state_count",
        "remote_command_file_bridge_agent_quota_spend_slot_count",
        "remote_command_file_bridge_agent_task_facing_operation_count",
        "remote_command_file_bridge_agent_task_facing_success_count",
        "remote_command_file_bridge_agent_task_facing_failure_count",
        "remote_command_file_bridge_driver_lifecycle_trace_count",
        "remote_command_file_bridge_driver_lifecycle_checkpoint_count",
        "remote_command_file_bridge_driver_lifecycle_request_count",
        "remote_command_file_bridge_driver_lifecycle_success_count",
        "remote_command_file_bridge_driver_lifecycle_failure_count",
        "remote_command_file_bridge_driver_lifecycle_loopx_cli_call_count",
        "remote_command_file_bridge_driver_lifecycle_loopx_state_read_count",
        "remote_command_file_bridge_driver_lifecycle_loopx_state_write_count",
        "host_local_acp_codex_exec_failure_trace_count",
        "host_local_acp_codex_exec_recoverable_failure_trace_count",
        "host_local_acp_codex_exec_fatal_failure_trace_count",
    ):
        if isinstance(value.get(field), int) and not isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in (
        "product_mode_declared_done_below_passing_reward_score",
        "product_mode_no_open_todo_below_passing_reward_score",
        "product_mode_host_local_idle_no_task_output_progress_score",
    ):
        raw = value.get(field)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            compact[field] = float(raw)
    for field in (
        "case_result_writeback",
        "counter_trust_level",
        "controller_trace_schema_version",
        "controller_trace_publicness",
        "case_goal_state_init_status",
        "case_goal_state_init_failed_phase",
        "case_goal_state_schema_version",
        "product_mode_lifecycle_checkpoint_missing_reason",
        "product_mode_solver_activity_missing_reason",
        "product_mode_declared_done_below_passing_reward_score_status",
        "product_mode_no_open_todo_below_passing_reward_score_status",
        "product_mode_host_local_idle_no_task_output_progress_score_status",
        "product_mode_host_local_idle_no_task_output_progress_category",
        "product_mode_host_local_idle_no_task_output_progress_policy",
        "product_mode_declared_done_policy",
        "product_mode_typed_repair_policy_id",
        "product_mode_typed_repair_terminal_reason",
        "product_mode_final_closeout_superseded_reason",
        "controller_budget_cutoff_reason",
        "benchflow_user_loop_recovery_stage",
        "benchflow_user_loop_recovery_exception_type",
        "benchflow_intermediate_soft_verify_policy",
        "benchflow_intermediate_soft_verify_timeout_stage",
        "benchflow_intermediate_soft_verify_timeout_cleanup_status",
        "benchflow_intermediate_soft_verify_orphan_cleanup_status",
        "remote_command_file_bridge_agent_operation_trace_status",
        "remote_command_file_bridge_consumption_decision",
        "remote_command_file_bridge_driver_lifecycle_execution_style",
        "native_goal_worker_reasoning_effort",
        "host_local_acp_codex_exec_failure_category",
        "host_local_acp_bridge_progress_status",
        "host_local_acp_bridge_progress_signal_source",
        "last_decision",
        "worker_submit_eligible_mismatch_reason",
        "worker_bridge_writeback_loss_reason",
    ):
        text = public_safe_compact_text(value.get(field), limit=100)
        if text:
            compact[field] = text
    case_state_path = public_safe_compact_text(
        value.get("case_goal_state_path"),
        limit=180,
    )
    if (
        case_state_path
        and "/.codex/goals/" in case_state_path
        and case_state_path.endswith("/ACTIVE_GOAL_STATE.md")
        and not re.search(r"^/(Users|private|var/folders)/", case_state_path)
    ):
        compact["case_goal_state_path"] = case_state_path

    for field in (
        "codex_runtime_goal_tool_calls",
        "trajectory_action_category_counts",
        "loopx_cli_state_usage_counts",
        "remote_command_file_bridge_agent_returncode_counts",
        "remote_command_file_bridge_agent_loopx_subcommand_counts",
        "remote_command_file_bridge_agent_successful_loopx_subcommand_counts",
        "remote_command_file_bridge_driver_lifecycle_command_counts",
        "remote_command_file_bridge_driver_lifecycle_returncode_counts",
    ):
        calls = _compact_numeric_map(value.get(field))
        if calls:
            compact[field] = calls
    selected_p0_todo_id = public_safe_compact_text(
        value.get("selected_p0_todo_id"),
        limit=100,
    )
    if selected_p0_todo_id:
        compact["selected_p0_todo_id"] = selected_p0_todo_id
    planned_todo_ids = public_safe_compact_list(
        value.get("planned_todo_ids"),
        limit=8,
    )
    if planned_todo_ids:
        compact["planned_todo_ids"] = planned_todo_ids
    planned_todo_texts = public_safe_compact_list(
        value.get("planned_todo_texts_public_safe"),
        limit=8,
    )
    if planned_todo_texts:
        compact["planned_todo_texts_public_safe"] = planned_todo_texts
    command_records = _compact_loopx_command_records(
        value.get("remote_command_file_bridge_agent_successful_loopx_command_records")
    )
    if command_records:
        compact[
            "remote_command_file_bridge_agent_successful_loopx_command_records"
        ] = command_records
    raw_loopx_cli_calls = value.get("loopx_cli_calls")
    if isinstance(raw_loopx_cli_calls, dict):
        calls = _compact_numeric_map(raw_loopx_cli_calls)
        if calls:
            compact["loopx_cli_calls"] = calls
    elif isinstance(raw_loopx_cli_calls, list):
        calls: list[dict[str, Any]] = []
        for item in raw_loopx_cli_calls[:8]:
            if not isinstance(item, dict):
                continue
            call: dict[str, Any] = {}
            round_value = item.get("round")
            if (
                isinstance(round_value, int)
                and not isinstance(round_value, bool)
                and round_value > 0
            ):
                call["round"] = round_value
            command = public_safe_compact_text(item.get("command"), limit=120)
            if command:
                call["command"] = command
            flags = item.get("flags")
            if isinstance(flags, list):
                compact_flags = [
                    flag
                    for flag in (
                        public_safe_compact_text(flag, limit=60)
                        for flag in flags[:8]
                    )
                    if flag
                ]
                if compact_flags:
                    call["flags"] = compact_flags
            if isinstance(item.get("raw_title_copied"), bool):
                call["raw_title_copied"] = item["raw_title_copied"]
            if isinstance(item.get("raw_output_copied"), bool):
                call["raw_output_copied"] = item["raw_output_copied"]
            if call:
                calls.append(call)
        if calls:
            compact["loopx_cli_calls"] = calls

    return compact


def _compact_benchmark_preflight_guard(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in (
        "schema_version",
        "first_blocker",
        "loopx_mode_kwarg",
        "codex_goal_mode_invocation_surface",
        "codex_goal_mode_required_invocation_surface",
        "codex_goal_mode_baseline_claim_blocker",
        "codex_app_server_goal_worker_plan_schema",
        "runner_binary_resolution_policy",
        "simulator_setting",
    ):
        text = public_safe_compact_text(value.get(field), limit=120)
        if text:
            compact[field] = text
    for field in (
        "runner_surface_checked",
        "local_execution_surface_checked",
        "codex_cli_surface_checked",
        "auth_surface_names_only",
        "auth_values_read",
        "artifact_redaction_required",
        "task_material_ready_required",
        "access_packet_prompt_injection_checked",
        "trace_counter_extraction_contract_checked",
        "loopx_mode_kwarg_checked",
        "codex_goal_mode_invocation_surface_checked",
        "codex_app_server_goal_baseline_requested",
        "codex_app_server_goal_worker_adapter_present",
        "codex_app_server_goal_worker_adapter_absent",
        "codex_app_server_goal_worker_turn_start_required",
        "codex_app_server_goal_proof_present",
        "codex_goal_mode_baseline_claim_allowed",
        "loopx_access_packet_absent",
        "loopx_cli_bridge_absent",
        "active_cli_bridge_enabled",
        "claim_requires_worker_cli_calls",
        "real_interface_use_observed",
        "uplift_claim_allowed",
        "active_user_assisted_treatment",
        "simulator_to_worker_injection_channel_available",
        "interactive_user_message_injection_checked",
        "initial_prompt_only_is_not_active_intervention",
        "no_oracle_audit_required",
        "assisted_score_kept_separate_from_official",
        "uvx_cli_present",
        "uvx_version_probe_ok",
        "docker_cli_present",
        "docker_version_probe_ok",
        "docker_server_available",
        "colima_cli_present",
        "colima_status_probe_ok",
        "codex_cli_present",
        "codex_version_probe_ok",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    text = public_safe_compact_text(value.get("worker_cli_bridge_surface"), limit=120)
    if text:
        compact["worker_cli_bridge_surface"] = text
    for field in ("required_worker_loopx_cli_call_total_min",):
        if isinstance(value.get(field), int) and not isinstance(value.get(field), bool):
            compact[field] = value[field]
    return compact


def _compact_benchmark_compose_setup_diagnostic(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    for field in (
        "schema_version",
        "status",
        "route",
        "failure_class",
        "runner_prerequisite_status",
        "task_setup_preflight_status",
        "fingerprint_confidence",
        "runner_error_len_bucket",
        "primary_setup_failure_category",
        "apt_failure_subtype",
        "pip_failure_subtype",
        "retryability",
        "next_diagnostic_action",
    ):
        text = public_safe_compact_text(value.get(field), limit=180)
        if text:
            compact[field] = text
    for field in (
        "compose_setup_failure",
        "unclassified_compose_failure",
        "docker_daemon_unavailable",
        "apt_repository_failure",
        "pip_bootstrap_failure",
        "volume_mount_failure",
        "environment_setup_failure",
        "agent_rounds_started",
        "official_score_missing",
        "official_result_json_materialized",
        "case_attempt_budget_should_count",
        "runner_launch_preflight_passed",
        "apt_setup_risk_detected",
        "apt_retry_patch_required",
        "verifier_uv_bootstrap_risk_detected",
        "verifier_uv_bootstrap_mirror_patch_required",
        "verifier_uv_bootstrap_mirror_patch_applied",
        "staged_task_prepared",
        "task_skills_removed",
        "codex_acp_runtime_tools_patch_applied",
        "resource_cap_applied",
        "raw_error_recorded",
        "raw_logs_read",
        "raw_task_text_read",
        "raw_trajectory_read",
    ):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    for field in (
        "heartbeat_count",
        "controller_action_decision_count",
        "trajectory_round_count",
        "trajectory_tool_call_count",
        "loopx_cli_call_count",
        "round_reward_count",
        "setup_stall_timeout_requested_sec",
        "setup_stall_timeout_sec",
        "progress_completed_trials",
        "progress_errored_trials",
    ):
        if isinstance(value.get(field), int) and not isinstance(value.get(field), bool):
            compact[field] = value[field]
    patterns = public_safe_compact_list(
        value.get("fingerprint_matched_patterns"),
        limit=MAX_BENCHMARK_RUN_LIST_ITEMS,
    )
    if patterns:
        compact["fingerprint_matched_patterns"] = patterns
    for field in (
        "terminal_failure_dependency_classes",
        "terminal_failure_reason_codes",
        "terminal_failure_dependency_endpoints",
    ):
        values = public_safe_compact_list(
            value.get(field),
            limit=MAX_BENCHMARK_RUN_LIST_ITEMS * 2,
        )
        if values:
            compact[field] = values
    return compact


_SKILLSBENCH_PRE_AGENT_SETUP_STATUS_LABELS = {
    "compose_setup_blocked_before_agent_rounds": (
        "skillsbench_compose_setup_blocked_before_agent_rounds"
    ),
    "runner_setup_blocked_before_agent_rounds": (
        "skillsbench_runner_setup_blocked_before_agent_rounds"
    ),
}


def _skillsbench_compact_official_score_missing(compact: dict[str, Any]) -> bool:
    official = (
        compact.get("official_task_score")
        if isinstance(compact.get("official_task_score"), dict)
        else {}
    )
    value = official.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return False
    value = compact.get("official_score")
    return not (isinstance(value, (int, float)) and not isinstance(value, bool))


def _sync_skillsbench_runner_failure_root_blockers(
    compact: dict[str, Any],
) -> None:
    runner_failure = compact.get("runner_failure")
    if not isinstance(runner_failure, dict):
        return
    if not _skillsbench_compact_official_score_missing(compact):
        return

    blocker = public_safe_compact_text(
        compact.get("score_failure_attribution"),
        limit=140,
    )
    if blocker in {None, "none", "score_missing"}:
        blocker = public_safe_compact_text(
            runner_failure.get("failure_class"),
            limit=140,
        )
    if not blocker:
        return

    replaceable = {
        None,
        "none",
        "score_missing",
        "skillsbench_runner_error",
    }
    for field in ("first_blocker", "repeat_blocked_by"):
        if compact.get(field) in replaceable:
            compact[field] = blocker


def _skillsbench_compact_pre_agent_setup_label(compact: dict[str, Any]) -> str:
    diagnostic = compact.get("compose_setup_diagnostic")
    if not isinstance(diagnostic, dict):
        return ""
    label = _SKILLSBENCH_PRE_AGENT_SETUP_STATUS_LABELS.get(
        str(diagnostic.get("status") or "")
    )
    if not label:
        return ""
    if compact.get("mode") != "skillsbench_codex_app_server_goal_baseline":
        return ""
    validation = (
        compact.get("validation") if isinstance(compact.get("validation"), dict) else {}
    )
    native_route = (
        compact.get("native_goal_worker_route")
        if "native_goal_worker_route" in compact
        else validation.get("native_goal_worker_route")
    )
    if native_route is not True:
        return ""
    native_connected = (
        compact.get("native_goal_worker_connected")
        if "native_goal_worker_connected" in compact
        else validation.get("native_goal_worker_connected")
    )
    if native_connected is True:
        return ""
    trace_count = (
        compact.get("native_goal_worker_trace_count")
        if "native_goal_worker_trace_count" in compact
        else validation.get("native_goal_worker_trace_count")
    )
    if (
        isinstance(trace_count, int)
        and not isinstance(trace_count, bool)
        and trace_count > 0
    ):
        return ""
    if diagnostic.get("agent_rounds_started") is True:
        return ""
    if not _skillsbench_compact_official_score_missing(compact):
        return ""
    return label


def _apply_skillsbench_pre_agent_setup_compact_projection(
    compact: dict[str, Any],
) -> None:
    label = _skillsbench_compact_pre_agent_setup_label(compact)
    if not label:
        return
    current = str(compact.get("score_failure_attribution") or "")
    if (
        current in {"", "none", "score_missing", "skillsbench_runner_error"}
        or current.startswith("skillsbench_native_goal_worker_")
    ):
        compact["score_failure_attribution"] = label
        compact["first_blocker"] = label
    labels = [
        item
        for item in compact.get("failure_attribution_labels", [])
        if isinstance(item, str) and item
    ]
    for item in (
        label,
        "skillsbench_app_server_goal_pre_agent_materialization_blocked",
        "skillsbench_runner_setup_error",
    ):
        if item not in labels:
            labels.append(item)
    compact["failure_attribution_labels"] = labels[:MAX_BENCHMARK_RUN_LIST_ITEMS]
    attempt_accounting = compact.get("attempt_accounting")
    if isinstance(attempt_accounting, dict):
        attempt_accounting["failure_label"] = label
        attempt_accounting["failure_class"] = "job_materialization_failed"
    runner_failure = compact.get("runner_failure")
    if isinstance(runner_failure, dict):
        runner_failure["exception_type"] = label
        runner_failure["failure_class"] = label
        runner_failure["pre_agent_setup_materialization_blocked"] = True
    validation = compact.get("validation")
    if isinstance(validation, dict):
        failed = [
            item
            for item in validation.get("failed_checks", [])
            if isinstance(item, str) and item
        ]
        failed = [
            item for item in failed if item != "native_goal_worker_public_trace_missing"
        ]
        if "pre_agent_setup_materialization_blocked" not in failed:
            failed.append("pre_agent_setup_materialization_blocked")
        validation["failed_checks"] = failed[:MAX_BENCHMARK_RUN_LIST_ITEMS]
        validation["all_passed"] = False
    compact["pre_agent_setup_materialization_blocked"] = True
    compact["native_goal_worker_pre_agent_setup_blocked"] = True


def _mark_skillsbench_pre_task_attempt_accounting(
    compact: dict[str, Any],
    *,
    failure_label: str,
) -> None:
    attempt_accounting = compact.get("attempt_accounting")
    if not isinstance(attempt_accounting, dict):
        return
    attempt_accounting["lifecycle_phase"] = "runner_accepted_args"
    attempt_accounting["failure_label"] = failure_label
    attempt_accounting["failure_class"] = "job_materialization_failed"
    attempt_accounting["launcher_attempt_countable"] = True
    for field in (
        "case_attempt_countable",
        "solver_attempt_countable",
        "verifier_attempt_countable",
        "official_score_attempt_countable",
    ):
        attempt_accounting[field] = False
    attempts = attempt_accounting.get("attempts")
    if not isinstance(attempts, dict):
        return
    launcher = attempts.get("launcher")
    if isinstance(launcher, dict):
        launcher["attempted"] = True
        launcher["countable"] = True
    for phase_name in ("case", "solver", "verifier", "official_score"):
        phase = attempts.get(phase_name)
        if isinstance(phase, dict):
            phase["attempted"] = False
            phase["countable"] = False


def _apply_skillsbench_benchmark_egress_preflight_compact_projection(
    compact: dict[str, Any],
    *,
    source: dict[str, Any] | None = None,
) -> None:
    source = source if isinstance(source, dict) else {}
    source_runner_config = (
        source.get("runner_config")
        if isinstance(source.get("runner_config"), dict)
        else {}
    )
    proxy_required = (
        compact.get("benchmark_egress_proxy_required") is True
        or source_runner_config.get("benchmark_egress_proxy_required") is True
    )
    proxy_ready = (
        compact.get("benchmark_egress_proxy_ready") is True
        or source_runner_config.get("benchmark_egress_proxy_ready") is True
    )
    proxy_status = public_safe_compact_text(
        compact.get("benchmark_egress_proxy_status")
        or source_runner_config.get("benchmark_egress_proxy_status"),
        limit=120,
    )
    benchmark_failure_statuses = {
        "failed",
        "invalid_proxy_value",
        "missing_required_proxy",
        "proxy_auth_required",
        "proxy_connect_rejected",
        "unsupported_proxy_scheme",
    }
    benchmark_blocked = bool(
        proxy_required
        and not proxy_ready
        and proxy_status in benchmark_failure_statuses
    )
    codex_required = (
        compact.get("codex_api_egress_preflight_required") is True
        or source_runner_config.get("codex_api_egress_preflight_required") is True
    )
    codex_ready = (
        compact.get("codex_api_egress_preflight_ready") is True
        or source_runner_config.get("codex_api_egress_preflight_ready") is True
    )
    codex_status = public_safe_compact_text(
        compact.get("codex_api_egress_preflight_status")
        or source_runner_config.get("codex_api_egress_preflight_status"),
        limit=120,
    )
    codex_failure_statuses = {
        "failed",
        "missing_reverse_tunnel_proxy",
        "proxy_auth_required",
        "proxy_connect_rejected",
        "unsupported_egress_mode",
        "unsupported_proxy_scheme",
    }
    codex_blocked = bool(
        codex_required and not codex_ready and codex_status in codex_failure_statuses
    )
    if not benchmark_blocked and not codex_blocked:
        return
    if not _skillsbench_compact_official_score_missing(compact):
        return

    if benchmark_blocked:
        label = "skillsbench_benchmark_egress_proxy_preflight_blocked"
        status_label = f"skillsbench_benchmark_egress_proxy_{proxy_status}"
        blocker_key = "benchmark_egress_proxy_preflight_blocked"
    else:
        label = "skillsbench_codex_api_egress_preflight_blocked"
        status_label = f"skillsbench_codex_api_egress_{codex_status}"
        blocker_key = "codex_api_egress_preflight_blocked"
    compact["score_failure_attribution"] = label
    compact["first_blocker"] = label
    compact["repeat_blocked_by"] = label
    compact["official_score_comparable_to_native_codex"] = False
    compact["official_score_comparable_to_loopx_treatment"] = False

    labels = [
        item
        for item in compact.get("failure_attribution_labels", [])
        if isinstance(item, str)
        and item
        and item
        not in {
            "skillsbench_product_mode_uncountable_treatment",
            "skillsbench_remote_bridge_agent_operation_trace_missing",
            "skillsbench_verifier_package_install_risk",
            "skillsbench_verifier_uv_install_or_download_failure",
            "verifier_dependency_install_failure",
        }
    ]
    primary_labels = (
        label,
        "skillsbench_environment_setup_error",
        status_label,
    )
    labels = list(primary_labels) + [
        item for item in labels if item not in primary_labels
    ]
    compact["failure_attribution_labels"] = labels[:MAX_BENCHMARK_RUN_LIST_ITEMS]

    _mark_skillsbench_pre_task_attempt_accounting(
        compact,
        failure_label=label,
    )
    runner_failure = compact.get("runner_failure")
    if isinstance(runner_failure, dict):
        runner_failure["failure_class"] = label
        runner_failure[blocker_key] = True

    validation = (
        compact.get("validation")
        if isinstance(compact.get("validation"), dict)
        else {}
    )
    validation[blocker_key] = True
    validation["raw_verifier_output_read"] = False
    validation["all_passed"] = False
    compact["validation"] = validation

    if benchmark_blocked:
        compact["benchmark_egress_proxy_diagnostic"] = {
            "schema_version": "skillsbench_benchmark_egress_proxy_diagnostic_v0",
            "status": "benchmark_egress_proxy_preflight_blocked",
            "score_failure_attribution": label,
            "proxy_required": True,
            "proxy_ready": False,
            "proxy_status": proxy_status,
            "proxy_error_kind": public_safe_compact_text(
                compact.get("benchmark_egress_proxy_error_kind")
                or source_runner_config.get("benchmark_egress_proxy_error_kind"),
                limit=120,
            ),
            "proxy_mode_requested": public_safe_compact_text(
                compact.get("benchmark_egress_proxy_mode_requested")
                or source_runner_config.get("benchmark_egress_proxy_mode_requested"),
                limit=80,
            ),
            "proxy_mode_effective": public_safe_compact_text(
                compact.get("benchmark_egress_proxy_mode_effective")
                or source_runner_config.get("benchmark_egress_proxy_mode_effective"),
                limit=80,
            ),
            "proxy_url_recorded": False,
            "raw_logs_read": False,
            "raw_task_text_read": False,
            "raw_trajectory_read": False,
            "next_diagnostic_action": (
                "configure_valid_private_benchmark_egress_proxy"
            ),
        }
        return

    compact["codex_api_egress_diagnostic"] = {
        "schema_version": "skillsbench_codex_api_egress_diagnostic_v0",
        "status": "codex_api_egress_preflight_blocked",
        "score_failure_attribution": label,
        "egress_required": True,
        "egress_ready": False,
        "egress_status": codex_status,
        "egress_error_kind": public_safe_compact_text(
            compact.get("codex_api_egress_preflight_error_kind")
            or source_runner_config.get("codex_api_egress_preflight_error_kind"),
            limit=120,
        ),
        "egress_mode_requested": public_safe_compact_text(
            compact.get("codex_api_egress_mode_requested")
            or source_runner_config.get("codex_api_egress_mode_requested"),
            limit=80,
        ),
        "egress_mode_effective": public_safe_compact_text(
            compact.get("codex_api_egress_mode_resolved")
            or source_runner_config.get("codex_api_egress_mode_resolved"),
            limit=80,
        ),
        "reverse_tunnel_required": (
            compact.get("codex_api_reverse_tunnel_required") is True
            or source_runner_config.get("codex_api_reverse_tunnel_required") is True
        ),
        "proxy_url_recorded": False,
        "raw_logs_read": False,
        "raw_task_text_read": False,
        "raw_trajectory_read": False,
        "next_diagnostic_action": "restore_required_private_egress_then_retry",
    }


def _apply_skillsbench_runner_source_fingerprint_compact_projection(
    compact: dict[str, Any],
    *,
    source: dict[str, Any] | None = None,
) -> None:
    source = source if isinstance(source, dict) else {}
    prerequisites = (
        compact.get("runner_prerequisites")
        if isinstance(compact.get("runner_prerequisites"), dict)
        else {}
    )
    source_config = (
        source.get("runner_config")
        if isinstance(source.get("runner_config"), dict)
        else {}
    )
    status = public_safe_compact_text(
        prerequisites.get("loopx_runner_source_fingerprint_status")
        or source_config.get("loopx_runner_source_fingerprint_status"),
        limit=80,
    )
    blocker = public_safe_compact_text(
        prerequisites.get("loopx_runner_source_first_blocker")
        or source_config.get("loopx_runner_source_first_blocker"),
        limit=120,
    )
    if (
        status != "mismatched_expected"
        or blocker != "loopx_runner_source_git_head_mismatch"
        or not _skillsbench_compact_official_score_missing(compact)
    ):
        return

    compact["score_failure_attribution"] = blocker
    compact["first_blocker"] = blocker
    compact["repeat_blocked_by"] = blocker
    compact["official_score_comparable_to_native_codex"] = False
    compact["official_score_comparable_to_loopx_treatment"] = False

    verifier_labels = {
        "verifier_dependency_bootstrap_timeout",
        "verifier_dependency_install_failure",
        "verifier_uv_install_or_download_failure",
        "skillsbench_verifier_bootstrap_missing_official_score",
        "skillsbench_verifier_bootstrap_preflight_blocked",
        "skillsbench_verifier_package_install_risk",
    }
    labels = [
        item
        for item in compact.get("failure_attribution_labels", [])
        if isinstance(item, str) and item and item not in verifier_labels
    ]
    primary_labels = (
        blocker,
        "skillsbench_runner_source_fingerprint_mismatch",
        "skillsbench_runner_setup_error",
    )
    labels = list(primary_labels) + [
        item for item in labels if item not in primary_labels
    ]
    compact["failure_attribution_labels"] = labels[:MAX_BENCHMARK_RUN_LIST_ITEMS]

    _mark_skillsbench_pre_task_attempt_accounting(
        compact,
        failure_label=blocker,
    )
    runner_failure = compact.get("runner_failure")
    if isinstance(runner_failure, dict):
        runner_failure["failure_class"] = blocker
        runner_failure["runner_source_fingerprint_mismatch"] = True

    validation = (
        compact.get("validation")
        if isinstance(compact.get("validation"), dict)
        else {}
    )
    validation["runner_source_fingerprint_mismatch"] = True
    validation["all_passed"] = False
    compact["validation"] = validation

    compose_setup_diagnostic = compact.get("compose_setup_diagnostic")
    if isinstance(compose_setup_diagnostic, dict):
        compose_setup_diagnostic["case_attempt_budget_should_count"] = False

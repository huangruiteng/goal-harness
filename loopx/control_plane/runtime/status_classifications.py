from __future__ import annotations

"""Pure status classification sets owned by the runtime read model.

`loopx.status` re-exports these names for compatibility. No module in this
file may import from ``loopx.status`` or other presentation surfaces.
"""


CODEX_READY_CLASSIFICATIONS = {
    "controller_opted_in_waiting_for_run",
    "design_next_experiment",
    "inspect_eval_result",
    "inspect_result",
    "needs_more_read_only_evidence",
    "needs_validation",
    "public_harness_healthy",
    "read_only_project_map",
    "run_validation",
    "state_refreshed",
    "operator_gate_approved",
    "monitor_todo_repeat_dedupe_deployed",
}

HANDOFF_READY_CLASSIFICATIONS = {
    "operator_gate_approved",
    "controller_opted_in_waiting_for_run",
}

DREAMING_ADVISORY_CLASSIFICATIONS = {
    "dreaming_exploration_proposal",
    "dreaming_memory_consolidation",
    "dreaming_refactor_warning",
    "dreaming_archive_suggestion",
}

USER_OR_CONTROLLER_CLASSIFICATIONS = {
    "needs_human_reward",
    "needs_controller_opt_in",
    "needs_user_relay",
    "ready_for_controller_opt_in",
    "ready_for_user_relay",
    "operator_gate_deferred",
    "operator_gate_rejected",
} | DREAMING_ADVISORY_CLASSIFICATIONS

BLOCKING_CLASSIFICATIONS = {
    "blocked_by_safety",
}

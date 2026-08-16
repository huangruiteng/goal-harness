from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...control_plane.runtime.public_safety import (
    compact_numeric_map,
    public_safe_compact_list,
    public_safe_compact_text,
)
from ...control_plane.runtime.run_ingest_health import (
    compact_environment_setup_failure_context,
    compact_worker_bridge_outcome,
)
from .benchmark_event_timeline import compact_benchmark_case_event_timeline
from .benchmark_lifecycle_contracts import (
    compact_app_server_goal_round_semantics,
    compact_native_goal_worker_contract,
    compact_product_mode_lifecycle_contract,
)
from .benchmark_run_failure import (
    compact_benchmark_runner_failure,
    compact_benchmark_runner_failure_fingerprint,
)
from .benchmark_run_metrics import (
    compact_benchmark_overhead_attribution_counters,
    compact_benchmark_round_reward_trace,
)
from .goal_start_control_score import compact_goal_start_product_mode_control_score


@dataclass(frozen=True)
class BenchmarkRunPostExecutionMetadata:
    """Ordered pure metadata groups separated by status-owned mutation barriers."""

    failure: dict[str, Any]
    progress_metrics: dict[str, Any]
    lifecycle: dict[str, Any]
    active_user_and_claim: dict[str, Any]
    worker_outcome: dict[str, Any]


def compact_benchmark_run_post_execution_metadata(
    source: dict[str, Any],
    *,
    max_list_items: int,
) -> BenchmarkRunPostExecutionMetadata:
    return BenchmarkRunPostExecutionMetadata(
        failure=_compact_failure(source, max_list_items=max_list_items),
        progress_metrics=_compact_progress_metrics(source),
        lifecycle=_compact_lifecycle(source),
        active_user_and_claim=_compact_active_user_and_claim(source),
        worker_outcome=_compact_worker_outcome(source),
    )


def repair_product_mode_lifecycle_missing_attribution(
    compact: dict[str, Any],
    *,
    max_list_items: int,
) -> None:
    contract = compact.get("product_mode_lifecycle_contract")
    if not isinstance(contract, dict):
        return
    if not (
        contract.get("required") is True
        and contract.get("satisfied") is True
        and contract.get("countable_treatment") is True
    ):
        return
    if compact.get("score_failure_attribution") != (
        "skillsbench_product_mode_lifecycle_missing"
    ):
        return

    labels = public_safe_compact_list(
        compact.get("failure_attribution_labels"),
        limit=max_list_items,
    )
    stale_labels = {
        "skillsbench_product_mode_lifecycle_missing",
        "skillsbench_product_mode_uncountable_treatment",
        "skillsbench_case_local_loopx_state_not_observed",
        "skillsbench_remote_bridge_agent_no_requests",
        "skillsbench_remote_bridge_agent_operation_trace_missing",
    }
    labels = [label for label in labels if label not in stale_labels]

    official_score = compact.get("official_score")
    counters = compact.get("interaction_counters")
    if not isinstance(counters, dict):
        counters = {}

    def positive_counter(field: str) -> int:
        value = counters.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return 0

    def zero_counter_observed(field: str) -> bool:
        if field not in counters:
            return False
        value = counters.get(field)
        return isinstance(value, int) and not isinstance(value, bool) and value == 0

    solver_activity_gap = bool(
        counters.get("product_mode_solver_activity_gap") is True
        and (
            counters.get("product_mode_solver_activity_missing_reason")
            == "missing_task_facing_activity_or_agent_closeout_before_declared_done"
            or positive_counter("product_mode_solver_activity_gap_count") > 0
            or zero_counter_observed(
                "remote_command_file_bridge_agent_task_facing_operation_count"
            )
            or zero_counter_observed(
                "remote_command_file_bridge_agent_todo_closeout_count"
            )
        )
    )

    if solver_activity_gap:
        replacement = "skillsbench_product_mode_solver_activity_gap"
        labels = [
            label
            for label in labels
            if label
            not in {
                "official_verifier_solution_failure",
                "official_score_zero_case_failure",
            }
        ]
    elif (
        isinstance(official_score, (int, float))
        and not isinstance(
            official_score,
            bool,
        )
        and official_score == 0
    ):
        replacement = "official_verifier_solution_failure"
    else:
        replacement = "none"

    compact["score_failure_attribution"] = replacement
    if replacement != "none" and replacement not in labels:
        labels.insert(0, replacement)
    if labels:
        compact["failure_attribution_labels"] = labels[:max_list_items]
    else:
        compact.pop("failure_attribution_labels", None)


def _compact_failure(
    source: dict[str, Any],
    *,
    max_list_items: int,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    runner_failure = compact_benchmark_runner_failure(source.get("runner_failure"))
    if runner_failure:
        compact["runner_failure"] = runner_failure
    fingerprint = compact_benchmark_runner_failure_fingerprint(
        source.get("runner_failure_fingerprint"),
        max_list_items=max_list_items,
    )
    if fingerprint:
        compact["runner_failure_fingerprint"] = fingerprint
    return compact


def _compact_progress_metrics(source: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    progress = compact_numeric_map(
        source.get("progress"),
        keys=(
            "n_total_trials",
            "n_completed_trials",
            "n_errored_trials",
            "n_running_trials",
            "n_pending_trials",
            "n_cancelled_trials",
            "n_retries",
        ),
    )
    if progress:
        compact["progress"] = progress
    metrics = compact_numeric_map(
        source.get("metrics"),
        keys=("input_tokens", "cache_tokens", "output_tokens", "cost_usd"),
    )
    if metrics:
        compact["metrics"] = metrics
    return compact


def _compact_lifecycle(source: dict[str, Any]) -> dict[str, Any]:
    sections = (
        (
            "goal_start_product_mode_control_score",
            compact_goal_start_product_mode_control_score(
                source.get("goal_start_product_mode_control_score")
            ),
        ),
        (
            "round_reward_trace",
            compact_benchmark_round_reward_trace(source.get("round_reward_trace")),
        ),
        (
            "overhead_attribution_counters",
            compact_benchmark_overhead_attribution_counters(
                source.get("overhead_attribution_counters")
            ),
        ),
        (
            "episode_policy",
            _compact_benchmark_episode_policy(source.get("episode_policy")),
        ),
        (
            "product_mode_lifecycle_contract",
            compact_product_mode_lifecycle_contract(
                source.get("product_mode_lifecycle_contract")
            ),
        ),
        (
            "native_goal_worker_contract",
            compact_native_goal_worker_contract(
                source.get("native_goal_worker_contract")
            ),
        ),
        (
            "app_server_goal_round_semantics",
            compact_app_server_goal_round_semantics(
                source.get("app_server_goal_round_semantics")
            ),
        ),
        (
            "case_event_timeline",
            compact_benchmark_case_event_timeline(source.get("case_event_timeline")),
        ),
    )
    return {field: value for field, value in sections if value}


def _compact_active_user_and_claim(source: dict[str, Any]) -> dict[str, Any]:
    sections = (
        (
            "active_user_assisted_treatment_preflight",
            _compact_active_user_assisted_treatment_preflight(
                source.get("active_user_assisted_treatment_preflight")
            ),
        ),
        (
            "active_user_private_launcher_plan",
            _compact_active_user_private_launcher_plan(
                source.get("active_user_private_launcher_plan")
            ),
        ),
        (
            "active_user_observation",
            _compact_active_user_observation(source.get("active_user_observation")),
        ),
        ("claim_gate", _compact_benchmark_claim_gate(source.get("claim_gate"))),
    )
    return {field: value for field, value in sections if value}


def _compact_worker_outcome(source: dict[str, Any]) -> dict[str, Any]:
    sections = (
        (
            "environment_setup_failure_context",
            compact_environment_setup_failure_context(
                source.get("environment_setup_failure_context")
            ),
        ),
        (
            "worker_bridge_outcome",
            compact_worker_bridge_outcome(source.get("worker_bridge_outcome")),
        ),
    )
    return {field: value for field, value in sections if value}


def _compact_active_user_assisted_treatment_preflight(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(
        compact,
        value,
        (
            "schema_version",
            "pilot_schema_version",
            "active_injection_schema_version",
            "operator_simulator_run_schema_version",
            "simulator_setting",
            "next_step",
        ),
        limit=140,
    )
    _copy_bool_fields(
        compact,
        value,
        (
            "proactive_intervention_allowed",
            "directive_feedback_allowed",
            "artificial_mildness_required",
            "frequency_budget_required",
            "visibility_policy_required",
            "no_oracle_audit_required",
            "assisted_collaboration_claim_allowed",
            "official_score_claim_allowed",
            "leaderboard_claim_allowed",
        ),
    )

    channel = value.get("simulator_to_worker_injection_channel")
    if not isinstance(channel, dict):
        channel = {}
    compact_channel: dict[str, Any] = {}
    _copy_text_fields(
        compact_channel,
        channel,
        (
            "schema_version",
            "first_blocker",
            "required_capability",
            "current_agent_surface",
            "active_user_feed_jsonl",
            "active_user_observation_json",
            "next_channel_requirement",
            "minimum_next_implementation",
            "required_missing_channel",
        ),
        limit=140,
    )
    checked_count = channel.get("checked_channel_count")
    if isinstance(checked_count, int) and not isinstance(checked_count, bool):
        compact_channel["checked_channel_count"] = checked_count

    checked_channel_names = channel.get("checked_channel_names")
    if not isinstance(checked_channel_names, list):
        checked_channel_names = []
    channel_names = [
        name
        for name in (
            public_safe_compact_text(item, limit=80)
            for item in checked_channel_names
        )
        if name
    ]
    required_missing_channel = ""
    checked_channels = channel.get("checked_channels")
    if isinstance(checked_channels, list):
        for item in checked_channels:
            if not isinstance(item, dict):
                continue
            name = public_safe_compact_text(item.get("channel"), limit=80)
            verdict = public_safe_compact_text(item.get("verdict"), limit=80)
            if name:
                channel_names.append(name)
            if verdict == "required_missing" and name and not required_missing_channel:
                required_missing_channel = name
    if channel_names:
        compact_channel["checked_channel_names"] = channel_names[:5]
    if required_missing_channel:
        compact_channel["required_missing_channel"] = required_missing_channel
    _copy_bool_fields(
        compact_channel,
        channel,
        (
            "channel_available",
            "initial_prompt_only_is_not_active_intervention",
            "direct_codex_chat_injection_available",
            "audited_external_update_loop_available",
            "no_user_message_injected",
            "model_api_invoked",
            "raw_transcript_recorded",
        ),
    )
    if compact_channel:
        compact["simulator_to_worker_injection_channel"] = compact_channel

    launcher_plan = _compact_active_user_private_launcher_plan(
        value.get("private_launcher_plan")
    )
    if launcher_plan:
        compact["private_launcher_plan"] = launcher_plan
    return compact


def _compact_active_user_private_launcher_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(
        compact,
        value,
        (
            "schema_version",
            "launch_surface",
            "first_blocker",
            "required_capability",
            "worker_start_marker",
            "active_user_feed_jsonl",
            "active_user_observation_json",
            "simulator_setting",
        ),
        limit=140,
    )
    contract = value.get("codex_simulator_contract")
    if not isinstance(contract, dict):
        contract = {}
    compact_contract: dict[str, Any] = {}
    _copy_text_fields(
        compact_contract,
        contract,
        (
            "schema_version",
            "simulator_kind",
            "codex_exec_command",
            "append_validated_output_command",
            "simulator_output_schema_version",
        ),
        limit=500,
    )
    _copy_bool_fields(
        compact_contract,
        contract,
        (
            "manual_controller_feed_allowed",
            "formal_treatment_requires_model_backed_simulator",
            "controller_authored_feed_allowed",
        ),
    )
    if compact_contract:
        compact["codex_simulator_contract"] = compact_contract
    if isinstance(value.get("ready"), bool):
        compact["ready"] = value["ready"]
    for field in ("sequence_steps", "required_evidence", "stop_conditions"):
        items = public_safe_compact_list(value.get(field), limit=8)
        if items:
            compact[field] = items
    for nested_name in ("claim_boundary", "public_boundary"):
        nested = value.get(nested_name)
        if not isinstance(nested, dict):
            nested = {}
        compact_nested: dict[str, Any] = {}
        for key, nested_value in nested.items():
            safe_key = public_safe_compact_text(key, limit=80)
            if not safe_key:
                continue
            if isinstance(nested_value, bool):
                compact_nested[safe_key] = nested_value
            else:
                text = public_safe_compact_text(nested_value, limit=120)
                if text:
                    compact_nested[safe_key] = text
        if compact_nested:
            compact[nested_name] = compact_nested
    return compact


def _compact_active_user_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(
        compact,
        value,
        ("schema_version", "bridge_surface", "channel_surface", "next_action"),
        limit=140,
    )
    _copy_bool_fields(
        compact,
        value,
        (
            "feed_present",
            "feed_path_recorded",
            "observed_after_worker_start",
            "worker_observation_proof",
        ),
    )
    _copy_int_fields(
        compact,
        value,
        (
            "worker_start_seq",
            "valid_intervention_count",
            "invalid_line_count",
            "observed_intervention_count",
        ),
    )

    latest = value.get("latest_intervention")
    if not isinstance(latest, dict):
        latest = {}
    compact_latest: dict[str, Any] = {}
    _copy_text_fields(
        compact_latest,
        latest,
        ("channel", "type", "trigger", "message"),
        limit=160,
    )
    _copy_int_fields(compact_latest, latest, ("seq",))
    _copy_bool_fields(
        compact_latest,
        latest,
        (
            "oracle_free",
            "hidden_tests_visible",
            "expected_solution_visible",
            "credential_values_visible",
            "private_material_visible",
        ),
    )
    if compact_latest:
        compact["latest_intervention"] = compact_latest

    for field in ("claim_boundary", "public_boundary"):
        boundary = value.get(field)
        if not isinstance(boundary, dict):
            boundary = {}
        compact_boundary: dict[str, Any] = {}
        for key, boundary_value in boundary.items():
            if not isinstance(key, str) or not isinstance(boundary_value, bool):
                continue
            safe_key = public_safe_compact_text(key, limit=80)
            if safe_key:
                compact_boundary[safe_key] = boundary_value
        if compact_boundary:
            compact[field] = compact_boundary
    return compact


def _compact_benchmark_claim_gate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(compact, value, ("schema_version",), limit=100)
    _copy_bool_fields(
        compact,
        value,
        (
            "requires_private_no_upload",
            "requires_worker_loopx_cli_calls",
            "reject_runner_bridge_calls_as_in_case_evidence",
            "reject_codex_runtime_goal_tool_calls_as_loopx_evidence",
            "uplift_claim_allowed",
            "leaderboard_claim_allowed",
        ),
    )
    _copy_int_fields(
        compact,
        value,
        ("required_worker_loopx_cli_call_total_min",),
    )
    return compact


def _compact_benchmark_episode_policy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    compact: dict[str, Any] = {}
    _copy_text_fields(
        compact,
        value,
        (
            "schema_version",
            "mode",
            "worker_topology",
            "loopx_role",
            "runner_role",
            "checkpoint_surface",
            "resumable_episode_style",
        ),
        limit=140,
    )
    _copy_bool_fields(
        compact,
        value,
        (
            "runner_side_guaranteed_writeback",
            "does_not_spawn_additional_agents",
            "does_not_split_task_prompt",
            "does_not_change_task_solution_actor",
            "raw_trace_recorded",
            "product_mode",
            "blind_loop",
            "official_feedback_blinded",
            "reward_feedback_forwarded",
        ),
    )
    _copy_int_fields(compact, value, ("checkpoint_interval_seconds",))
    return compact


def _copy_text_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
    *,
    limit: int,
) -> None:
    for field in fields:
        text = public_safe_compact_text(source.get(field), limit=limit)
        if text:
            target[field] = text


def _copy_bool_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if isinstance(source.get(field), bool):
            target[field] = source[field]


def _copy_int_fields(
    target: dict[str, Any],
    source: dict[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        value = source.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            target[field] = value

#!/usr/bin/env python3
"""Smoke-test the shared benchmark loop protocol contract."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.benchmark_core.loop_protocol import (
    BLIND_LOOP_DEFAULT_MAX_ROUNDS,
    CODEX_ACP_BLIND_LOOP_BASELINE_ROUTE,
    CODEX_CLI_GOAL_BASELINE_ROUTE,
    LEGACY_NONPRODUCT_PROMPT_POLLING_ROUTES,
    LOOPX_GOAL_START_PRODUCT_MODE_ROUTE,
    LOOPX_PACKET_ONLY_OBSERVATION_ROUTE,
    MATCHED_PAIR_CONTRACT_SCHEMA_VERSION,
    MAX5_BLIND_LOOP_NO_FEEDBACK_PROTOCOL_ID,
    PACKET_ONLY_OBSERVATION_PROTOCOL_ID,
    PRODUCT_MODE_MAX5_NO_FEEDBACK_PROTOCOL_ID,
    RAW_CODEX_AUTONOMOUS_MAX5_ROUTE,
    LOOPX_PRODUCT_MODE_ROUTE,
    build_benchmark_loop_contract,
    build_benchmark_loop_controller_trace,
    build_blind_loop_continuation_prompt,
    build_blind_loop_initial_prompt,
    build_product_mode_main_table_comparison_contract,
    classify_loopx_treatment_claim,
    classify_product_mode_main_table_pair,
    render_loop_contract_packet_lines,
)


def main() -> int:
    for route in LEGACY_NONPRODUCT_PROMPT_POLLING_ROUTES:
        legacy = build_benchmark_loop_contract(
            route=route,
            max_rounds=BLIND_LOOP_DEFAULT_MAX_ROUNDS,
        )
        assert legacy["protocol_id"] == MAX5_BLIND_LOOP_NO_FEEDBACK_PROTOCOL_ID
        assert legacy["strict_treatment_claim_allowed"] is False
        assert (
            legacy["claim_blocker"]
            == "historical_nonproduct_invalid_for_comparison"
        )

    packet_only = build_benchmark_loop_contract(
        route=LOOPX_PACKET_ONLY_OBSERVATION_ROUTE,
        protocol_id=PACKET_ONLY_OBSERVATION_PROTOCOL_ID,
    )
    assert packet_only["strict_treatment_claim_allowed"] is False
    assert packet_only["claim_blocker"] == "packet_only_no_max5_controller"

    raw_product = build_benchmark_loop_contract(
        route=RAW_CODEX_AUTONOMOUS_MAX5_ROUTE,
        max_rounds=5,
    )
    assert raw_product["protocol_id"] == PRODUCT_MODE_MAX5_NO_FEEDBACK_PROTOCOL_ID
    assert raw_product["product_mode"] is True
    assert raw_product["official_feedback_blinded"] is True
    goal_start_product = build_benchmark_loop_contract(
        route=LOOPX_GOAL_START_PRODUCT_MODE_ROUTE,
        max_rounds=5,
    )
    assert (
        goal_start_product["protocol_id"]
        == PRODUCT_MODE_MAX5_NO_FEEDBACK_PROTOCOL_ID
    )
    assert goal_start_product["product_mode"] is True
    assert goal_start_product["official_feedback_blinded"] is True

    legacy_feedback_route = build_benchmark_loop_contract(
        route="loopx-goal-start-verifier-feedback-todo",
        max_rounds=16,
    )
    assert legacy_feedback_route["official_feedback_forwarded"] is False
    assert legacy_feedback_route["official_feedback_blinded"] is True
    assert legacy_feedback_route["product_mode"] is False

    product_contract = build_product_mode_main_table_comparison_contract()
    assert product_contract["protocol_id"] == PRODUCT_MODE_MAX5_NO_FEEDBACK_PROTOCOL_ID
    assert (
        product_contract["baseline_arm"]["route"]
        == CODEX_CLI_GOAL_BASELINE_ROUTE
    )
    assert (
        product_contract["treatment_arm"]["route"]
        == LOOPX_GOAL_START_PRODUCT_MODE_ROUTE
    )
    assert product_contract["policy_gate"]["headline_metrics"] == [
        "best_score",
        "final_score",
        "first_success_round",
        "declared_done_score",
    ]
    assert product_contract["policy_gate"]["official_feedback_blinded"] is True
    assert (
        product_contract["policy_gate"][
            "declared_done_stop_requires_no_failed_every_round_reward"
        ]
        is True
    )
    assert (
        product_contract["policy_gate"][
            "continue_after_declared_done_below_passing_reward"
        ]
        is True
    )

    historical_product_contract = build_product_mode_main_table_comparison_contract(
        baseline_route=RAW_CODEX_AUTONOMOUS_MAX5_ROUTE,
        treatment_route=LOOPX_PRODUCT_MODE_ROUTE,
    )
    assert (
        historical_product_contract["baseline_arm"]["route"]
        == RAW_CODEX_AUTONOMOUS_MAX5_ROUTE
    )
    assert (
        historical_product_contract["treatment_arm"]["route"]
        == LOOPX_PRODUCT_MODE_ROUTE
    )
    assert (
        product_contract["treatment_arm"]["agent_surface"]
        == "loopx_goal_start_plan_todo_lifecycle_cli"
    )
    assert (
        product_contract["treatment_arm"]["contract"]["protocol_id"]
        == PRODUCT_MODE_MAX5_NO_FEEDBACK_PROTOCOL_ID
    )

    trace = build_benchmark_loop_controller_trace(
        route=CODEX_ACP_BLIND_LOOP_BASELINE_ROUTE,
        max_rounds=5,
    )
    assert trace["loop_protocol_id"] == MAX5_BLIND_LOOP_NO_FEEDBACK_PROTOCOL_ID
    assert trace["official_feedback_forwarded"] is False
    assert trace["round_rewards"] == []
    assert trace["raw_task_text_recorded"] is False

    initial = build_blind_loop_initial_prompt(
        route=CODEX_ACP_BLIND_LOOP_BASELINE_ROUTE,
        instruction="Synthetic instruction.",
        benchmark_surface="official synthetic benchmark sandbox",
    )
    assert "Codex blind-loop baseline round 1" in initial
    assert "No official reward, pass/fail status" in initial
    assert "Synthetic instruction." in initial
    try:
        build_blind_loop_initial_prompt(
            route="loopx-prompt-polling-test",
            instruction="Synthetic instruction.",
        )
    except ValueError as exc:
        assert "read-only historical labels" in str(exc)
    else:
        raise AssertionError("legacy prompt-polling route must fail closed")

    continuation = build_blind_loop_continuation_prompt(
        scheduled_round=2,
        max_rounds=5,
        persistent_constraint_clause=" Keep protected paths stable.",
    )
    assert "Scheduled blind-loop continuation round 2 of 5" in continuation
    assert "not evidence that the official verifier passed or failed" in continuation
    assert "Keep protected paths stable." in continuation

    historical_claim = classify_loopx_treatment_claim(
        {
            "benchmark_loop_contract": build_benchmark_loop_contract(
                route="loopx-blind-loop-treatment",
                max_rounds=5,
            ),
            "controller_trace_present": True,
            "round_rewards": [{"agent_round": 1, "reward": 0.0}],
        }
    )
    assert historical_claim["strict_loopx_treatment_claim_allowed"] is False
    assert (
        historical_claim["loopx_treatment_evidence_tier"]
        == "historical_nonproduct_invalid_for_comparison"
    )
    assert (
        historical_claim["loopx_treatment_claim_blocker"]
        == "historical_nonproduct_invalid_for_comparison"
    )

    packet_claim = classify_loopx_treatment_claim(
        {
            "benchmark_loop_contract": packet_only,
            "loopx_access_packet_injected": True,
            "worker_loopx_cli_call_total": 0,
        }
    )
    assert packet_claim["strict_loopx_treatment_claim_allowed"] is False
    assert packet_claim["loopx_treatment_evidence_tier"] == "packet_or_incomplete"
    assert "missing_max5_blind_loop_protocol" in packet_claim[
        "loopx_treatment_claim_blocker"
    ]

    matched_pair_contract = {
        "schema_version": MATCHED_PAIR_CONTRACT_SCHEMA_VERSION,
        "case_set_fingerprint": "sha256:case-set",
        "case_order_fingerprint": "sha256:case-order",
        "model": "gpt-fixture",
        "reasoning_effort": "xhigh",
        "task_packet_fingerprint": "sha256:task-packet",
        "instruction_channel": "skillsbench_private_task_packet_v1",
        "sandbox_policy": "docker_workspace_write",
        "network_policy": "matched_default",
        "outer_timeout_sec": 21600,
        "token_budget": 200000,
        "runner_commit": "runner-commit-fixture",
        "reducer_commit": "reducer-commit-fixture",
        "official_verifier_closeout_contract": "skillsbench_official_v1",
        "best_of_retry_replacement": False,
        "symmetric_infra_exclusion": True,
    }
    baseline_run = {
        "benchmark_id": "skillsbench@1.1",
        "case_id": "citation-check",
        "benchmark_loop_contract": build_benchmark_loop_contract(
            route=CODEX_CLI_GOAL_BASELINE_ROUTE,
            max_rounds=5,
        ),
        "arm_id": "codex_cli_goal_baseline",
        "product_mode": True,
        "goal_get_present": True,
        "turn_id_present": True,
        "matched_pair_contract": dict(matched_pair_contract),
        "official_feedback_blinded": True,
        "reward_feedback_forwarded": False,
        "official_score": 0.0,
        "round_rewards": [{"agent_round": 1, "reward": 0.0, "passed": False}],
    }
    treatment_run = {
        "benchmark_id": "skillsbench@1.1",
        "case_id": "citation-check",
        "benchmark_loop_contract": build_benchmark_loop_contract(
            route=LOOPX_GOAL_START_PRODUCT_MODE_ROUTE,
            max_rounds=5,
        ),
        "arm_id": "loopx_goal_start_product_mode",
        "product_mode": True,
        "loopx_inside_case": True,
        "matched_pair_contract": dict(matched_pair_contract),
        "interaction_counters": {
            "goal_start_product_mode": True,
            "selected_p0_todo_id": "todo-fixture-p0",
            "remote_command_file_bridge_agent_task_facing_success_count": 1,
        },
        "goal_start_product_mode_control_score": {
            "satisfied": True,
            "goal_start_guided_command_observed": True,
            "planner_before_todo_write": True,
            "selected_p0_todo_id": "todo-fixture-p0",
            "selected_todo_claimed": True,
            "selected_todo_updated_before_solver": True,
            "selected_todo_completed_before_spend": True,
        },
        "product_mode_lifecycle_contract": {
            "schema_version": "skillsbench_product_mode_lifecycle_contract_v0",
            "satisfied": True,
            "countable_treatment": True,
            "closeout_satisfied": True,
            "agent_bridge_refresh_state_count": 1,
            "agent_bridge_quota_spend_slot_count": 1,
        },
        "official_feedback_blinded": True,
        "reward_feedback_forwarded": False,
        "official_score": 1.0,
        "round_rewards": [
            {"agent_round": 1, "reward": 0.0, "passed": False},
            {"agent_round": 2, "reward": 1.0, "passed": True},
        ],
    }
    product_pair = classify_product_mode_main_table_pair(
        baseline_run=baseline_run,
        treatment_run=treatment_run,
    )
    assert product_pair["main_table_claim_allowed"] is True, product_pair
    assert product_pair["product_mode_pair_complete"] is True, product_pair
    assert product_pair["case_id"] == "citation-check", product_pair
    assert product_pair["treatment_loopx_lifecycle_observed"] is True, product_pair

    baseline_run_8 = dict(baseline_run)
    baseline_run_8["benchmark_loop_contract"] = build_benchmark_loop_contract(
        route=CODEX_CLI_GOAL_BASELINE_ROUTE,
        max_rounds=8,
    )
    treatment_run_8 = dict(treatment_run)
    treatment_run_8["benchmark_loop_contract"] = build_benchmark_loop_contract(
        route=LOOPX_GOAL_START_PRODUCT_MODE_ROUTE,
        max_rounds=8,
    )
    product_pair_8 = classify_product_mode_main_table_pair(
        baseline_run=baseline_run_8,
        treatment_run=treatment_run_8,
    )
    assert product_pair_8["main_table_claim_allowed"] is True, product_pair_8
    assert product_pair_8["contract"]["max_rounds_budget"] == 8, product_pair_8

    mismatched_budget_pair = classify_product_mode_main_table_pair(
        baseline_run=baseline_run,
        treatment_run=treatment_run_8,
    )
    assert mismatched_budget_pair["main_table_claim_allowed"] is False, (
        mismatched_budget_pair
    )
    assert "max_rounds_budget_mismatch" in mismatched_budget_pair["claim_blocker"]

    shallow_treatment = dict(treatment_run)
    shallow_treatment["product_mode_lifecycle_contract"] = {
        "satisfied": True,
        "countable_treatment": True,
    }
    shallow_pair = classify_product_mode_main_table_pair(
        baseline_run=baseline_run,
        treatment_run=shallow_treatment,
    )
    assert shallow_pair["main_table_claim_allowed"] is False, shallow_pair
    assert "treatment_goal_start_lifecycle_incomplete" in shallow_pair[
        "claim_blocker"
    ]

    missing_goal_baseline = dict(baseline_run)
    missing_goal_baseline["goal_get_present"] = False
    missing_goal_pair = classify_product_mode_main_table_pair(
        baseline_run=missing_goal_baseline,
        treatment_run=treatment_run,
    )
    assert missing_goal_pair["main_table_claim_allowed"] is False, missing_goal_pair
    assert "baseline_persistent_goal_turn_not_observed" in missing_goal_pair[
        "claim_blocker"
    ]

    tui_only_baseline = dict(baseline_run)
    tui_only_baseline["goal_get_present"] = False
    tui_only_baseline["turn_id_present"] = False
    tui_only_baseline["interaction_counters"] = {
        "codex_cli_goal_tui_trace_present": True,
        "codex_cli_goal_tui_goal_active_observed_count": 1,
        "codex_cli_goal_tui_first_action_observed_count": 1,
    }
    tui_only_pair = classify_product_mode_main_table_pair(
        baseline_run=tui_only_baseline,
        treatment_run=treatment_run,
    )
    assert "baseline_persistent_goal_turn_not_observed" in tui_only_pair[
        "claim_blocker"
    ]

    mismatch_values = {
        "case_set_fingerprint": "sha256:different-case-set",
        "case_order_fingerprint": "sha256:different-case-order",
        "model": "different-model",
        "reasoning_effort": "high",
        "task_packet_fingerprint": "sha256:different-task-packet",
        "instruction_channel": "different-instruction-channel",
        "sandbox_policy": "different-sandbox",
        "network_policy": "different-network",
        "outer_timeout_sec": 10800,
        "token_budget": 100000,
        "runner_commit": "different-runner-commit",
        "reducer_commit": "different-reducer-commit",
        "official_verifier_closeout_contract": "different-verifier-contract",
    }
    for field, mismatch_value in mismatch_values.items():
        mismatched_treatment = dict(treatment_run)
        mismatched_contract = dict(matched_pair_contract)
        mismatched_contract[field] = mismatch_value
        mismatched_treatment["matched_pair_contract"] = mismatched_contract
        mismatched_pair = classify_product_mode_main_table_pair(
            baseline_run=baseline_run,
            treatment_run=mismatched_treatment,
        )
        assert mismatched_pair["main_table_claim_allowed"] is False
        assert f"{field}_mismatch" in mismatched_pair["claim_blocker"]

    retry_replacement_treatment = dict(treatment_run)
    retry_replacement_contract = dict(matched_pair_contract)
    retry_replacement_contract["best_of_retry_replacement"] = True
    retry_replacement_treatment["matched_pair_contract"] = (
        retry_replacement_contract
    )
    retry_replacement_pair = classify_product_mode_main_table_pair(
        baseline_run=baseline_run,
        treatment_run=retry_replacement_treatment,
    )
    assert "treatment_best_of_retry_replacement_not_disabled" in (
        retry_replacement_pair["claim_blocker"]
    )

    asymmetric_infra_treatment = dict(treatment_run)
    asymmetric_infra_contract = dict(matched_pair_contract)
    asymmetric_infra_contract["symmetric_infra_exclusion"] = False
    asymmetric_infra_treatment["matched_pair_contract"] = (
        asymmetric_infra_contract
    )
    asymmetric_infra_pair = classify_product_mode_main_table_pair(
        baseline_run=baseline_run,
        treatment_run=asymmetric_infra_treatment,
    )
    assert "treatment_symmetric_infra_exclusion_not_confirmed" in (
        asymmetric_infra_pair["claim_blocker"]
    )

    missing_contract_treatment = dict(treatment_run)
    missing_contract_treatment.pop("matched_pair_contract")
    missing_contract_pair = classify_product_mode_main_table_pair(
        baseline_run=baseline_run,
        treatment_run=missing_contract_treatment,
    )
    assert "matched_pair_contract_missing_or_unsupported" in (
        missing_contract_pair["claim_blocker"]
    )

    historical_baseline = dict(baseline_run)
    historical_baseline["route"] = RAW_CODEX_AUTONOMOUS_MAX5_ROUTE
    historical_baseline["arm_id"] = "raw_codex_autonomous_max5"
    historical_baseline["benchmark_loop_contract"] = build_benchmark_loop_contract(
        route=RAW_CODEX_AUTONOMOUS_MAX5_ROUTE,
        max_rounds=5,
    )
    historical_pair = classify_product_mode_main_table_pair(
        baseline_run=historical_baseline,
        treatment_run=treatment_run,
    )
    assert "baseline_not_codex_cli_goal_baseline" in historical_pair[
        "claim_blocker"
    ]

    prefixed_route_baseline = dict(baseline_run)
    prefixed_route_baseline["route"] = "fake-codex-cli-goal-baseline-wrapper"
    prefixed_route_baseline["arm_id"] = "fake_codex_cli_goal_baseline"
    prefixed_route_baseline["benchmark_loop_contract"] = build_benchmark_loop_contract(
        route="fake-codex-cli-goal-baseline-wrapper",
        max_rounds=5,
    )
    prefixed_route_pair = classify_product_mode_main_table_pair(
        baseline_run=prefixed_route_baseline,
        treatment_run=treatment_run,
    )
    assert "baseline_not_codex_cli_goal_baseline" in prefixed_route_pair[
        "claim_blocker"
    ]

    final_score_only_baseline = dict(baseline_run)
    final_score_only_baseline.pop("round_rewards")
    final_score_only_pair = classify_product_mode_main_table_pair(
        baseline_run=final_score_only_baseline,
        treatment_run=treatment_run,
    )
    assert final_score_only_pair["main_table_claim_allowed"] is False, (
        final_score_only_pair
    )
    assert "baseline_compact_metrics_missing" in final_score_only_pair[
        "claim_blocker"
    ]

    lines = render_loop_contract_packet_lines(packet_only)
    assert "benchmark_loop_contract:" in lines
    assert "  protocol_id: packet_only_observation" in lines

    print("benchmark-loop-protocol-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

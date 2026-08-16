from __future__ import annotations

from loopx.control_plane.runtime.active_user_assisted_pilot import (
    compact_active_user_assisted_pilot,
)


def test_compacts_nested_active_user_assisted_pilot_contract() -> None:
    run = {
        "active_user_assisted_pilot": {
            "schema_version": "active_user_assisted_pilot_v0",
            "pilot_id": "pilot-1",
            "benchmark_id": "terminal-bench@2.0",
            "task_id": "train-fasttext",
            "trigger": {
                "kind": "previous_compact_negative_result",
                "assisted_score_kind": "not_run",
                "both_autonomous_modes_failed": True,
                "failed_autonomous_modes": [
                    "baseline",
                    {"mode": "codex_loopx"},
                    {"ignored": "missing mode"},
                ],
            },
            "active_injection_contract": {
                "schema_version": "active_user_simulator_injection_v0",
                "simulator_setting": "deterministic_scripted_user",
                "proactive_intervention_allowed": True,
                "directive_feedback_allowed": False,
                "artificial_mildness_required": True,
            },
            "frequency_budget": {
                "max_interventions": "3",
                "max_proactive_interventions": 2,
                "min_worker_events_between_proactive": 2,
                "max_chars_per_intervention": 800,
            },
            "visibility_policy": {
                "policy_id": "compact-only",
                "allowed": ["public_task_statement", "compact_failure_summary"],
            },
            "operator_simulator_run": {
                "schema_version": "operator_simulator_run_v0",
                "simulator_identity": {
                    "setting": "deterministic_scripted_user",
                    "model_family": "scripted",
                    "seed": "seed-1",
                },
                "interventions": [
                    {
                        "proactive": True,
                        "no_oracle_audit": {"hidden_tests_seen": False},
                    },
                    {
                        "proactive": False,
                        "no_oracle_audit": {"hidden_tests_seen": False},
                    },
                ],
                "official_task_score_reference": {"kind": "not_run"},
                "simulator_induced_error_count": 0,
                "frequency_budget_audit": {
                    "min_worker_events_between_proactive_satisfied": True,
                },
                "side_effect_audit": {"model_api": False, "docker": False},
                "next_run_decision": {
                    "decision": "eligible_for_private_assisted_treatment",
                    "minimum_next_evidence": "one reviewed runner attempt",
                    "requires_real_runner_approval": True,
                    "keep_official_scores_separate": True,
                },
            },
            "claim_boundary": {
                "official_score_claim_allowed": False,
                "assisted_collaboration_claim_allowed": True,
                "leaderboard_claim_allowed": False,
            },
        }
    }

    assert compact_active_user_assisted_pilot(run) == {
        "schema_version": "active_user_assisted_pilot_v0",
        "pilot_id": "pilot-1",
        "benchmark_id": "terminal-bench@2.0",
        "task_id": "train-fasttext",
        "trigger": {
            "kind": "previous_compact_negative_result",
            "assisted_score_kind": "not_run",
            "both_autonomous_modes_failed": True,
            "failed_autonomous_mode_count": 3,
            "failed_autonomous_modes": ["baseline", "codex_loopx"],
        },
        "active_injection_contract": {
            "schema_version": "active_user_simulator_injection_v0",
            "simulator_setting": "deterministic_scripted_user",
            "proactive_intervention_allowed": True,
            "directive_feedback_allowed": False,
            "artificial_mildness_required": True,
        },
        "frequency_budget": {
            "max_interventions": 3,
            "max_proactive_interventions": 2,
            "min_worker_events_between_proactive": 2,
            "max_chars_per_intervention": 800,
        },
        "visibility_policy": {
            "policy_id": "compact-only",
            "allowed_visibility": [
                "public_task_statement",
                "compact_failure_summary",
            ],
        },
        "operator_simulator_run": {
            "schema_version": "operator_simulator_run_v0",
            "setting": "deterministic_scripted_user",
            "model_family": "scripted",
            "seed": "seed-1",
            "intervention_count": 2,
            "proactive_intervention_count": 1,
            "no_oracle_audit_passed": True,
            "official_task_score_kind": "not_run",
            "simulator_induced_error_count": 0,
            "frequency_budget_satisfied": True,
            "side_effect_audit_passed": True,
        },
        "claim_boundary": {
            "official_score_claim_allowed": False,
            "assisted_collaboration_claim_allowed": True,
            "leaderboard_claim_allowed": False,
        },
        "next_run_decision": {
            "decision": "eligible_for_private_assisted_treatment",
            "minimum_next_evidence": "one reviewed runner attempt",
            "requires_real_runner_approval": True,
            "keep_official_scores_separate": True,
        },
    }


def test_rejects_unknown_or_empty_pilot_contracts() -> None:
    assert compact_active_user_assisted_pilot({}) is None
    assert (
        compact_active_user_assisted_pilot(
            {"schema_version": "active_user_assisted_pilot_v0"}
        )
        is None
    )
    assert (
        compact_active_user_assisted_pilot(
            {
                "active_user_assisted_pilot": {
                    "schema_version": "active_user_assisted_pilot_v1",
                    "pilot_id": "future",
                }
            }
        )
        is None
    )


def test_preserves_compact_operator_fallback_fields() -> None:
    assert compact_active_user_assisted_pilot(
        {
            "schema_version": "active_user_assisted_pilot_v0",
            "pilot_id": "pilot-fallback",
            "visibility_policy": {"allowed_visibility": ["public_task_statement"]},
            "operator_simulator_run": {
                "simulator_identity": {},
                "setting": "must-not-replace-empty-identity",
                "intervention_count": 4,
                "proactive_intervention_count": 2,
                "no_oracle_audit_passed": False,
                "official_task_score_kind": "separate_assisted_score",
                "frequency_budget_satisfied": False,
                "side_effect_audit_passed": True,
            },
            "next_run_decision": {
                "decision": "prefer-top-level-decision",
                "keep_official_scores_separate": True,
            },
        }
    ) == {
        "schema_version": "active_user_assisted_pilot_v0",
        "pilot_id": "pilot-fallback",
        "visibility_policy": {
            "allowed_visibility": ["public_task_statement"],
        },
        "operator_simulator_run": {
            "intervention_count": 4,
            "proactive_intervention_count": 2,
            "no_oracle_audit_passed": False,
            "official_task_score_kind": "separate_assisted_score",
            "frequency_budget_satisfied": False,
            "side_effect_audit_passed": True,
        },
        "next_run_decision": {
            "decision": "prefer-top-level-decision",
            "keep_official_scores_separate": True,
        },
    }

from __future__ import annotations

from typing import Any

from .public_safety import (
    compact_numeric_map,
    public_safe_compact_list,
    public_safe_compact_text,
)


ACTIVE_USER_ASSISTED_PILOT_SCHEMA_VERSION = "active_user_assisted_pilot_v0"
OPERATOR_SIMULATOR_RUN_SCHEMA_VERSION = "operator_simulator_run_v0"
MAX_ACTIVE_USER_ASSISTED_PILOT_LIST_ITEMS = 5


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _source(run: dict[str, Any]) -> dict[str, Any] | None:
    nested = run.get("active_user_assisted_pilot")
    if (
        isinstance(nested, dict)
        and nested.get("schema_version")
        == ACTIVE_USER_ASSISTED_PILOT_SCHEMA_VERSION
    ):
        return nested
    if run.get("schema_version") == ACTIVE_USER_ASSISTED_PILOT_SCHEMA_VERSION:
        return run
    return None


def _compact_trigger(value: Any) -> dict[str, Any]:
    trigger = _dict(value)
    compact: dict[str, Any] = {}
    for field in ("kind", "assisted_score_kind"):
        text = public_safe_compact_text(trigger.get(field), limit=120)
        if text:
            compact[field] = text
    if isinstance(trigger.get("both_autonomous_modes_failed"), bool):
        compact["both_autonomous_modes_failed"] = trigger[
            "both_autonomous_modes_failed"
        ]

    failed_modes = trigger.get("failed_autonomous_modes")
    if not isinstance(failed_modes, list) or not failed_modes:
        return compact

    compact["failed_autonomous_mode_count"] = len(failed_modes)
    names: list[str] = []
    for item in failed_modes:
        raw_mode = item if isinstance(item, str) else _dict(item).get("mode")
        mode = public_safe_compact_text(raw_mode, limit=100)
        if mode:
            names.append(mode)
        if len(names) >= MAX_ACTIVE_USER_ASSISTED_PILOT_LIST_ITEMS:
            break
    if names:
        compact["failed_autonomous_modes"] = names
    return compact


def _compact_active_injection_contract(value: Any) -> dict[str, Any]:
    contract = _dict(value)
    compact: dict[str, Any] = {}
    for field in ("schema_version", "simulator_setting"):
        text = public_safe_compact_text(contract.get(field), limit=120)
        if text:
            compact[field] = text
    for field in (
        "proactive_intervention_allowed",
        "directive_feedback_allowed",
        "artificial_mildness_required",
    ):
        if isinstance(contract.get(field), bool):
            compact[field] = contract[field]
    return compact


def _compact_visibility_policy(value: Any) -> dict[str, Any]:
    policy = _dict(value)
    compact: dict[str, Any] = {}
    policy_id = public_safe_compact_text(policy.get("policy_id"), limit=140)
    if policy_id:
        compact["policy_id"] = policy_id
    allowed_source = policy.get("allowed")
    if allowed_source is None:
        allowed_source = policy.get("allowed_visibility")
    allowed = public_safe_compact_list(
        allowed_source,
        limit=MAX_ACTIVE_USER_ASSISTED_PILOT_LIST_ITEMS,
    )
    if allowed:
        compact["allowed_visibility"] = allowed
    return compact


def _compact_operator_simulator_run(value: Any) -> dict[str, Any]:
    operator_run = _dict(value)
    compact: dict[str, Any] = {}
    if (
        operator_run.get("schema_version")
        == OPERATOR_SIMULATOR_RUN_SCHEMA_VERSION
    ):
        compact["schema_version"] = OPERATOR_SIMULATOR_RUN_SCHEMA_VERSION

    raw_simulator_identity = operator_run.get("simulator_identity")
    simulator_identity = (
        raw_simulator_identity
        if isinstance(raw_simulator_identity, dict)
        else operator_run
    )
    for field in ("setting", "model_family", "seed"):
        text = public_safe_compact_text(simulator_identity.get(field), limit=140)
        if text:
            compact[field] = text

    interventions = operator_run.get("interventions")
    if isinstance(interventions, list) and interventions:
        compact["intervention_count"] = len(interventions)
        compact["proactive_intervention_count"] = sum(
            1
            for item in interventions
            if isinstance(item, dict) and item.get("proactive") is True
        )
        compact["no_oracle_audit_passed"] = all(
            isinstance(item, dict)
            and isinstance(item.get("no_oracle_audit"), dict)
            and not any(bool(audit) for audit in item["no_oracle_audit"].values())
            for item in interventions
        )
    else:
        for field in ("intervention_count", "proactive_intervention_count"):
            if isinstance(operator_run.get(field), int):
                compact[field] = operator_run[field]
        if isinstance(operator_run.get("no_oracle_audit_passed"), bool):
            compact["no_oracle_audit_passed"] = operator_run[
                "no_oracle_audit_passed"
            ]

    official_kind = public_safe_compact_text(
        _dict(operator_run.get("official_task_score_reference")).get("kind"),
        limit=100,
    )
    if not official_kind:
        official_kind = public_safe_compact_text(
            operator_run.get("official_task_score_kind"),
            limit=100,
        )
    if official_kind:
        compact["official_task_score_kind"] = official_kind

    if isinstance(operator_run.get("simulator_induced_error_count"), int):
        compact["simulator_induced_error_count"] = operator_run[
            "simulator_induced_error_count"
        ]

    frequency_audit = _dict(operator_run.get("frequency_budget_audit"))
    frequency_satisfied = frequency_audit.get(
        "min_worker_events_between_proactive_satisfied"
    )
    if not isinstance(frequency_satisfied, bool):
        frequency_satisfied = operator_run.get("frequency_budget_satisfied")
    if isinstance(frequency_satisfied, bool):
        compact["frequency_budget_satisfied"] = frequency_satisfied

    side_effect_audit = _dict(operator_run.get("side_effect_audit"))
    if side_effect_audit:
        compact["side_effect_audit_passed"] = not any(
            bool(effect) for effect in side_effect_audit.values()
        )
    elif isinstance(operator_run.get("side_effect_audit_passed"), bool):
        compact["side_effect_audit_passed"] = operator_run[
            "side_effect_audit_passed"
        ]
    return compact


def _compact_claim_boundary(value: Any) -> dict[str, Any]:
    boundary = _dict(value)
    return {
        field: boundary[field]
        for field in (
            "official_score_claim_allowed",
            "assisted_collaboration_claim_allowed",
            "leaderboard_claim_allowed",
        )
        if isinstance(boundary.get(field), bool)
    }


def _compact_next_run_decision(
    value: Any,
    *,
    operator_run: dict[str, Any],
) -> dict[str, Any]:
    decision = _dict(value) or _dict(operator_run.get("next_run_decision"))
    compact: dict[str, Any] = {}
    for field in ("decision", "minimum_next_evidence"):
        text = public_safe_compact_text(decision.get(field), limit=180)
        if text:
            compact[field] = text
    for field in (
        "requires_real_runner_approval",
        "keep_official_scores_separate",
    ):
        if isinstance(decision.get(field), bool):
            compact[field] = decision[field]
    return compact


def compact_active_user_assisted_pilot(
    run: dict[str, Any],
) -> dict[str, Any] | None:
    source = _source(run)
    if not source:
        return None

    compact: dict[str, Any] = {
        "schema_version": ACTIVE_USER_ASSISTED_PILOT_SCHEMA_VERSION
    }
    for field in ("pilot_id", "benchmark_id", "task_id"):
        text = public_safe_compact_text(source.get(field), limit=140)
        if text:
            compact[field] = text

    sections = (
        ("trigger", _compact_trigger(source.get("trigger"))),
        (
            "active_injection_contract",
            _compact_active_injection_contract(
                source.get("active_injection_contract")
            ),
        ),
        (
            "frequency_budget",
            compact_numeric_map(
                source.get("frequency_budget"),
                keys=(
                    "max_interventions",
                    "max_proactive_interventions",
                    "min_worker_events_between_proactive",
                    "max_chars_per_intervention",
                ),
            ),
        ),
        (
            "visibility_policy",
            _compact_visibility_policy(source.get("visibility_policy")),
        ),
    )
    for field, value in sections:
        if value:
            compact[field] = value

    operator_run = _dict(source.get("operator_simulator_run"))
    compact_operator = _compact_operator_simulator_run(operator_run)
    if compact_operator:
        compact["operator_simulator_run"] = compact_operator

    claim_boundary = _compact_claim_boundary(source.get("claim_boundary"))
    if claim_boundary:
        compact["claim_boundary"] = claim_boundary

    next_decision = _compact_next_run_decision(
        source.get("next_run_decision"),
        operator_run=operator_run,
    )
    if next_decision:
        compact["next_run_decision"] = next_decision

    if set(compact) == {"schema_version"}:
        return None
    return compact

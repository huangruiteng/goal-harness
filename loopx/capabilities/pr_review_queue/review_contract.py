from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

REQUIRED_FINAL_SECTIONS = [
    "动机",
    "改动思路",
    "具体改动",
    "对主干的风险",
    "我的整体评价",
]

CODE_AREAS = {
    "product_runtime",
    "app_or_ui_surface",
    "ci_or_release",
    "build_or_config",
}

EXAMPLE_OR_SMOKE_AREAS = {"test_or_example"}

NEGATIVE_PATH_AREAS = CODE_AREAS | {"public_entry_or_policy"}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _line_churn(item: Mapping[str, Any]) -> int:
    try:
        return int(item.get("additions") or 0) + int(item.get("deletions") or 0)
    except (TypeError, ValueError):
        return 0


def _review_order(
    key_files: Sequence[Mapping[str, Any]], *, limit: int = 5
) -> list[str]:
    ranked = sorted(key_files, key=_line_churn, reverse=True)
    return [str(item.get("path") or "") for item in ranked[:limit] if item.get("path")]


def _section(label: str, word_hint: str, instruction: str) -> dict[str, str]:
    return {
        "label": label,
        "word_hint": word_hint,
        "content": "",
        "agent_instruction": instruction,
    }


def build_review_template(item: Mapping[str, Any]) -> dict[str, Any]:
    key_files = [
        candidate
        for candidate in _as_sequence(item.get("key_files"))
        if isinstance(candidate, Mapping)
    ]
    return {
        "schema_version": "pr_review_five_block_template_v0",
        "purpose": "Empty scaffold only; fill it from the verified review evidence, not PR metadata.",
        "sections": [
            _section(
                "动机",
                "200-350字",
                "Use evidence `problem_context`: old behavior, affected caller, concrete cost, before/after outcome, and why the nearest smaller fix is or is not enough.",
            ),
            _section(
                "改动思路",
                "300-500字",
                "Use `architecture_flow` and `walkthroughs`: entry point, authoritative state, decision boundary, positive path, alternative, and ownership trade-off.",
            ),
            _section(
                "具体改动",
                "450-800字",
                "Use `changed_line_classification` and `symbol_map`. Code changes require `### 关键代码讲解` for 2-5 behavior-bearing exact-head symbols; docs-only changes use `### 关键内容讲解`.",
            ),
            _section(
                "对主干的风险",
                "250-500字",
                "Use `failure_analysis`, `walkthroughs.negative`, and `validation_matrix`; trace each finding from triggering state to observed outcome and minimum repair. When `scope_fit` applies, name the active production caller or explicitly record a coverage-only boundary. When `change_proportionality` applies, compare verified problem impact with mechanism and maintenance cost; a resolved implementation blocker does not justify approval when the full exact-head scope remains disproportionate. Surface typed-state-rule, domain-neutrality, behavior-change-disclosure, and guidance-vs-obligation findings when their evidence applies.",
            ),
            _section(
                "我的整体评价",
                "150-300字",
                "Use `code_volume`, `change_proportionality`, validation results, residual risk, and exact-head freshness to state the verdict and the evidence needed for re-review.",
            ),
        ],
        "review_order": _review_order(key_files),
        "output_hint": (
            "Render the verified structured result using the five sections. "
            "The capability-owned review_execution_contract is the evidence and completeness authority."
        ),
    }


def build_review_execution_contract() -> dict[str, Any]:
    return {
        "schema_version": "pull_request_review_execution_contract_v1",
        "purpose": (
            "Define the evidence that must exist before a detailed review verdict; "
            "host skills route this contract but must not reimplement it."
        ),
        "evidence_status_values": ["verified", "unverified", "not_applicable"],
        "evidence_requirements": [
            {
                "evidence_id": "problem_context",
                "required_when": "always",
                "fields": [
                    "author_claim",
                    "old_behavior",
                    "affected_caller_or_operator",
                    "compounding_cost",
                    "before_after_scenario",
                    "smaller_fix_analysis",
                    "observable_outcome",
                    "non_goals",
                ],
            },
            {
                "evidence_id": "architecture_flow",
                "required_when": "always",
                "fields": [
                    "entry_point",
                    "authoritative_input_or_state",
                    "decision_owner",
                    "side_effect_or_transition",
                    "receipt_or_consumer",
                    "failure_or_retry_owner",
                ],
            },
            {
                "evidence_id": "changed_line_classification",
                "required_when": "always",
                "categories": [
                    "production",
                    "tests_or_fixtures",
                    "docs",
                    "generated",
                    "mechanical_moves",
                ],
                "fields": ["files", "additions", "deletions", "behavior_role"],
                "rule": "Classify the exact base..head diff before judging code volume.",
            },
            {
                "evidence_id": "scope_fit",
                "required_when": "code_change",
                "fields": [
                    "shipped_behavior",
                    "active_call_sites",
                    "caller_path_or_none",
                    "coverage_only_declared",
                    "scope_fit_verdict",
                ],
                "rule": (
                    "For every added or moved production module, adapter, CLI "
                    "command, or control-plane contract, verify a shipped "
                    "behavior and at least one active production call site in "
                    "the reviewed branch. Test-only coverage of an unused "
                    "module is not a shipped behavior; name the gap and treat "
                    "it as blocking unless an explicit, owner-accepted "
                    "coverage-only boundary is recorded."
                ),
            },
            {
                "evidence_id": "symbol_map",
                "required_when": "code_change",
                "item_count": {"minimum": 2, "maximum": 5},
                "item_fields": [
                    "path",
                    "line",
                    "symbol",
                    "responsibility",
                    "before_after_behavior",
                    "input_or_pre_state",
                    "critical_branch_or_invariant",
                    "callee_or_side_effect",
                    "return_or_consumer",
                    "failure_fallback_or_retry_owner",
                    "caller_evidence",
                ],
                "source_rule": (
                    "Use exact-head definitions plus unchanged surrounding callers; "
                    "select symbols by behavior, not diff size."
                ),
            },
            {
                "evidence_id": "walkthroughs",
                "required_when": "always",
                "positive_fields": [
                    "trigger",
                    "ordered_symbols_or_steps",
                    "state_transitions",
                    "observable_result",
                ],
                "negative_required_when": (
                    "runtime, selector, policy, authority, lifecycle, installer, bridge, "
                    "or public-entry contract changes"
                ),
                "negative_fields": [
                    "triggering_input_or_state",
                    "ordered_symbols_or_steps",
                    "rejection_fallback_or_wrong_outcome",
                    "error_or_retry_owner",
                ],
            },
            {
                "evidence_id": "validation_matrix",
                "required_when": "always",
                "item_fields": [
                    "invariant_or_case",
                    "command_or_check",
                    "status",
                    "result",
                    "required",
                    "skip_or_failure_reason",
                ],
                "required_cases": [
                    "changed invariant positive case",
                    "material negative or failure case when applicable",
                    "repository-required checks",
                ],
            },
            {
                "evidence_id": "failure_analysis",
                "required_when": "always",
                "fields": [
                    "strongest_regression_scenario",
                    "triggering_state",
                    "permitting_or_preventing_code_path",
                    "blast_radius",
                    "observability",
                    "rollback_or_recovery",
                    "minimum_repair",
                    "regression_test",
                ],
            },
            {
                "evidence_id": "code_volume",
                "required_when": "always",
                "verdict_values": ["necessary", "partly_avoidable", "not_yet_proven"],
                "fields": [
                    "changed_line_shape",
                    "largest_production_hotspots",
                    "active_call_site_evidence",
                    "compatibility_or_migration_need",
                    "verdict",
                    "highest_value_simplification",
                    "behavior_preserving_validation",
                ],
            },
            {
                "evidence_id": "change_proportionality",
                "required_when": "code_change",
                "verdict_values": [
                    "proportionate",
                    "disproportionate",
                    "not_yet_proven",
                ],
                "fields": [
                    "original_problem",
                    "frequency_or_severity",
                    "affected_users_or_operators",
                    "failure_cost_and_recovery",
                    "smallest_viable_fix",
                    "production_mechanism_cost",
                    "new_state_contract_or_cli_surface",
                    "maintenance_and_migration_cost",
                    "alternatives_considered",
                    "scope_growth_since_initial_review",
                    "verdict",
                ],
                "rule": (
                    "Judge the full exact-head change against the original "
                    "user-visible problem, not against how completely the proposed "
                    "mechanism is implemented. Compare verified frequency, severity, "
                    "blast radius, and recovery cost with production code, new state, "
                    "schema, CLI, caller, migration, and long-term maintenance surface. "
                    "Correctness, green CI, and resolution of earlier review findings "
                    "are necessary but do not prove positive value. Treat "
                    "`disproportionate` and `not_yet_proven` as blocking; request the "
                    "smallest viable fix, deletion, split, or hold. On every materially "
                    "expanded re-review, reset this assessment from the original problem "
                    "instead of treating reviewer-requested additions as progress toward "
                    "approval."
                ),
            },
            {
                "evidence_id": "typed_state_rule",
                "required_when": "code_change",
                "fields": [
                    "state_classification_rule",
                    "matching_mechanism",
                    "typed_contract_or_enum",
                    "false_positive_or_negative_risk",
                    "migration_or_followup",
                ],
                "rule": (
                    "State-classification and delivery-semantics rules must be typed "
                    "enums, schemas, or transition helpers. Flag substring denylists, "
                    "scattered booleans, and prose-only assumptions as findings with "
                    "the concrete misclassification risk and the typed alternative."
                ),
            },
            {
                "evidence_id": "domain_neutrality",
                "required_when": "product_runtime_or_policy_contract",
                "fields": [
                    "obligation_or_error_text",
                    "domain_specific_language",
                    "affected_goal_types",
                    "neutral_alternative",
                ],
                "rule": (
                    "Generic control-plane obligations and error text must stay "
                    "domain-neutral. Flag product- or benchmark-specific wording in "
                    "core work-lane, quota, todo, or settlement contracts and propose "
                    "a goal-agnostic alternative."
                ),
            },
            {
                "evidence_id": "behavior_change_disclosure",
                "required_when": "runtime_behavior_change",
                "fields": [
                    "previous_default",
                    "new_default",
                    "affected_callers_or_lanes",
                    "disclosure_surface",
                ],
                "rule": (
                    "Default behavior changes must be disclosed through renamed "
                    "smokes, docs, or release notes. Flag silent behavior changes "
                    "that alter existing automation without naming the old and new "
                    "default."
                ),
            },
            {
                "evidence_id": "guidance_vs_obligation",
                "required_when": "work_lane_or_obligation_contract",
                "fields": [
                    "advisory_or_enforced",
                    "machine_flag",
                    "consequence_when_ignored",
                    "documented_semantics",
                ],
                "rule": (
                    "Advisory versus machine-enforced semantics must be explicit. "
                    "Flag text that calls a hard obligation 'guidance' when a "
                    "contract flag such as must_attempt_work forces a turn, or that "
                    "leaves the enforcement consequence undocumented."
                ),
            },
            {
                "evidence_id": "durable_smoke_value",
                "required_when": "smoke_or_example_only",
                "fields": [
                    "shipped_behavior_or_boundary_guarded",
                    "active_call_site_or_consumer",
                    "existing_coverage_scan",
                    "duplication_verdict",
                    "same_author_batch_scan",
                    "consolidation_or_thinning_recommendation",
                    "real_product_or_repo_value_verdict",
                    "repeat_offender_escalation",
                ],
                "rule": (
                    "For example, walkthrough, or smoke-only PRs, prove the added "
                    "artifact delivers real, durable value to the repository or "
                    "product: it guards shipped behavior or a real boundary, "
                    "improves maintainability, or reduces a concrete maintenance "
                    "cost. Running successfully, being deterministic, and being "
                    "public-safe are necessary but not sufficient. Name the "
                    "existing-coverage scan and reject one-off scaffolding, "
                    "same-shape batch farming, or duplication of existing smokes."
                    " Repeated same-author violations after a REQUEST_CHANGES "
                    "warning escalate to a contribution-restriction "
                    "recommendation: the owner blocks that account from further "
                    "PR submissions. The warning must name this consequence."
                ),
            },
        ],
        "finding_contract": {
            "findings_first": True,
            "required_fields": [
                "severity",
                "trigger",
                "code_path",
                "incorrect_or_risky_outcome",
                "location",
                "minimum_repair",
                "regression_test",
            ],
            "no_finding_rule": (
                "Say no blocking finding explicitly, then name residual risk and the "
                "strongest missing validation."
            ),
        },
        "completion_gate": {
            "metadata_only_verdict_allowed": False,
            "required_status": "Every applicable evidence item is verified or explicitly unverified with a reason.",
            "code_change_symbol_minimum": 2,
            "exact_head_recheck_required": True,
            "stale_head_verdict_allowed": False,
            "blocking_evidence_verdicts": {
                "change_proportionality": [
                    "disproportionate",
                    "not_yet_proven",
                ]
            },
            "required_final_sections": REQUIRED_FINAL_SECTIONS,
        },
        "verdict_policy": {
            "open_pr_blocking_finding": "REQUEST_CHANGES",
            "open_pr_unresolved_proportionality": (
                "REQUEST_CHANGES when change_proportionality is disproportionate "
                "or not_yet_proven; correctness, green CI, and resolved earlier "
                "findings cannot override this gate"
            ),
            "materially_expanded_rereview": (
                "Reset change_proportionality from the original problem and review "
                "the full exact head; do not inherit an approval trajectory from "
                "resolved prior findings"
            ),
            "open_pr_non_blocking_finding": "APPROVE",
            "open_pr_no_finding": "APPROVE",
            "author_owned_no_blocker_fallback": (
                "COMMENTED review titled 'Approval conclusion (author-owned PR; "
                "GitHub blocks formal self-approval)'"
            ),
            "author_owned_blocker_fallback": (
                "COMMENTED review titled 'Request changes conclusion (author-owned "
                "PR; GitHub blocks formal self-review)'"
            ),
            "merged_pr": "POST_MERGE_AUDIT_COMMENT when a new actionable finding exists",
            "publication_exceptions": [
                "explicit local-only request",
                "private or security-sensitive finding",
            ],
        },
    }


def build_review_plan(item: Mapping[str, Any]) -> dict[str, Any]:
    areas = {
        str(area) for area, count in _as_mapping(item.get("areas")).items() if count
    }
    code_change = bool(areas & CODE_AREAS)
    docs_only = bool(areas) and areas <= {"public_docs", "public_entry_or_policy"}
    smoke_or_example_only = bool(areas & EXAMPLE_OR_SMOKE_AREAS) and not code_change
    required_evidence = [
        "problem_context",
        "architecture_flow",
        "changed_line_classification",
        "walkthroughs",
        "validation_matrix",
        "failure_analysis",
        "code_volume",
    ]
    if code_change:
        required_evidence.insert(3, "symbol_map")
        required_evidence.append("scope_fit")
        required_evidence.append("change_proportionality")
        required_evidence.append("typed_state_rule")
        required_evidence.append("behavior_change_disclosure")
    if areas & {"product_runtime", "public_entry_or_policy"}:
        required_evidence.append("domain_neutrality")
        required_evidence.append("guidance_vs_obligation")
    if smoke_or_example_only:
        required_evidence.append("durable_smoke_value")
    number = item.get("number")
    head_oid = str(item.get("head_oid") or "").strip()
    target_key = f"{number}@{head_oid}" if number and head_oid else None
    return {
        "schema_version": "pull_request_review_plan_v1",
        "contract_ref": "agent_response_contract.review_execution_contract",
        "target": {
            "number": number,
            "base_ref": item.get("base_ref"),
            "head_oid": head_oid or None,
            "exact_head_key": target_key,
        },
        "applicability": {
            "areas": sorted(areas),
            "code_change": code_change,
            "docs_only": docs_only,
            "symbol_map_required": code_change,
            "scope_fit_required": code_change,
            "change_proportionality_required": code_change,
            "negative_walkthrough_required": bool(areas & NEGATIVE_PATH_AREAS),
            "typed_state_rule_required": code_change,
            "behavior_change_disclosure_required": code_change,
            "domain_neutrality_required": bool(
                areas & {"product_runtime", "public_entry_or_policy"}
            ),
            "guidance_vs_obligation_required": bool(
                areas & {"product_runtime", "public_entry_or_policy"}
            ),
            "smoke_or_example_only": smoke_or_example_only,
            "durable_smoke_value_required": smoke_or_example_only,
            "duplication_scan_required": smoke_or_example_only,
            "batch_pattern_scan_required": smoke_or_example_only,
        },
        "required_evidence_ids": required_evidence,
        "result_template": {
            "schema_version": "pull_request_review_result_v1",
            "target_exact_head": target_key,
            "evidence": {
                evidence_id: {"status": "unverified"}
                for evidence_id in required_evidence
            },
            "findings": [],
            "residual_risk": "",
            "verdict": "unverified",
        },
    }


def build_agent_response_contract() -> dict[str, Any]:
    return {
        "schema_version": "pr_review_agent_response_contract_v0",
        "table_only_response_allowed": False,
        "slash_prefix_dominates_intent": True,
        "stats_only_requires_explicit_opt_out": True,
        "queue_table_role": "preface_only",
        "default_review_scope": (
            "Review PRs in review_groups.unmerged first, then review_groups.merged, "
            "bounded by the requested limit."
        ),
        "required_packet_fields_to_preserve": [
            "agent_response_contract",
            "agent_response_contract.review_execution_contract",
            "result_completeness",
            "review_groups",
            "pull_requests[].review_plan",
            "pull_requests[].review_template",
            "pull_requests[].evidence_commands",
        ],
        "stats_only_opt_out_examples": [
            "只统计",
            "只列出",
            "stats only",
            "list only",
            "不要 review",
            "不用分析",
        ],
        "required_final_sections": REQUIRED_FINAL_SECTIONS,
        "review_execution_contract": build_review_execution_contract(),
        "explanation_depth_contract": {
            "schema_version": "pr_review_explanation_depth_v0",
            "authority": "agent_response_contract.review_execution_contract",
            "reader_profile": "A technically curious reader who may not know this PR or subsystem.",
            "verdict_preface": "Lead with one evidence-based verdict and the highest-severity reason.",
            "freshness": "Record and recheck the remote head SHA; do not publish a stale verdict.",
        },
        "instructions": [
            "Use review_groups as the queue and require result_completeness.complete=true for exhaustive review.",
            "Execute each pull_requests[].review_plan against the shared review_execution_contract before drafting prose.",
            "Do not infer verified evidence from title, labels, changed-file counts, metadata_risk_hint, or green CI alone.",
            "Recheck the exact remote head before verdict and publication.",
            "Render the verified result through pull_requests[].review_template; host skills must not maintain a competing depth checklist.",
        ],
    }

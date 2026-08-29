from __future__ import annotations

from loopx.capabilities.pr_review_queue import (
    build_agent_response_contract,
    build_review_plan,
    build_review_template,
)


def _item(*, areas: dict[str, int]) -> dict[str, object]:
    return {
        "number": 42,
        "base_ref": "main",
        "head_oid": "a" * 40,
        "areas": areas,
        "key_files": [
            {"path": "src/runtime.py", "additions": 20, "deletions": 5},
            {"path": "tests/test_runtime.py", "additions": 30, "deletions": 0},
        ],
    }


def test_execution_contract_owns_deep_review_requirements() -> None:
    response = build_agent_response_contract()

    assert response["required_packet_fields_to_preserve"] == [
        "agent_response_contract",
        "agent_response_contract.review_execution_contract",
        "result_completeness",
        "review_groups",
        "pull_requests[].review_plan",
        "pull_requests[].review_template",
        "pull_requests[].evidence_commands",
    ]
    contract = response["review_execution_contract"]
    assert contract["schema_version"] == "pull_request_review_execution_contract_v1"
    requirements = {
        item["evidence_id"]: item for item in contract["evidence_requirements"]
    }
    assert set(requirements) == {
        "problem_context",
        "architecture_flow",
        "changed_line_classification",
        "scope_fit",
        "symbol_map",
        "walkthroughs",
        "validation_matrix",
        "failure_analysis",
        "code_volume",
        "change_proportionality",
        "typed_state_rule",
        "domain_neutrality",
        "behavior_change_disclosure",
        "guidance_vs_obligation",
        "durable_smoke_value",
    }
    assert requirements["symbol_map"]["item_count"] == {
        "minimum": 2,
        "maximum": 5,
    }
    assert "caller_evidence" in requirements["symbol_map"]["item_fields"]
    assert "negative_fields" in requirements["walkthroughs"]
    assert "regression_test" in requirements["failure_analysis"]["fields"]
    assert requirements["typed_state_rule"]["required_when"] == "code_change"
    assert "substring denylists" in requirements["typed_state_rule"]["rule"]
    assert "domain-neutral" in requirements["domain_neutrality"]["rule"]
    assert (
        "silent behavior changes" in requirements["behavior_change_disclosure"]["rule"]
    )
    assert "must_attempt_work" in requirements["guidance_vs_obligation"]["rule"]
    proportionality = requirements["change_proportionality"]
    assert proportionality["required_when"] == "code_change"
    assert proportionality["verdict_values"] == [
        "proportionate",
        "disproportionate",
        "not_yet_proven",
    ]
    assert "smallest_viable_fix" in proportionality["fields"]
    assert "maintenance_and_migration_cost" in proportionality["fields"]
    assert "green CI" in proportionality["rule"]
    assert "original problem" in proportionality["rule"]
    assert contract["completion_gate"]["metadata_only_verdict_allowed"] is False
    assert contract["completion_gate"]["stale_head_verdict_allowed"] is False
    assert contract["completion_gate"]["blocking_evidence_verdicts"] == {
        "change_proportionality": ["disproportionate", "not_yet_proven"]
    }
    assert contract["finding_contract"]["findings_first"] is True
    verdict = contract["verdict_policy"]
    assert verdict["open_pr_blocking_finding"] == "REQUEST_CHANGES"
    assert "REQUEST_CHANGES" in verdict["open_pr_unresolved_proportionality"]
    assert "original problem" in verdict["materially_expanded_rereview"]
    assert verdict["open_pr_non_blocking_finding"] == "APPROVE"
    assert verdict["open_pr_no_finding"] == "APPROVE"
    assert "author-owned PR" in verdict["author_owned_no_blocker_fallback"]


def test_runtime_plan_requires_symbol_map_and_negative_walkthrough() -> None:
    plan = build_review_plan(_item(areas={"product_runtime": 1, "test_or_example": 1}))

    assert plan["target"] == {
        "number": 42,
        "base_ref": "main",
        "head_oid": "a" * 40,
        "exact_head_key": f"42@{'a' * 40}",
    }
    assert plan["applicability"]["code_change"] is True
    assert plan["applicability"]["symbol_map_required"] is True
    assert plan["applicability"]["scope_fit_required"] is True
    assert plan["applicability"]["change_proportionality_required"] is True
    assert plan["applicability"]["negative_walkthrough_required"] is True
    assert plan["applicability"]["typed_state_rule_required"] is True
    assert plan["applicability"]["behavior_change_disclosure_required"] is True
    assert plan["applicability"]["domain_neutrality_required"] is True
    assert plan["applicability"]["guidance_vs_obligation_required"] is True
    assert "symbol_map" in plan["required_evidence_ids"]
    assert "scope_fit" in plan["required_evidence_ids"]
    assert "change_proportionality" in plan["required_evidence_ids"]
    assert "typed_state_rule" in plan["required_evidence_ids"]
    assert "behavior_change_disclosure" in plan["required_evidence_ids"]
    assert "domain_neutrality" in plan["required_evidence_ids"]
    assert "guidance_vs_obligation" in plan["required_evidence_ids"]
    assert set(plan["result_template"]["evidence"]) == set(
        plan["required_evidence_ids"]
    )
    assert all(
        item["status"] == "unverified"
        for item in plan["result_template"]["evidence"].values()
    )


def test_docs_plan_does_not_invent_code_symbols() -> None:
    item = _item(areas={"public_docs": 2})
    item["key_files"] = [{"path": "docs/design.md", "additions": 15, "deletions": 2}]

    plan = build_review_plan(item)
    template = build_review_template(item)

    assert plan["applicability"]["docs_only"] is True
    assert plan["applicability"]["symbol_map_required"] is False
    assert plan["applicability"]["scope_fit_required"] is False
    assert plan["applicability"]["change_proportionality_required"] is False
    assert plan["applicability"]["typed_state_rule_required"] is False
    assert plan["applicability"]["behavior_change_disclosure_required"] is False
    assert plan["applicability"]["domain_neutrality_required"] is False
    assert plan["applicability"]["guidance_vs_obligation_required"] is False
    assert "symbol_map" not in plan["required_evidence_ids"]
    assert "scope_fit" not in plan["required_evidence_ids"]
    assert "change_proportionality" not in plan["required_evidence_ids"]
    assert "typed_state_rule" not in plan["required_evidence_ids"]
    assert "domain_neutrality" not in plan["required_evidence_ids"]
    assert "behavior_change_disclosure" not in plan["required_evidence_ids"]
    assert "guidance_vs_obligation" not in plan["required_evidence_ids"]
    concrete = next(
        section for section in template["sections"] if section["label"] == "具体改动"
    )
    assert "### 关键内容讲解" in concrete["agent_instruction"]
    assert template["review_order"] == ["docs/design.md"]


def test_smoke_only_plan_requires_durable_value_evidence() -> None:
    item = _item(areas={"test_or_example": 1})
    item["key_files"] = [
        {"path": "examples/walkthrough-smoke.py", "additions": 500, "deletions": 0}
    ]

    plan = build_review_plan(item)

    assert plan["applicability"]["code_change"] is False
    assert plan["applicability"]["docs_only"] is False
    assert plan["applicability"]["smoke_or_example_only"] is True
    assert plan["applicability"]["durable_smoke_value_required"] is True
    assert plan["applicability"]["duplication_scan_required"] is True
    assert plan["applicability"]["batch_pattern_scan_required"] is True
    assert "durable_smoke_value" in plan["required_evidence_ids"]
    assert set(plan["result_template"]["evidence"]) == set(
        plan["required_evidence_ids"]
    )


def test_runtime_plan_does_not_require_smoke_durability_gate() -> None:
    plan = build_review_plan(_item(areas={"product_runtime": 1}))

    assert plan["applicability"]["smoke_or_example_only"] is False
    assert plan["applicability"]["durable_smoke_value_required"] is False
    assert "durable_smoke_value" not in plan["required_evidence_ids"]


def test_test_only_plan_skips_runtime_lenses() -> None:
    plan = build_review_plan(_item(areas={"test_or_example": 2}))

    assert plan["applicability"]["code_change"] is False
    assert plan["applicability"]["typed_state_rule_required"] is False
    assert plan["applicability"]["behavior_change_disclosure_required"] is False
    assert plan["applicability"]["domain_neutrality_required"] is False
    assert plan["applicability"]["guidance_vs_obligation_required"] is False
    assert "typed_state_rule" not in plan["required_evidence_ids"]
    assert "domain_neutrality" not in plan["required_evidence_ids"]

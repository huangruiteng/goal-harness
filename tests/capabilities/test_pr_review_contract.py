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
        "symbol_map",
        "walkthroughs",
        "validation_matrix",
        "failure_analysis",
        "code_volume",
    }
    assert requirements["symbol_map"]["item_count"] == {
        "minimum": 2,
        "maximum": 5,
    }
    assert "caller_evidence" in requirements["symbol_map"]["item_fields"]
    assert "negative_fields" in requirements["walkthroughs"]
    assert "regression_test" in requirements["failure_analysis"]["fields"]
    assert contract["completion_gate"]["metadata_only_verdict_allowed"] is False
    assert contract["completion_gate"]["stale_head_verdict_allowed"] is False
    assert contract["finding_contract"]["findings_first"] is True


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
    assert plan["applicability"]["negative_walkthrough_required"] is True
    assert "symbol_map" in plan["required_evidence_ids"]
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
    assert "symbol_map" not in plan["required_evidence_ids"]
    concrete = next(
        section for section in template["sections"] if section["label"] == "具体改动"
    )
    assert "### 关键内容讲解" in concrete["agent_instruction"]
    assert template["review_order"] == ["docs/design.md"]

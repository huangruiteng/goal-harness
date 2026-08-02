from __future__ import annotations

from typing import Any

import pytest

from loopx.capabilities.context_providers import (
    ContextProviderItem,
    ContextProviderRetrieval,
)
from loopx.capabilities.material_lifecycle import (
    build_material_explore_intent,
    execute_material_explore_intent,
)

OBSERVED_AT = "2026-07-26T13:00:00+08:00"


def explore_intent(**overrides: Any) -> dict[str, Any]:
    values = {
        "goal_id": "goal:material-example",
        "intent_id": "intent:runtime-adoption",
        "inventory_ref": "material-inventory-0123456789abcdef",
        "decision_evidence_ref": "decision-evidence-0123456789abcdef",
        "policy_ref": "policy:material-fit",
        "observed_at": OBSERVED_AT,
        "max_explore_topics": 2,
        "max_provider_calls": 2,
        "max_new_candidates": 3,
        "stop_condition": "Stop when the evidence gap closes or the budget is exhausted.",
        "topics": [
            {
                "topic_ref": "topic:runtime-adoption",
                "reason_code": "evidence_gap",
                "evidence_refs": ["fact:priority-shift"],
            },
            {
                "topic_ref": "topic:recovery-outcome",
                "reason_code": "evidence_gap",
                "evidence_refs": ["fact:priority-shift"],
            },
        ],
    }
    values.update(overrides)
    return build_material_explore_intent(**values)


class RecallProvider:
    provider_id = "openviking"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.queries: list[str] = []

    def retrieve(self, **kwargs: Any) -> ContextProviderRetrieval:
        self.queries.append(kwargs["query"])
        if self.fail:
            raise RuntimeError("provider unavailable")
        topic = kwargs["query_summary"].rsplit(" ", 1)[-1]
        return ContextProviderRetrieval(
            provider=self.provider_id,
            namespace=kwargs["namespace"],
            status="completed",
            query_summary=kwargs["query_summary"],
            observed_at=kwargs["observed_at"],
            search_performed=True,
            read_performed=True,
            items=(
                ContextProviderItem(
                    resource_ref=f"viking://resources/private/{topic}",
                    summary="A bounded material exploration result.",
                    content=f"private content for {topic}",
                    score=0.8,
                ),
            ),
            requested_limit=kwargs["max_results"],
        )


def execute(provider: Any, **overrides: Any) -> Any:
    values = {
        "provider": provider,
        "explore_intent": explore_intent(),
        "queries": {
            "topic:runtime-adoption": "runtime adoption evidence",
            "topic:recovery-outcome": "recovery outcome evidence",
        },
        "namespace": "material-explore",
        "scope_ref": "viking://user/default/resources/materials",
        "execution_authority_ref": "owner-direction:bounded-explore",
        "observed_at": OBSERVED_AT,
        "timeout_seconds": 10,
    }
    values.update(overrides)
    return execute_material_explore_intent(**values)


def test_executes_bounded_provider_calls_without_authorizing_rerank() -> None:
    provider = RecallProvider()

    execution = execute(provider)
    receipt = execution.public_receipt()

    assert receipt["status"] == "completed"
    assert receipt["provider_call_count"] == 2
    assert receipt["completed_call_count"] == 2
    assert receipt["candidate_count"] == 2
    assert receipt["exact_read_required_for_promotion"] is True
    assert receipt["rerank_authorized"] is False
    assert receipt["new_candidate_apply_authorized"] is False
    assert receipt["raw_queries_captured"] is False
    assert receipt["raw_content_captured"] is False
    assert "private content" not in str(receipt)
    assert "viking://resources/private" not in str(receipt)
    assert len(execution.candidates) == 2
    assert execution.candidates[0].content.startswith("private content")
    assert provider.queries == [
        "recovery outcome evidence",
        "runtime adoption evidence",
    ]


def test_provider_failure_fails_open_without_partial_candidates() -> None:
    execution = execute(RecallProvider(fail=True))
    receipt = execution.public_receipt()

    assert receipt["status"] == "unavailable"
    assert receipt["completed_call_count"] == 0
    assert receipt["candidate_count"] == 0
    assert receipt["provider_fail_open"] is True
    assert execution.candidates == ()
    assert {topic["reason_code"] for topic in receipt["topics"]} == {
        "provider_retrieval_failed"
    }


def test_candidate_budget_stops_later_topics_without_extra_calls() -> None:
    provider = RecallProvider()
    intent = explore_intent(max_new_candidates=1)

    execution = execute(provider, explore_intent=intent)
    receipt = execution.public_receipt()

    assert receipt["status"] == "completed"
    assert receipt["provider_call_count"] == 1
    assert receipt["candidate_count"] == 1
    assert receipt["topics"][1]["status"] == "budget_exhausted"
    assert provider.queries == ["recovery outcome evidence"]


def test_tampered_intent_and_query_scope_are_rejected_before_provider_call() -> None:
    provider = RecallProvider()
    tampered = explore_intent()
    tampered["constraints"]["max_provider_calls"] = 3

    with pytest.raises(ValueError, match="canonical payload"):
        execute(provider, explore_intent=tampered)
    with pytest.raises(ValueError, match="outside the explore intent"):
        execute(
            provider,
            queries={
                "topic:runtime-adoption": "runtime adoption evidence",
                "topic:recovery-outcome": "recovery outcome evidence",
                "topic:extra": "must not run",
            },
        )
    assert provider.queries == []

    neutral_provider = RecallProvider()
    execution = execute(
        neutral_provider,
        scope_ref="goal-scoped-material-authority",
    )
    assert execution.public_receipt()["status"] == "completed"
    assert len(neutral_provider.queries) == 2

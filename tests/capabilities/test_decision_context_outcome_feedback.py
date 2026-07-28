from __future__ import annotations

import copy
import json

import pytest

from loopx.capabilities.context_providers.base import (
    ContextProviderItem,
    ContextProviderRetrieval,
)
from loopx.capabilities.decision_context import (
    build_decision_evidence_packet,
    build_decision_outcome_feedback,
    build_decision_outcome_receipt,
)


OBSERVED_AT = "2026-07-26T05:08:48+00:00"
REVIEW_AT = "2026-07-29T05:08:48+00:00"


def evidence_packet(*, promoted: bool = True) -> dict[str, object]:
    return build_decision_evidence_packet(
        goal_id="goal:decision-advisor",
        decision_id="decision:openviking-fusion",
        observed_at=OBSERVED_AT,
        recalled_claims=(
            [
                {
                    "claim_id": "claim:current-authority",
                    "summary": "The current authority supports bounded fusion.",
                    "provider_ref": "provider:semantic-recall",
                    "source_ref": "source:decision-ledger",
                    "source_revision": "revision:current",
                    "observed_at": OBSERVED_AT,
                    "exact_read_verified": True,
                    "confidence": 0.95,
                }
            ]
            if promoted
            else []
        ),
        stale_or_rejected_claims=[
            {
                "claim_id": "claim:stale-route",
                "summary": "The old route no longer matches current authority.",
                "observed_at": OBSERVED_AT,
                "reason_code": "stale_authority_revision",
            }
        ],
        conflicts=[
            {
                "conflict_id": "conflict:priority",
                "summary": "The latest owner direction supersedes the old route.",
                "source_refs": ["source:decision-ledger", "source:legacy-route"],
                "conflict_rule": "latest_explicit_authority_wins",
                "status": "resolved",
            }
        ],
        source_revisions=[
            {
                "source_ref": "source:decision-ledger",
                "revision": "revision:current",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            }
        ],
        provider_health=[
            {
                "provider": "semantic-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            }
        ],
    )


def outcome_receipt(
    evidence: dict[str, object],
    *,
    verification_status: str = "verified",
) -> dict[str, object]:
    observed_outcomes = (
        [
            {
                "outcome_id": "outcome:bounded-fusion",
                "summary": "The promoted evidence changed the selected action.",
                "evidence_ref": evidence["packet_ref"],
                "status": "verified",
                "observed_at": OBSERVED_AT,
            }
        ]
        if verification_status == "verified"
        else []
    )
    return build_decision_outcome_receipt(
        goal_id=str(evidence["goal_id"]),
        decision_id=str(evidence["decision_id"]),
        proposal_packet_ref="decision-proposal:example",
        recorded_at=OBSERVED_AT,
        verification_status=verification_status,
        accepted_decision={
            "option_id": "option:bounded-fusion",
            "summary": "Use semantic recall under exact-read authority.",
            "accepted_by": "agent:decision-advisor",
            "accepted_at": OBSERVED_AT,
        },
        resulting_transitions=[
            {
                "transition_id": "transition:activate-provider",
                "summary": "The advisory provider entered bounded dogfood.",
                "event_ref": "event:provider-dogfood",
                "status": "committed",
            }
        ],
        observed_outcomes=observed_outcomes,
        invalidated_assumptions=[],
        review_at=REVIEW_AT,
    )


def build_feedback(
    evidence: dict[str, object],
    outcome: dict[str, object],
    *,
    retrieval_receipt: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_decision_outcome_feedback(
        evidence_packet=evidence,
        outcome_receipt=outcome,
        workspace_ref="workspace:example",
        project_ref="project:decision-advisor",
        retrieval_receipt=retrieval_receipt,
    )


def test_verified_promoted_recall_creates_review_only_candidate() -> None:
    evidence = evidence_packet()
    feedback = build_feedback(evidence, outcome_receipt(evidence))

    assert feedback["schema_version"] == "decision_outcome_feedback_v0"
    assert feedback["retrieval_telemetry"] == {
        "discovered_result_count": 2,
        "exact_read_promoted_count": 1,
        "rejected_result_count": 1,
        "rejected_recall_record_count": 1,
        "rejection_reason_counts": {"stale_authority_revision": 1},
        "provider_health_status_counts": {"healthy": 1},
        "current_source_revision_count": 1,
        "count_mode": "evidence_records",
    }
    assert feedback["outcome_telemetry"]["linked_verified_outcome_count"] == 1
    assert feedback["reward_memory"] == {
        "candidate_created": True,
        "candidate_status": "review_ready",
        "candidate_ref": feedback["reward_memory_candidate"]["candidate"][
            "candidate_ref"
        ],
        "ineligible_reason_codes": [],
        "review_required": True,
        "automatic_ingest_performed": False,
        "automatic_activation_performed": False,
    }
    candidate = feedback["reward_memory_candidate"]
    assert candidate["candidate"]["lifecycle"]["state"] == "candidate"
    assert candidate["candidate_persisted"] is False
    assert candidate["provider_write_performed"] is False
    assert candidate["external_writes_performed"] is False


def test_rejected_recall_is_telemetry_only() -> None:
    evidence = evidence_packet(promoted=False)
    feedback = build_feedback(evidence, outcome_receipt(evidence))

    assert feedback["retrieval_telemetry"]["exact_read_promoted_count"] == 0
    assert feedback["retrieval_telemetry"]["rejected_result_count"] == 1
    assert feedback["reward_memory_candidate"] is None
    assert feedback["reward_memory"]["candidate_created"] is False
    assert feedback["reward_memory"]["ineligible_reason_codes"] == [
        "no_exact_read_promoted_claim"
    ]


def test_pending_outcome_does_not_create_candidate() -> None:
    evidence = evidence_packet()
    feedback = build_feedback(
        evidence,
        outcome_receipt(evidence, verification_status="pending"),
    )

    assert feedback["reward_memory_candidate"] is None
    assert feedback["reward_memory"]["ineligible_reason_codes"] == [
        "outcome_not_candidate_eligible",
        "outcome_not_verified",
        "verified_outcome_not_linked_to_evidence",
    ]


def test_retrieval_receipt_preserves_real_result_rejection_count() -> None:
    evidence = evidence_packet()
    receipt = ContextProviderRetrieval(
        provider="semantic-provider",
        namespace="decision-context",
        status="completed",
        query_summary="bounded decision recall",
        observed_at=OBSERVED_AT,
        search_performed=True,
        read_performed=True,
        items=tuple(
            ContextProviderItem(
                resource_ref=f"resource:{index}",
                summary=f"Result {index}",
                content=f"Transient result {index}",
                score=0.9,
            )
            for index in range(6)
        ),
        requested_limit=6,
    ).public_packet()
    feedback = build_feedback(
        evidence,
        outcome_receipt(evidence),
        retrieval_receipt=receipt,
    )

    assert feedback["retrieval_telemetry"]["discovered_result_count"] == 6
    assert feedback["retrieval_telemetry"]["exact_read_promoted_count"] == 1
    assert feedback["retrieval_telemetry"]["rejected_result_count"] == 5
    assert feedback["retrieval_telemetry"]["rejected_recall_record_count"] == 1
    assert feedback["retrieval_telemetry"]["count_mode"] == "retrieval_receipt"


def test_feedback_rejects_tampered_packets() -> None:
    evidence = evidence_packet()
    tampered = copy.deepcopy(evidence)
    tampered["recalled_claims"][0]["summary"] = "Tampered after packet hashing."

    with pytest.raises(ValueError, match="canonical and untampered"):
        build_feedback(tampered, outcome_receipt(evidence))


def test_feedback_projection_contains_no_raw_provider_or_activation_state() -> None:
    evidence = evidence_packet()
    serialized = json.dumps(
        build_feedback(evidence, outcome_receipt(evidence)),
        sort_keys=True,
    )

    assert '"provider_payload":' not in serialized
    assert '"raw_chat":' not in serialized
    assert '"private_locator":' not in serialized
    assert '"state": "active"' not in serialized

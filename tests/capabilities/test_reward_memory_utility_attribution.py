from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from loopx.capabilities.reward_memory.memory_utility import (
    MEMORY_UTILITY_OBSERVATION_SCHEMA_VERSION,
    build_reward_memory_utility_observation,
    reward_memory_application_receipt_id,
    validate_reward_memory_utility_observation,
)
from loopx.capabilities.reward_memory.dogfood import (
    build_reward_memory_dogfood_batch,
    build_reward_memory_dogfood_receipt,
)


CREATED_AT = "2026-08-15T00:00:00Z"
MEMORY_A = "0123456789abcdef"
MEMORY_B = "fedcba9876543210"


def application_receipt(*, memories: list[str] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "reward_memory_application_receipt_v0",
        "application_id": "application:issue-3214",
        "artifact_ref": "artifact:patch-3214",
        "corpus_id": "reward-memory-corpus",
        "surface_id": "loopx.issue_fix",
        "mode": "function_boundary",
        "query_kind": "business_recall",
        "query_evidence": [
            {
                "query_digest": "aabbccddeeff0011",
                "query_summary": "reviewed guidance for this patch",
                "exact_query_exposed": False,
            }
        ],
        "outcome": "applied",
        "memory_ref_digests": memories or [MEMORY_A],
        "reasoning_summary": "Applied the recalled guidance to the patch.",
        "current_artifact_verified": True,
        "result_readback_verified": True,
        "provider_call_count": 1,
        "model_reasoning_preserved": True,
        "grants_new_action_authority": False,
        "external_writes_performed": False,
        "raw_content_captured": False,
    }


def verified_outcome() -> dict[str, Any]:
    return {
        "verified": True,
        "outcome_ref": "effect:test-suite:3214",
        "artifact_ref": "artifact:patch-3214",
        "outcome_status": "succeeded",
    }


def attribution_context() -> dict[str, Any]:
    return {
        "scope": {
            "agent_id": "codex-memory-agent",
            "project_id": "loopx-project",
            "corpus_id": "reward-memory-corpus",
            "surface_id": "loopx.issue_fix",
        },
        "retrieval_snapshot_ref": "retrieval-snapshot:3214",
        "policy_snapshot_ref": "policy-snapshot:v1",
    }


def evaluator_proposal(
    *,
    memories: list[str] | None = None,
    utility_label: str = "unknown",
    attribution_level: str = "set",
    evidence_basis: str = "insufficient",
    evidence_refs: list[str] | None = None,
    confidence: float = 0.0,
) -> dict[str, Any]:
    context = attribution_context()
    outcome = verified_outcome()
    return {
        "scope": dict(context["scope"]),
        "application_id": "application:issue-3214",
        "artifact_ref": outcome["artifact_ref"],
        "outcome_ref": outcome["outcome_ref"],
        "outcome_status": outcome["outcome_status"],
        "retrieval_snapshot_ref": context["retrieval_snapshot_ref"],
        "policy_snapshot_ref": context["policy_snapshot_ref"],
        "memory_ref_digests": memories or [MEMORY_A],
        "utility_label": utility_label,
        "attribution_level": attribution_level,
        "evidence_basis": evidence_basis,
        "confidence": confidence,
        "reason_codes": ["application-is-not-causal-evidence"],
        "evidence_refs": evidence_refs or [],
        "evaluator_ref": "evaluator:fixture",
        "evaluation_version": "evaluation:v1",
    }


def build(
    *,
    application: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    proposal: dict[str, Any] | None = None,
    created_at: str = CREATED_AT,
) -> dict[str, Any]:
    return build_reward_memory_utility_observation(
        application or application_receipt(),
        outcome or verified_outcome(),
        context or attribution_context(),
        proposal or evaluator_proposal(),
        created_at=created_at,
    )


def dogfood_observation(application: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_content_captured": False,
        "domain_family": "issue_fix",
        "domain_id": "issue_fix.memory_utility_boundary",
        "application_receipt": application,
        "module_outcome": {
            "artifact_ref": application["artifact_ref"],
            "outcome_verified": True,
            "outcome_ref": "effect:test-suite:3214",
            "outcome_status": "succeeded",
            "summary": "Verified focused memory-utility boundary fixture.",
        },
        "cost": {
            "latency_ms": 1,
            "model_tokens": 0,
            "provider_call_count": 1,
        },
        "intervention": {"count": 0, "summary": None},
        "bot_feedback": {"captured": False, "summary": None},
    }


def test_applied_verified_success_is_unknown_when_attribution_is_insufficient() -> None:
    observation = build()

    assert observation["schema_version"] == MEMORY_UTILITY_OBSERVATION_SCHEMA_VERSION
    assert observation["utility_label"] == "unknown"
    assert observation["evidence_basis"] == "insufficient"
    assert observation["attribution_level"] == "set"
    assert observation["outcome_ref"] == verified_outcome()["outcome_ref"]
    assert observation["application_receipt_id"].startswith("rma_")
    assert observation[
        "application_receipt_id"
    ] == reward_memory_application_receipt_id(application_receipt())


def test_applied_memory_can_be_harmful_with_deterministic_evidence() -> None:
    proposal = evaluator_proposal(
        utility_label="harmful",
        attribution_level="item",
        evidence_basis="deterministic_effect",
        evidence_refs=["test-result:regression-3214"],
        confidence=0.98,
    )

    observation = build(proposal=proposal)

    assert observation["utility_label"] == "harmful"
    assert observation["memory_ref_digests"] == [MEMORY_A]
    assert observation["confidence"] == 0.98


def test_multi_memory_attribution_preserves_set_level_credit() -> None:
    application = application_receipt(memories=[MEMORY_A, MEMORY_B])
    proposal = evaluator_proposal(memories=[MEMORY_B, MEMORY_A])

    observation = build(application=application, proposal=proposal)

    assert observation["attribution_level"] == "set"
    assert observation["memory_ref_digests"] == [MEMORY_A, MEMORY_B]


@pytest.mark.parametrize(
    ("level", "memories", "match"),
    [
        ("item", [MEMORY_A, MEMORY_B], "item attribution"),
        ("item", ["1111111111111111"], "item attribution"),
        ("set", [MEMORY_A], "complete application memory set"),
        ("none", [MEMORY_A], "complete application memory set"),
    ],
)
def test_multi_memory_attribution_rejects_copied_or_partial_credit(
    level: str, memories: list[str], match: str
) -> None:
    application = application_receipt(memories=[MEMORY_A, MEMORY_B])
    proposal = evaluator_proposal(memories=memories, attribution_level=level)

    with pytest.raises(ValueError, match=match):
        build(application=application, proposal=proposal)


def test_none_attribution_requires_unknown() -> None:
    proposal = evaluator_proposal(
        utility_label="helpful",
        attribution_level="none",
        evidence_basis="evaluator_inference",
        evidence_refs=["evaluation:one"],
    )

    with pytest.raises(ValueError, match="none attribution"):
        build(proposal=proposal)


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("scope", "agent_id"), "different-agent"),
        (("application_id",), "application:different"),
        (("artifact_ref",), "artifact:different"),
        (("outcome_ref",), "effect:different"),
        (("outcome_status",), "failed"),
        (("retrieval_snapshot_ref",), "retrieval-snapshot:different"),
        (("policy_snapshot_ref",), "policy-snapshot:different"),
    ],
)
def test_evaluator_echo_drift_is_rejected(
    path: tuple[str, ...], replacement: str
) -> None:
    proposal = evaluator_proposal()
    target: dict[str, Any] = proposal
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(ValueError, match="does not match trusted context"):
        build(proposal=proposal)


@pytest.mark.parametrize("scope_field", ["corpus_id", "surface_id"])
def test_trusted_scope_must_match_application_receipt(scope_field: str) -> None:
    context = attribution_context()
    context["scope"][scope_field] = "different-scope"
    proposal = evaluator_proposal()
    proposal["scope"] = dict(context["scope"])

    with pytest.raises(ValueError, match=scope_field):
        build(context=context, proposal=proposal)


@pytest.mark.parametrize(
    "snapshot_field", ["retrieval_snapshot_ref", "policy_snapshot_ref"]
)
def test_trusted_snapshot_must_match_application_receipt_when_present(
    snapshot_field: str,
) -> None:
    application = application_receipt()
    application[snapshot_field] = "snapshot:trusted"
    context = attribution_context()
    context[snapshot_field] = "snapshot:stale"
    proposal = evaluator_proposal()
    proposal[snapshot_field] = context[snapshot_field]

    with pytest.raises(ValueError, match=snapshot_field):
        build(application=application, context=context, proposal=proposal)


def test_verified_outcome_must_be_verified_and_match_artifact() -> None:
    unverified = verified_outcome()
    unverified["verified"] = False
    with pytest.raises(ValueError, match="verified.*true"):
        build(outcome=unverified)

    mismatched = verified_outcome()
    mismatched["artifact_ref"] = "artifact:different"
    proposal = evaluator_proposal()
    proposal["artifact_ref"] = mismatched["artifact_ref"]
    with pytest.raises(ValueError, match="artifact_ref must match"):
        build(outcome=mismatched, proposal=proposal)


def test_observation_id_is_retry_stable_and_version_or_evidence_sensitive() -> None:
    proposal = evaluator_proposal(
        utility_label="helpful",
        evidence_basis="evaluator_inference",
        evidence_refs=["evaluation:evidence-a"],
        confidence=0.7,
    )
    first = build(proposal=proposal)
    retried = build(proposal=proposal, created_at="2026-08-15T00:01:00Z")

    assert first["observation_id"] == retried["observation_id"]
    assert first["created_at"] != retried["created_at"]

    new_version = deepcopy(proposal)
    new_version["evaluation_version"] = "evaluation:v2"
    new_evidence = deepcopy(proposal)
    new_evidence["evidence_refs"] = ["evaluation:evidence-b"]
    assert build(proposal=new_version)["observation_id"] != first["observation_id"]
    assert build(proposal=new_evidence)["observation_id"] != first["observation_id"]


def test_observation_id_is_an_evaluation_key_not_judgment_content() -> None:
    proposal = evaluator_proposal(
        utility_label="helpful",
        evidence_basis="deterministic_effect",
        evidence_refs=["test-result:3214"],
        confidence=0.9,
    )
    first = build(proposal=proposal)
    changed_judgment = deepcopy(proposal)
    changed_judgment["utility_label"] = "harmful"
    changed_judgment["confidence"] = 0.2
    changed_judgment["reason_codes"] = ["same-evaluation-key-conflict"]

    second = build(
        proposal=changed_judgment,
        created_at="2026-08-16T00:00:00+00:00",
    )

    assert second["observation_id"] == first["observation_id"]


def test_full_application_receipt_digest_participates_in_identity() -> None:
    first = build()
    changed_receipt = application_receipt()
    changed_receipt["reasoning_summary"] = "Applied the same guidance after review."

    second = build(application=changed_receipt)

    assert second["application_receipt_id"] != first["application_receipt_id"]
    assert second["observation_id"] != first["observation_id"]


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("missing_query_evidence", "missing=.*query_evidence"),
        ("unknown_provider_field", "unknown=.*provider_uri"),
        ("unpreserved_reasoning", "model_reasoning_preserved must be true"),
    ],
)
def test_application_receipt_identity_requires_a_complete_trusted_envelope(
    mutation: str,
    match: str,
) -> None:
    application = application_receipt()
    if mutation == "missing_query_evidence":
        del application["query_evidence"]
    elif mutation == "unknown_provider_field":
        application["provider_uri"] = "viking://private/exact-provider-reference"
    else:
        application["model_reasoning_preserved"] = False

    with pytest.raises(ValueError, match=match):
        reward_memory_application_receipt_id(application)


def test_validator_rejects_tampered_observation_id() -> None:
    observation = build()
    observation["observation_id"] = "muo_" + "0" * 64

    with pytest.raises(ValueError, match="canonical identity"):
        validate_reward_memory_utility_observation(
            observation,
            application_receipt=application_receipt(),
            verified_outcome=verified_outcome(),
            attribution_context=attribution_context(),
        )


@pytest.mark.parametrize(
    "field",
    [
        "raw_memory",
        "transcript",
        "provider_uri",
        "local_path",
        "writeback",
        "lifecycle",
    ],
)
def test_evaluator_proposal_rejects_unknown_private_or_authority_fields(
    field: str,
) -> None:
    proposal = evaluator_proposal()
    proposal[field] = "not-accepted"

    with pytest.raises(ValueError, match="unknown"):
        build(proposal=proposal)


@pytest.mark.parametrize(
    ("target", "unsafe_ref"),
    [
        ("evidence", "/Users/example/private-result.json"),
        ("evidence", "file:///tmp/private-result.json"),
        ("evidence", "viking://resources/private/memory.json"),
        ("retrieval", "/private/tmp/retrieval.json"),
        ("policy", "https://provider.invalid/policy/private"),
        ("scope", "C:\\Users\\example\\project"),
    ],
)
def test_public_observation_refs_reject_local_paths_and_provider_uris(
    target: str, unsafe_ref: str
) -> None:
    context = attribution_context()
    proposal = evaluator_proposal()
    if target == "evidence":
        proposal["evidence_refs"] = [unsafe_ref]
    elif target == "retrieval":
        context["retrieval_snapshot_ref"] = unsafe_ref
        proposal["retrieval_snapshot_ref"] = unsafe_ref
    elif target == "policy":
        context["policy_snapshot_ref"] = unsafe_ref
        proposal["policy_snapshot_ref"] = unsafe_ref
    else:
        context["scope"]["project_id"] = unsafe_ref
        proposal["scope"]["project_id"] = unsafe_ref

    with pytest.raises(ValueError, match="opaque public-safe reference"):
        build(context=context, proposal=proposal)


def test_application_receipt_rejects_false_boundaries() -> None:
    authority_receipt = application_receipt()
    authority_receipt["grants_new_action_authority"] = True
    with pytest.raises(ValueError, match="must be false"):
        build(application=authority_receipt)


@pytest.mark.parametrize(
    "memory_ref",
    [
        "provider-private-ref",
        "ABCDEF0123456789",
        "sha256:not-a-digest",
    ],
)
def test_memory_references_must_remain_canonical_opaque_digests(
    memory_ref: str,
) -> None:
    application = application_receipt(memories=[memory_ref])
    proposal = evaluator_proposal(memories=[memory_ref])

    with pytest.raises(ValueError, match="canonical opaque memory digests"):
        build(application=application, proposal=proposal)


@pytest.mark.parametrize(
    "memory_ref",
    [
        "viking://private/exact-provider-reference",
        "/Users/example/private-memory.json",
        "ABCDEF0123456789",
    ],
)
def test_dogfood_builder_rejects_noncanonical_memory_references(
    memory_ref: str,
) -> None:
    application = application_receipt(memories=[memory_ref])

    with pytest.raises(ValueError, match="memory_ref_digests"):
        build_reward_memory_dogfood_receipt(dogfood_observation(application))


@pytest.mark.parametrize(
    "memory_ref",
    [
        "viking://private/exact-provider-reference",
        "/Users/example/private-memory.json",
        "ABCDEF0123456789",
    ],
)
def test_dogfood_batch_rejects_noncanonical_memory_references(
    memory_ref: str,
) -> None:
    receipt = build_reward_memory_dogfood_receipt(
        dogfood_observation(application_receipt())
    )
    receipt["memory_ref_digests"] = [memory_ref]

    with pytest.raises(ValueError, match="memory_ref_digests"):
        build_reward_memory_dogfood_batch([receipt], [], evaluation={})


def test_observation_is_opaque_and_cannot_grant_authority_or_write() -> None:
    observation = build()
    for key in (
        "grants_new_action_authority",
        "provider_write_performed",
        "external_writes_performed",
        "raw_content_captured",
    ):
        assert observation[key] is False

    assert validate_reward_memory_utility_observation(observation) == observation
    unknown = dict(observation)
    unknown["transcript"] = "not accepted"
    with pytest.raises(ValueError, match="unknown"):
        validate_reward_memory_utility_observation(unknown)


def test_non_unknown_utility_requires_evidence_and_rejects_duplicate_refs() -> None:
    missing_evidence = evaluator_proposal(
        utility_label="helpful",
        evidence_basis="evaluator_inference",
    )
    with pytest.raises(ValueError, match="requires evidence_refs"):
        build(proposal=missing_evidence)

    duplicate = evaluator_proposal()
    duplicate["reason_codes"] = ["reason:a", "reason:a"]
    with pytest.raises(ValueError, match="duplicates"):
        build(proposal=duplicate)


@pytest.mark.parametrize(
    "evidence_basis",
    ["owner_correction", "controlled_replay", "deterministic_effect"],
)
def test_strong_evidence_basis_requires_a_reference_even_for_unknown(
    evidence_basis: str,
) -> None:
    proposal = evaluator_proposal(evidence_basis=evidence_basis)

    with pytest.raises(ValueError, match="strong evidence basis"):
        build(proposal=proposal)

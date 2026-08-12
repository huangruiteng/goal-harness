#!/usr/bin/env python3
"""Contributor-facing walkthrough: Decision Context → Material Lifecycle rerank.

Covers the shipped pipeline from revision-bound evidence through owner-gated
material rerank:

1. **Source manifest** — provider sources declare exact-read policies; private
   locators are stripped from public-safe output
2. **Evidence packet** — changed facts, recalled/stale claims, and conflicts
   are all visible; source bodies and private locators stay absent
3. **Decision proposal** — evidence drives a scored, confidence-bound proposal
4. **Outcome receipt** — verified decisions produce ``reward_memory_candidate_eligible``
   receipts; conflicting and invalidated assumptions remain visible
5. **Outcome feedback** — audited telemetry bridge from Decision Context into
   Reward Memory; candidate creation requires exact-read-verified claims, a
   verified outcome, no unresolved conflicts, and current source revisions
6. **Material inventory** — ``raw_content_captured`` is False; stable ids and
   backups are verified without exposing private bodies
7. **Material rerank** — a rerank proposal references decision evidence;
   moves carry reason codes; source bodies stay absent
8. **Owner-gated apply** — the rerank apply receipt requires an owner gate ref
   and validation ref; cursor commits remain separate actions
9. **Lifecycle transition** — state changes are receipted with transition
   authority refs; raw content is never captured

No provider calls, draft bodies, credentials, private locators, or publish
authority.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.decision_context import (  # noqa: E402
    DecisionSourceSpec,
    build_decision_context_architecture_packet,
    build_decision_evidence_packet,
    build_decision_outcome_receipt,
    build_decision_proposal,
    build_decision_source_manifest,
)
from loopx.capabilities.decision_context.outcome_feedback import (  # noqa: E402
    build_decision_outcome_feedback,
)
from loopx.capabilities.material_lifecycle import (  # noqa: E402
    build_material_lifecycle_architecture_packet,
    build_material_lifecycle_receipt,
    build_material_rerank_apply_receipt,
    build_material_rerank_proposal,
    build_material_store_inventory,
)

OBSERVED_AT = "2026-08-01T12:00:00+00:00"
REVIEW_AT = "2026-08-03T12:00:00+00:00"
RECORDED_AT = "2026-08-05T12:00:00+00:00"

FORBIDDEN = [
    "/" + "Users/", "/" + "private/", "/" + "tmp/",
    "http" + "://", "https" + "://",
    "api" + "_key", "pass" + "word", "sec" + "ret",
    "C:\\", "C:/",
]


def _assert_public_safe(payload: Any, *, label: str = "") -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [n for n in FORBIDDEN if n.lower() in text.lower()]
    assert not leaked, f"{label}: public-boundary leak: {leaked}"


# ── Scenario 1: Decision Context architecture is default-off, no authority ──

def test_decision_context_architecture_boundary() -> None:
    """Decision Context is default-off, creates no authority, and fails open."""
    arch = build_decision_context_architecture_packet()
    assert arch["capability"]["default_enabled"] is False
    assert arch["capability"]["creates_authority"] is False
    assert arch["provider_boundaries"]["provider_failure_policy"] == (
        "fail_open_to_current_authority"
    )
    _assert_public_safe(arch, label="dc-arch")


# ── Scenario 2: Source manifest strips private locators ──

def test_source_manifest_strips_private_locators() -> None:
    """The public-safe source manifest declares ``private_locators_captured: False``
    and never leaks the private locator value, even when the source spec includes it."""
    source = DecisionSourceSpec(
        source_id="source:repository:adoption-signals",
        provider_id="repository-provider",
        source_kind="repository",
        priority="p0",
        evidence_level="s1",
        objectives=("adoption", "stability"),
        scan_mode="incremental",
        exact_read_policy="material_change",
        freshness_seconds=3600,
        private_locator="private-repo-locator-value",
    )
    manifest = build_decision_source_manifest(
        goal_id="goal:dc-ml-walkthrough",
        observed_at=OBSERVED_AT,
        sources=[source],
    )
    serialized = json.dumps(manifest, sort_keys=True)
    # Private locator value must not leak.
    assert "private-repo-locator-value" not in serialized, (
        "source manifest must not leak private locator value"
    )
    # The manifest declares the boundary was respected.
    assert manifest.get("private_locators_captured") is False, (
        "manifest must declare private_locators_captured=False"
    )
    _assert_public_safe(manifest, label="source-manifest")


# ── Scenario 3: Evidence packet keeps stale/conflicting claims visible ──

def test_evidence_packet_keeps_stale_and_conflicts_visible() -> None:
    """Stale claims and unresolved conflicts remain visible in the evidence
    packet — they are never silently dropped.  Source bodies stay absent."""
    evidence = build_decision_evidence_packet(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:adoption-rate",
                "summary": "Monthly adoption rate increased from 12% to 18%.",
                "source_ref": "source:repository:adoption-signals",
                "observed_at": OBSERVED_AT,
            },
        ],
        recalled_claims=[
            {
                "claim_id": "claim:promote-knn-optimization",
                "summary": "KNN optimization candidate is the top-ranked material.",
                "provider_ref": "provider:repository",
                "source_ref": "source:repository:adoption-signals",
                "source_revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "exact_read_verified": True,
            },
        ],
        stale_or_rejected_claims=[
            {
                "claim_id": "claim:retire-old-benchmark",
                "summary": "Legacy benchmark no longer contributes to current objectives.",
                "observed_at": OBSERVED_AT,
                "reason_code": "insufficient_evidence",
            },
        ],
        conflicts=[
            {
                "conflict_id": "conflict:rank-disagreement",
                "summary": "Two providers disagree on material rank #1.",
                "source_refs": ["source:repository", "source:benchmark"],
                "conflict_rule": "single_material_rank",
                "status": "unresolved",
            },
        ],
        source_revisions=[
            {
                "source_ref": "source:repository:adoption-signals",
                "revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            },
        ],
        provider_health=[
            {
                "provider": "repository-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            },
        ],
    )
    # Stale claims are visible with reason codes.
    assert len(evidence["stale_or_rejected_claims"]) == 1
    assert evidence["stale_or_rejected_claims"][0]["reason_code"] == "insufficient_evidence"
    # Conflicts are visible.
    assert len(evidence["conflicts"]) == 1
    assert evidence["conflicts"][0]["status"] == "unresolved"
    # Source bodies absent.
    assert evidence.get("source_bodies") is None
    assert evidence.get("raw_context_captured") is False
    _assert_public_safe(evidence, label="evidence")


# ── Scenario 4: Decision proposal carries evidence ref and confidence ──

def test_decision_proposal_links_evidence() -> None:
    """A decision proposal must reference its evidence packet and carry
    scored objectives with rationale — never raw source bodies."""
    evidence = build_decision_evidence_packet(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:adoption-rate",
                "summary": "Monthly adoption rate increased.",
                "source_ref": "source:repository:adoption-signals",
                "observed_at": OBSERVED_AT,
            },
        ],
        recalled_claims=[],
        stale_or_rejected_claims=[],
        conflicts=[],
        source_revisions=[
            {
                "source_ref": "source:repository:adoption-signals",
                "revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            },
        ],
        provider_health=[
            {
                "provider": "repository-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            },
        ],
    )
    proposal = build_decision_proposal(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        evidence_packet_ref=str(evidence["packet_ref"]),
        observed_at=OBSERVED_AT,
        review_at=REVIEW_AT,
        objective_scores=[
            {
                "objective_id": "objective:adoption",
                "score": 0.82,
                "rationale": "Adoption rate is trending upward with current material ranking.",
            },
        ],
        recommended_decision={
            "option_id": "option:keep-current-ranking",
            "summary": "Keep the current material ranking; no rerank needed.",
            "rationale": "Current evidence supports the existing ranking order.",
            "confidence": 0.82,
        },
    )
    assert "evidence_packet_ref" in proposal
    assert proposal["evidence_packet_ref"] == evidence["packet_ref"]
    assert len(proposal["objective_scores"]) == 1
    assert proposal["objective_scores"][0]["score"] == 0.82
    _assert_public_safe(proposal, label="proposal")


# ── Scenario 5: Outcome receipt declares reward memory eligibility ──

def test_outcome_receipt_declares_candidate_eligibility() -> None:
    """A verified outcome receipt declares whether it is eligible for Reward
    Memory candidate creation.  Mutates_core_state is always False."""
    evidence = build_decision_evidence_packet(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:adoption-rate",
                "summary": "Monthly adoption rate increased.",
                "source_ref": "source:repository:adoption-signals",
                "observed_at": OBSERVED_AT,
            },
        ],
        recalled_claims=[
            {
                "claim_id": "claim:promote-knn",
                "summary": "KNN optimization candidate is the top-ranked material.",
                "provider_ref": "provider:repository",
                "source_ref": "source:repository:adoption-signals",
                "source_revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "exact_read_verified": True,
            },
        ],
        stale_or_rejected_claims=[],
        conflicts=[],
        source_revisions=[
            {
                "source_ref": "source:repository:adoption-signals",
                "revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            },
        ],
        provider_health=[
            {
                "provider": "repository-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            },
        ],
    )
    proposal = build_decision_proposal(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        evidence_packet_ref=str(evidence["packet_ref"]),
        observed_at=OBSERVED_AT,
        review_at=REVIEW_AT,
        objective_scores=[
            {
                "objective_id": "objective:adoption",
                "score": 0.82,
                "rationale": "Adoption rate trending upward.",
            },
        ],
        recommended_decision={
            "option_id": "option:close-pilot",
            "summary": "Close the pilot before expanding the protocol.",
            "rationale": "Verified adoption compounds more than another surface.",
            "confidence": 0.82,
        },
    )
    outcome = build_decision_outcome_receipt(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        proposal_packet_ref=str(proposal["packet_ref"]),
        recorded_at=RECORDED_AT,
        review_at=REVIEW_AT,
        verification_status="verified",
        accepted_decision={
            "option_id": "option:close-pilot",
            "summary": "Close the pilot before expanding the protocol.",
            "accepted_by": "owner:goal",
            "accepted_at": OBSERVED_AT,
        },
        observed_outcomes=[
            {
                "outcome_id": "outcome:pilot-closed",
                "summary": "Pilot was closed and verified.",
                "evidence_ref": evidence["packet_ref"],
                "status": "verified",
                "observed_at": REVIEW_AT,
            },
        ],
    )
    assert outcome["reward_memory_candidate_eligible"] is True
    assert outcome["capability"]["mutates_core_state"] is False
    _assert_public_safe(outcome, label="outcome")


# ── Scenario 6: Outcome feedback bridge — eligible candidate ──

def test_outcome_feedback_creates_candidate_when_eligible() -> None:
    """When all conditions are met (exact-read-verified claim, verified outcome,
    no unresolved conflicts, current source revision), the outcome feedback
    bridge creates a Reward Memory candidate.  The bridge never ingests or
    activates automatically."""
    evidence = build_decision_evidence_packet(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:adoption-rate",
                "summary": "Monthly adoption rate increased.",
                "source_ref": "source:repository:adoption-signals",
                "observed_at": OBSERVED_AT,
            },
        ],
        recalled_claims=[
            {
                "claim_id": "claim:promote-knn",
                "summary": "KNN optimization is top-ranked.",
                "provider_ref": "provider:repository",
                "source_ref": "source:repository:adoption-signals",
                "source_revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "exact_read_verified": True,
            },
        ],
        stale_or_rejected_claims=[],
        conflicts=[],
        source_revisions=[
            {
                "source_ref": "source:repository:adoption-signals",
                "revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            },
        ],
        provider_health=[
            {
                "provider": "repository-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            },
        ],
    )
    proposal = build_decision_proposal(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        evidence_packet_ref=str(evidence["packet_ref"]),
        observed_at=OBSERVED_AT,
        review_at=REVIEW_AT,
        objective_scores=[
            {
                "objective_id": "objective:adoption",
                "score": 0.82,
                "rationale": "Adoption rate trending upward.",
            },
        ],
        recommended_decision={
            "option_id": "option:close-pilot",
            "summary": "Close the pilot.",
            "rationale": "Verified adoption compounds.",
            "confidence": 0.82,
        },
    )
    outcome = build_decision_outcome_receipt(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        proposal_packet_ref=str(proposal["packet_ref"]),
        recorded_at=RECORDED_AT,
        review_at=REVIEW_AT,
        verification_status="verified",
        accepted_decision={
            "option_id": "option:close-pilot",
            "summary": "Close the pilot.",
            "accepted_by": "owner:goal",
            "accepted_at": OBSERVED_AT,
        },
        observed_outcomes=[
            {
                "outcome_id": "outcome:pilot-closed",
                "summary": "Pilot was closed and verified.",
                "evidence_ref": evidence["packet_ref"],
                "status": "verified",
                "observed_at": REVIEW_AT,
            },
        ],
    )

    feedback = build_decision_outcome_feedback(
        evidence_packet=evidence,
        outcome_receipt=outcome,
        workspace_ref="workspace:dc-ml-walkthrough",
        project_ref="project:loopx-contributor",
    )
    assert feedback["reward_memory"]["candidate_created"] is True
    assert feedback["reward_memory"]["candidate_status"] == "review_ready"
    assert feedback["reward_memory"]["candidate_ref"] is not None
    assert feedback["reward_memory"]["ineligible_reason_codes"] == []
    # Bridge never ingests or activates automatically.
    assert feedback["reward_memory"]["automatic_ingest_performed"] is False
    assert feedback["reward_memory"]["automatic_activation_performed"] is False
    # Raw content and credentials never captured.
    assert feedback.get("raw_context_captured") is False
    assert feedback.get("credentials_captured") is False
    assert feedback.get("private_locators_captured") is False
    _assert_public_safe(feedback, label="outcome-feedback")


# ── Scenario 7: Outcome feedback — ineligible with unresolved conflicts ──

def test_outcome_feedback_ineligible_with_conflicts() -> None:
    """When the evidence packet has unresolved conflicts, the outcome feedback
    must report ineligible reason codes — not silently skip candidate creation."""
    evidence = build_decision_evidence_packet(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:adoption-rate",
                "summary": "Monthly adoption rate increased.",
                "source_ref": "source:repository:adoption-signals",
                "observed_at": OBSERVED_AT,
            },
        ],
        recalled_claims=[
            {
                "claim_id": "claim:promote-knn",
                "summary": "KNN optimization is top-ranked.",
                "provider_ref": "provider:repository",
                "source_ref": "source:repository:adoption-signals",
                "source_revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "exact_read_verified": True,
            },
        ],
        stale_or_rejected_claims=[],
        conflicts=[
            {
                "conflict_id": "conflict:rank-disagreement",
                "summary": "Two providers disagree on material rank #1.",
                "source_refs": ["source:repository", "source:benchmark"],
                "conflict_rule": "single_material_rank",
                "status": "unresolved",
            },
        ],
        source_revisions=[
            {
                "source_ref": "source:repository:adoption-signals",
                "revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            },
        ],
        provider_health=[
            {
                "provider": "repository-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            },
        ],
    )
    proposal = build_decision_proposal(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        evidence_packet_ref=str(evidence["packet_ref"]),
        observed_at=OBSERVED_AT,
        review_at=REVIEW_AT,
        objective_scores=[
            {
                "objective_id": "objective:adoption",
                "score": 0.82,
                "rationale": "Adoption rate trending upward.",
            },
        ],
        recommended_decision={
            "option_id": "option:close-pilot",
            "summary": "Close the pilot.",
            "rationale": "Verified adoption compounds.",
            "confidence": 0.82,
        },
    )
    outcome = build_decision_outcome_receipt(
        goal_id="goal:dc-ml-walkthrough",
        decision_id="decision:adoption-priority",
        proposal_packet_ref=str(proposal["packet_ref"]),
        recorded_at=RECORDED_AT,
        review_at=REVIEW_AT,
        verification_status="verified",
        accepted_decision={
            "option_id": "option:close-pilot",
            "summary": "Close the pilot.",
            "accepted_by": "owner:goal",
            "accepted_at": OBSERVED_AT,
        },
        observed_outcomes=[
            {
                "outcome_id": "outcome:pilot-closed",
                "summary": "Pilot was closed and verified.",
                "evidence_ref": evidence["packet_ref"],
                "status": "verified",
                "observed_at": REVIEW_AT,
            },
        ],
    )

    feedback = build_decision_outcome_feedback(
        evidence_packet=evidence,
        outcome_receipt=outcome,
        workspace_ref="workspace:dc-ml-walkthrough",
        project_ref="project:loopx-contributor",
    )
    assert feedback["reward_memory"]["candidate_created"] is False
    assert "unresolved_authority_conflict" in feedback["reward_memory"]["ineligible_reason_codes"]
    _assert_public_safe(feedback, label="outcome-feedback-ineligible")


# ── Scenario 8: Material Lifecycle architecture is default-off ──

def test_material_lifecycle_architecture_boundary() -> None:
    """Material Lifecycle is default-off; the raw material store is a private
    external authority — never inside LoopX state."""
    arch = build_material_lifecycle_architecture_packet()
    assert arch["capability"]["default_enabled"] is False
    assert arch["provider_boundaries"]["raw_material_store"] == (
        "private_external_authority"
    )
    _assert_public_safe(arch, label="ml-arch")


# ── Scenario 9: Material inventory never captures raw content ──

def test_material_inventory_raw_content_absent() -> None:
    """The store inventory declares ``raw_content_captured: False`` and
    verifies stable ids and backups without exposing private bodies."""
    inventory = build_material_store_inventory(
        goal_id="goal:dc-ml-walkthrough",
        store_id="store:materials",
        store_revision="revision:3",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:3",
        backup_ref="backup:3",
        source_digest="sha256:abcdef0123456789",
        lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
        stable_ids_verified=True,
        backup_verified=True,
    )
    assert inventory["raw_content_captured"] is False
    assert inventory["stable_ids_verified"] is True
    assert inventory["backup_verified"] is True
    # Inventory must not leak source bodies.
    serialized = json.dumps(inventory, sort_keys=True)
    assert "private material body" not in serialized
    _assert_public_safe(inventory, label="inventory")


# ── Scenario 10: Rerank proposal references decision evidence ──

def test_rerank_proposal_references_decision_evidence() -> None:
    """A material rerank proposal references decision evidence and carries
    bounded moves with reason codes.  Raw content is never captured."""
    inventory = build_material_store_inventory(
        goal_id="goal:dc-ml-walkthrough",
        store_id="store:materials",
        store_revision="revision:3",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:3",
        backup_ref="backup:3",
        source_digest="sha256:abcdef0123456789",
        lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
        stable_ids_verified=True,
        backup_verified=True,
    )
    proposal = build_material_rerank_proposal(
        goal_id="goal:dc-ml-walkthrough",
        proposal_id="proposal:rerank-after-adoption-review",
        inventory_ref=str(inventory["inventory_ref"]),
        decision_evidence_ref="decision-evidence-abc123",
        observed_at=OBSERVED_AT,
        target_window_size=10,
        max_moved_items=2,
        max_rank_displacement=4,
        moves=[
            {
                "material_ref": "material:2",
                "from_rank": 5,
                "to_rank": 1,
                "reason_code": "current_objective_fit",
            },
        ],
    )
    assert proposal["raw_content_captured"] is False
    assert proposal["decision_evidence_ref"] == "decision-evidence-abc123"
    assert len(proposal["moves"]) == 1
    assert proposal["moves"][0]["reason_code"] == "current_objective_fit"
    # Bounds are inside the constraints block.
    constraints = proposal["constraints"]
    assert constraints["max_moved_items"] == 2
    assert constraints["max_rank_displacement"] == 4
    _assert_public_safe(proposal, label="rerank-proposal")


# ── Scenario 11: Owner-gated rerank apply receipt ──

def test_rerank_apply_is_owner_gated() -> None:
    """The rerank apply receipt requires an owner gate ref and validation ref.
    Cursor commits remain separate owner-gated actions — the apply receipt
    does not commit cursors."""
    inventory = build_material_store_inventory(
        goal_id="goal:dc-ml-walkthrough",
        store_id="store:materials",
        store_revision="revision:3",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:3",
        backup_ref="backup:3",
        source_digest="sha256:abcdef0123456789",
        lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
        stable_ids_verified=True,
        backup_verified=True,
    )
    proposal = build_material_rerank_proposal(
        goal_id="goal:dc-ml-walkthrough",
        proposal_id="proposal:rerank-after-adoption-review",
        inventory_ref=str(inventory["inventory_ref"]),
        decision_evidence_ref="decision-evidence-abc123",
        observed_at=OBSERVED_AT,
        target_window_size=10,
        max_moved_items=2,
        max_rank_displacement=4,
        moves=[
            {
                "material_ref": "material:2",
                "from_rank": 5,
                "to_rank": 1,
                "reason_code": "current_objective_fit",
            },
        ],
    )
    apply_receipt = build_material_rerank_apply_receipt(
        goal_id="goal:dc-ml-walkthrough",
        receipt_id="receipt:rerank-1",
        proposal_ref=str(proposal["proposal_ref"]),
        observed_at=OBSERVED_AT,
        status="applied",
        before_revision="revision:3",
        after_revision="revision:4",
        owner_gate_ref="gate:owner-approval-rerank-1",
        validation_ref="validation:rerank-1",
        applied_material_refs=["material:2"],
        rollback_ref="rollback:revision-3",
    )
    assert apply_receipt["raw_content_captured"] is False
    assert apply_receipt["owner_gate_ref"] == "gate:owner-approval-rerank-1"
    assert apply_receipt["validation_ref"] == "validation:rerank-1"
    # Cursor commit is a separate action — apply receipt must not include cursor references.
    assert "cursor_commit_ref" not in apply_receipt
    _assert_public_safe(apply_receipt, label="rerank-apply")


# ── Scenario 12: Lifecycle receipt preserves transition authority ──

def test_lifecycle_receipt_preserves_transition_authority() -> None:
    """Every lifecycle state transition carries a transition authority ref
    (typically a decision outcome) and never captures raw content."""
    receipt = build_material_lifecycle_receipt(
        goal_id="goal:dc-ml-walkthrough",
        receipt_id="receipt:archive-material-5",
        material_ref="material:5",
        from_state="active",
        to_state="archived",
        observed_at=OBSERVED_AT,
        source_ref="source:repository:adoption-signals",
        source_revision="revision:3",
        transition_authority_ref="decision-outcome:archive-material-5",
        archive_ref="archive:material-5",
    )
    assert receipt["raw_content_captured"] is False
    assert receipt["transition_authority_ref"] == "decision-outcome:archive-material-5"
    assert receipt["from_state"] == "active"
    assert receipt["to_state"] == "archived"
    _assert_public_safe(receipt, label="lifecycle-receipt")


# ── Scenario 13: Full pipeline — Decision Context → Material rerank ──

def test_full_pipeline_decision_to_rerank() -> None:
    """End-to-end narrative: evidence is collected → a decision is proposed
    and verified → outcome feedback is generated → material inventory is
    checked → a rerank is proposed and applied under an owner gate."""
    goal_id = "goal:dc-ml-walkthrough"

    # Step 1: Source manifest (strips private locators).
    source = DecisionSourceSpec(
        source_id="source:repository:adoption-signals",
        provider_id="repository-provider",
        source_kind="repository",
        priority="p0",
        evidence_level="s1",
        objectives=("adoption", "stability"),
        scan_mode="incremental",
        exact_read_policy="material_change",
        freshness_seconds=3600,
        private_locator="private-repo-locator",
    )
    manifest = build_decision_source_manifest(
        goal_id=goal_id, observed_at=OBSERVED_AT, sources=[source],
    )
    assert "private-repo-locator" not in json.dumps(manifest)

    # Step 2: Evidence packet (stale claims visible, conflicts visible).
    evidence = build_decision_evidence_packet(
        goal_id=goal_id, decision_id="decision:full-pipeline",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:pipeline",
                "summary": "Pipeline fact.",
                "source_ref": "source:repository:adoption-signals",
                "observed_at": OBSERVED_AT,
            },
        ],
        recalled_claims=[
            {
                "claim_id": "claim:pipeline",
                "summary": "Pipeline claim.",
                "provider_ref": "provider:repository",
                "source_ref": "source:repository:adoption-signals",
                "source_revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "exact_read_verified": True,
            },
        ],
        stale_or_rejected_claims=[],
        conflicts=[],
        source_revisions=[
            {
                "source_ref": "source:repository:adoption-signals",
                "revision": "revision:3",
                "observed_at": OBSERVED_AT,
                "freshness": "current",
            },
        ],
        provider_health=[
            {
                "provider": "repository-provider",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            },
        ],
    )

    # Step 3: Proposal.
    proposal = build_decision_proposal(
        goal_id=goal_id, decision_id="decision:full-pipeline",
        evidence_packet_ref=str(evidence["packet_ref"]),
        observed_at=OBSERVED_AT, review_at=REVIEW_AT,
        objective_scores=[
            {
                "objective_id": "objective:adoption",
                "score": 0.85,
                "rationale": "Evidence supports a rank adjustment.",
            },
        ],
        recommended_decision={
            "option_id": "option:rerank-materials",
            "summary": "Rerank materials based on latest adoption signals.",
            "rationale": "Current evidence suggests material #2 should be #1.",
            "confidence": 0.85,
        },
    )

    # Step 4: Verified outcome.
    outcome = build_decision_outcome_receipt(
        goal_id=goal_id, decision_id="decision:full-pipeline",
        proposal_packet_ref=str(proposal["packet_ref"]),
        recorded_at=RECORDED_AT, review_at=REVIEW_AT,
        verification_status="verified",
        accepted_decision={
            "option_id": "option:rerank-materials",
            "summary": "Rerank materials based on latest adoption signals.",
            "accepted_by": "owner:goal",
            "accepted_at": OBSERVED_AT,
        },
        observed_outcomes=[
            {
                "outcome_id": "outcome:pipeline",
                "summary": "Verified pipeline outcome.",
                "evidence_ref": evidence["packet_ref"],
                "status": "verified",
                "observed_at": REVIEW_AT,
            },
        ],
    )
    assert outcome["reward_memory_candidate_eligible"] is True

    # Step 5: Outcome feedback bridge.
    feedback = build_decision_outcome_feedback(
        evidence_packet=evidence, outcome_receipt=outcome,
        workspace_ref="workspace:pipeline", project_ref="project:loopx",
    )
    assert feedback["reward_memory"]["candidate_created"] is True
    assert feedback["reward_memory"]["automatic_ingest_performed"] is False

    # Step 6: Material inventory.
    inventory = build_material_store_inventory(
        goal_id=goal_id, store_id="store:materials",
        store_revision="revision:3", observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:3", backup_ref="backup:3",
        source_digest="sha256:abcdef0123456789",
        lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
        stable_ids_verified=True, backup_verified=True,
    )
    assert inventory["raw_content_captured"] is False

    # Step 7: Rerank proposal (references decision evidence).
    rerank = build_material_rerank_proposal(
        goal_id=goal_id, proposal_id="proposal:pipeline-rerank",
        inventory_ref=str(inventory["inventory_ref"]),
        decision_evidence_ref=str(evidence["packet_ref"]),
        observed_at=OBSERVED_AT, target_window_size=10,
        max_moved_items=2, max_rank_displacement=4,
        moves=[
            {
                "material_ref": "material:2",
                "from_rank": 5, "to_rank": 1,
                "reason_code": "current_objective_fit",
            },
        ],
    )
    assert rerank["raw_content_captured"] is False
    assert rerank["decision_evidence_ref"] == evidence["packet_ref"]

    # Step 8: Owner-gated apply.
    apply_receipt = build_material_rerank_apply_receipt(
        goal_id=goal_id, receipt_id="receipt:pipeline-rerank",
        proposal_ref=str(rerank["proposal_ref"]),
        observed_at=OBSERVED_AT, status="applied",
        before_revision="revision:3", after_revision="revision:4",
        owner_gate_ref="gate:owner-approval-pipeline",
        validation_ref="validation:pipeline",
        applied_material_refs=["material:2"],
        rollback_ref="rollback:revision-3",
    )
    assert apply_receipt["owner_gate_ref"] is not None
    assert apply_receipt["validation_ref"] is not None
    assert apply_receipt["raw_content_captured"] is False

    # Every payload public-safe.
    for label, payload in [
        ("pipeline-manifest", manifest),
        ("pipeline-evidence", evidence),
        ("pipeline-proposal", proposal),
        ("pipeline-outcome", outcome),
        ("pipeline-feedback", feedback),
        ("pipeline-inventory", inventory),
        ("pipeline-rerank", rerank),
        ("pipeline-apply", apply_receipt),
    ]:
        _assert_public_safe(payload, label=label)


def main() -> int:
    tests = [
        ("dc architecture boundary", test_decision_context_architecture_boundary),
        ("source manifest strips private locators", test_source_manifest_strips_private_locators),
        ("evidence keeps stale/conflicts visible", test_evidence_packet_keeps_stale_and_conflicts_visible),
        ("proposal links evidence with confidence", test_decision_proposal_links_evidence),
        ("outcome receipt declares eligibility", test_outcome_receipt_declares_candidate_eligibility),
        ("outcome feedback creates eligible candidate", test_outcome_feedback_creates_candidate_when_eligible),
        ("outcome feedback ineligible with conflicts", test_outcome_feedback_ineligible_with_conflicts),
        ("ml architecture boundary", test_material_lifecycle_architecture_boundary),
        ("inventory raw content absent", test_material_inventory_raw_content_absent),
        ("rerank proposal references decision evidence", test_rerank_proposal_references_decision_evidence),
        ("rerank apply is owner-gated", test_rerank_apply_is_owner_gated),
        ("lifecycle receipt preserves transition authority", test_lifecycle_receipt_preserves_transition_authority),
        ("full pipeline decision-to-rerank", test_full_pipeline_decision_to_rerank),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("decision-context-material-lifecycle-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

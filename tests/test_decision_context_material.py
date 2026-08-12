"""Thin pytest: decision context → material lifecycle — architecture boundary,
source manifest, evidence packet, proposals, outcome receipts, feedback bridge,
material inventory, rerank, owner-gated apply, lifecycle transitions.

Covers GH-C74 core assertions.
"""

from __future__ import annotations

import json
import re

from loopx.capabilities.decision_context import (
    DecisionSourceSpec,
    build_decision_context_architecture_packet,
    build_decision_evidence_packet,
    build_decision_outcome_receipt,
    build_decision_proposal,
    build_decision_source_manifest,
)
from loopx.capabilities.decision_context.outcome_feedback import (
    build_decision_outcome_feedback,
)
from loopx.capabilities.material_lifecycle import (
    build_material_lifecycle_architecture_packet,
    build_material_lifecycle_receipt,
    build_material_rerank_apply_receipt,
    build_material_rerank_proposal,
    build_material_store_inventory,
)

OBSERVED_AT = "2026-08-01T12:00:00+00:00"
REVIEW_AT = "2026-08-03T12:00:00+00:00"
RECORDED_AT = "2026-08-05T12:00:00+00:00"

_PRIVATE_RE = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def _public_safe(obj: object) -> bool:
    text = json.dumps(obj, sort_keys=True) if not isinstance(obj, str) else obj
    return not any(p.search(text) for p in _PRIVATE_RE)


class TestDecisionContextArchitecture:
    def test_default_off_fail_open(self):
        arch = build_decision_context_architecture_packet()
        assert arch["capability"]["default_enabled"] is False
        assert arch["capability"]["creates_authority"] is False
        assert arch["provider_boundaries"]["provider_failure_policy"] == "fail_open_to_current_authority"
        assert _public_safe(arch)


class TestSourceManifest:
    def test_strips_private_locators(self):
        source = DecisionSourceSpec(
            source_id="source:repo", provider_id="repo-provider", source_kind="repository",
            priority="p0", evidence_level="s1", objectives=("adoption",),
            scan_mode="incremental", exact_read_policy="material_change",
            freshness_seconds=3600, private_locator="secret-locator-value")
        manifest = build_decision_source_manifest(
            goal_id="g:dc", observed_at=OBSERVED_AT, sources=[source])
        serialized = json.dumps(manifest, sort_keys=True)
        assert "secret-locator-value" not in serialized
        assert manifest.get("private_locators_captured") is False
        assert _public_safe(manifest)


class TestEvidencePacket:
    def test_stale_and_conflicts_visible(self):
        evidence = build_decision_evidence_packet(
            goal_id="g:dc", decision_id="d:test", observed_at=OBSERVED_AT,
            changed_facts=[{"fact_id": "f:adoption", "summary": "Rate increased.",
                            "source_ref": "source:repo", "observed_at": OBSERVED_AT}],
            recalled_claims=[{"claim_id": "c:knn", "summary": "KNN top-ranked.",
                              "provider_ref": "p:repo", "source_ref": "source:repo",
                              "source_revision": "r:3", "observed_at": OBSERVED_AT,
                              "exact_read_verified": True}],
            stale_or_rejected_claims=[{"claim_id": "c:old", "summary": "Legacy benchmark.",
                                       "observed_at": OBSERVED_AT, "reason_code": "insufficient_evidence"}],
            conflicts=[{"conflict_id": "conf:rank", "summary": "Rank disagreement.",
                        "source_refs": ["source:repo", "source:bench"],
                        "conflict_rule": "single_material_rank", "status": "unresolved"}],
            source_revisions=[{"source_ref": "source:repo", "revision": "r:3",
                               "observed_at": OBSERVED_AT, "freshness": "current"}],
            provider_health=[{"provider": "repo-provider", "status": "healthy",
                              "observed_at": OBSERVED_AT, "fail_open": True}])
        assert len(evidence["stale_or_rejected_claims"]) == 1
        assert evidence["stale_or_rejected_claims"][0]["reason_code"] == "insufficient_evidence"
        assert len(evidence["conflicts"]) == 1
        assert evidence["conflicts"][0]["status"] == "unresolved"
        assert evidence.get("source_bodies") is None
        assert evidence.get("raw_context_captured") is False
        assert _public_safe(evidence)


class TestDecisionProposal:
    def test_links_evidence_with_confidence(self):
        evidence = build_decision_evidence_packet(
            goal_id="g:dc", decision_id="d:test", observed_at=OBSERVED_AT,
            changed_facts=[{"fact_id": "f:adoption", "summary": "Rate increased.",
                            "source_ref": "source:repo", "observed_at": OBSERVED_AT}],
            recalled_claims=[], stale_or_rejected_claims=[], conflicts=[],
            source_revisions=[{"source_ref": "source:repo", "revision": "r:3",
                               "observed_at": OBSERVED_AT, "freshness": "current"}],
            provider_health=[{"provider": "repo-provider", "status": "healthy",
                              "observed_at": OBSERVED_AT, "fail_open": True}])
        proposal = build_decision_proposal(
            goal_id="g:dc", decision_id="d:test",
            evidence_packet_ref=str(evidence["packet_ref"]),
            observed_at=OBSERVED_AT, review_at=REVIEW_AT,
            objective_scores=[{"objective_id": "obj:adoption", "score": 0.82,
                               "rationale": "Trending upward."}],
            recommended_decision={"option_id": "opt:keep", "summary": "Keep ranking.",
                                  "rationale": "Evidence supports.", "confidence": 0.82})
        assert proposal["evidence_packet_ref"] == evidence["packet_ref"]
        assert proposal["objective_scores"][0]["score"] == 0.82
        assert _public_safe(proposal)


class TestOutcomeReceipt:
    def test_declares_candidate_eligibility(self):
        evidence = build_decision_evidence_packet(
            goal_id="g:dc", decision_id="d:test", observed_at=OBSERVED_AT,
            changed_facts=[{"fact_id": "f:adoption", "summary": "Rate increased.",
                            "source_ref": "source:repo", "observed_at": OBSERVED_AT}],
            recalled_claims=[{"claim_id": "c:knn", "summary": "KNN top.",
                              "provider_ref": "p:repo", "source_ref": "source:repo",
                              "source_revision": "r:3", "observed_at": OBSERVED_AT,
                              "exact_read_verified": True}],
            stale_or_rejected_claims=[], conflicts=[],
            source_revisions=[{"source_ref": "source:repo", "revision": "r:3",
                               "observed_at": OBSERVED_AT, "freshness": "current"}],
            provider_health=[{"provider": "repo-provider", "status": "healthy",
                              "observed_at": OBSERVED_AT, "fail_open": True}])
        proposal = build_decision_proposal(
            goal_id="g:dc", decision_id="d:test",
            evidence_packet_ref=str(evidence["packet_ref"]),
            observed_at=OBSERVED_AT, review_at=REVIEW_AT,
            objective_scores=[{"objective_id": "obj:adoption", "score": 0.82,
                               "rationale": "Trending upward."}],
            recommended_decision={"option_id": "opt:close", "summary": "Close pilot.",
                                  "rationale": "Verified.", "confidence": 0.82})
        outcome = build_decision_outcome_receipt(
            goal_id="g:dc", decision_id="d:test",
            proposal_packet_ref=str(proposal["packet_ref"]),
            recorded_at=RECORDED_AT, review_at=REVIEW_AT,
            verification_status="verified",
            accepted_decision={"option_id": "opt:close", "summary": "Close pilot.",
                               "accepted_by": "owner:goal", "accepted_at": OBSERVED_AT},
            observed_outcomes=[{"outcome_id": "out:pilot", "summary": "Pilot closed.",
                                "evidence_ref": evidence["packet_ref"],
                                "status": "verified", "observed_at": REVIEW_AT}])
        assert outcome["reward_memory_candidate_eligible"] is True
        assert outcome["capability"]["mutates_core_state"] is False
        assert _public_safe(outcome)


class TestOutcomeFeedback:
    def test_creates_candidate_when_eligible(self):
        evidence = build_decision_evidence_packet(
            goal_id="g:dc", decision_id="d:test", observed_at=OBSERVED_AT,
            changed_facts=[{"fact_id": "f:adoption", "summary": "Rate increased.",
                            "source_ref": "source:repo", "observed_at": OBSERVED_AT}],
            recalled_claims=[{"claim_id": "c:knn", "summary": "KNN top.",
                              "provider_ref": "p:repo", "source_ref": "source:repo",
                              "source_revision": "r:3", "observed_at": OBSERVED_AT,
                              "exact_read_verified": True}],
            stale_or_rejected_claims=[], conflicts=[],
            source_revisions=[{"source_ref": "source:repo", "revision": "r:3",
                               "observed_at": OBSERVED_AT, "freshness": "current"}],
            provider_health=[{"provider": "repo-provider", "status": "healthy",
                              "observed_at": OBSERVED_AT, "fail_open": True}])
        proposal = build_decision_proposal(
            goal_id="g:dc", decision_id="d:test",
            evidence_packet_ref=str(evidence["packet_ref"]),
            observed_at=OBSERVED_AT, review_at=REVIEW_AT,
            objective_scores=[{"objective_id": "obj:adoption", "score": 0.82,
                               "rationale": "Trending upward."}],
            recommended_decision={"option_id": "opt:close", "summary": "Close pilot.",
                                  "rationale": "Verified.", "confidence": 0.82})
        outcome = build_decision_outcome_receipt(
            goal_id="g:dc", decision_id="d:test",
            proposal_packet_ref=str(proposal["packet_ref"]),
            recorded_at=RECORDED_AT, review_at=REVIEW_AT, verification_status="verified",
            accepted_decision={"option_id": "opt:close", "summary": "Close pilot.",
                               "accepted_by": "owner:goal", "accepted_at": OBSERVED_AT},
            observed_outcomes=[{"outcome_id": "out:pilot", "summary": "Pilot closed.",
                                "evidence_ref": evidence["packet_ref"],
                                "status": "verified", "observed_at": REVIEW_AT}])
        feedback = build_decision_outcome_feedback(
            evidence_packet=evidence, outcome_receipt=outcome,
            workspace_ref="ws:dc", project_ref="proj:loopx")
        assert feedback["reward_memory"]["candidate_created"] is True
        assert feedback["reward_memory"]["candidate_status"] == "review_ready"
        assert feedback["reward_memory"]["automatic_ingest_performed"] is False
        assert feedback["reward_memory"]["automatic_activation_performed"] is False
        assert feedback.get("raw_context_captured") is False
        assert _public_safe(feedback)

    def test_ineligible_with_conflicts(self):
        evidence = build_decision_evidence_packet(
            goal_id="g:dc", decision_id="d:test", observed_at=OBSERVED_AT,
            changed_facts=[{"fact_id": "f:adoption", "summary": "Rate increased.",
                            "source_ref": "source:repo", "observed_at": OBSERVED_AT}],
            recalled_claims=[{"claim_id": "c:knn", "summary": "KNN top.",
                              "provider_ref": "p:repo", "source_ref": "source:repo",
                              "source_revision": "r:3", "observed_at": OBSERVED_AT,
                              "exact_read_verified": True}],
            stale_or_rejected_claims=[],
            conflicts=[{"conflict_id": "conf:rank", "summary": "Disagreement.",
                        "source_refs": ["source:repo", "source:bench"],
                        "conflict_rule": "single_material_rank", "status": "unresolved"}],
            source_revisions=[{"source_ref": "source:repo", "revision": "r:3",
                               "observed_at": OBSERVED_AT, "freshness": "current"}],
            provider_health=[{"provider": "repo-provider", "status": "healthy",
                              "observed_at": OBSERVED_AT, "fail_open": True}])
        proposal = build_decision_proposal(
            goal_id="g:dc", decision_id="d:test",
            evidence_packet_ref=str(evidence["packet_ref"]),
            observed_at=OBSERVED_AT, review_at=REVIEW_AT,
            objective_scores=[{"objective_id": "obj:adoption", "score": 0.82, "rationale": "Up."}],
            recommended_decision={"option_id": "opt:close", "summary": "Close.",
                                  "rationale": "OK.", "confidence": 0.82})
        outcome = build_decision_outcome_receipt(
            goal_id="g:dc", decision_id="d:test",
            proposal_packet_ref=str(proposal["packet_ref"]),
            recorded_at=RECORDED_AT, review_at=REVIEW_AT, verification_status="verified",
            accepted_decision={"option_id": "opt:close", "summary": "Close.",
                               "accepted_by": "owner:goal", "accepted_at": OBSERVED_AT},
            observed_outcomes=[{"outcome_id": "out:pilot", "summary": "Done.",
                                "evidence_ref": evidence["packet_ref"],
                                "status": "verified", "observed_at": REVIEW_AT}])
        feedback = build_decision_outcome_feedback(
            evidence_packet=evidence, outcome_receipt=outcome,
            workspace_ref="ws:dc", project_ref="proj:loopx")
        assert feedback["reward_memory"]["candidate_created"] is False
        assert "unresolved_authority_conflict" in feedback["reward_memory"]["ineligible_reason_codes"]


class TestMaterialLifecycle:
    def test_architecture_default_off(self):
        arch = build_material_lifecycle_architecture_packet()
        assert arch["capability"]["default_enabled"] is False
        assert arch["provider_boundaries"]["raw_material_store"] == "private_external_authority"
        assert _public_safe(arch)

    def test_inventory_raw_content_absent(self):
        inv = build_material_store_inventory(
            goal_id="g:dc", store_id="store:materials", store_revision="r:3",
            observed_at=OBSERVED_AT, source_snapshot_ref="snap:3",
            backup_ref="backup:3", source_digest="sha256:abcdef0123456789",
            lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
            stable_ids_verified=True, backup_verified=True)
        assert inv["raw_content_captured"] is False
        assert inv["stable_ids_verified"] is True
        assert inv["backup_verified"] is True
        assert "private material body" not in json.dumps(inv, sort_keys=True)
        assert _public_safe(inv)

    def test_rerank_proposal_references_evidence(self):
        inv = build_material_store_inventory(
            goal_id="g:dc", store_id="store:materials", store_revision="r:3",
            observed_at=OBSERVED_AT, source_snapshot_ref="snap:3",
            backup_ref="backup:3", source_digest="sha256:abcdef0123456789",
            lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
            stable_ids_verified=True, backup_verified=True)
        proposal = build_material_rerank_proposal(
            goal_id="g:dc", proposal_id="prop:rerank",
            inventory_ref=str(inv["inventory_ref"]),
            decision_evidence_ref="decision-evidence-abc",
            observed_at=OBSERVED_AT, target_window_size=10,
            max_moved_items=2, max_rank_displacement=4,
            moves=[{"material_ref": "mat:2", "from_rank": 5, "to_rank": 1,
                    "reason_code": "current_objective_fit"}])
        assert proposal["raw_content_captured"] is False
        assert proposal["decision_evidence_ref"] == "decision-evidence-abc"
        assert proposal["moves"][0]["reason_code"] == "current_objective_fit"
        assert proposal["constraints"]["max_moved_items"] == 2
        assert _public_safe(proposal)

    def test_rerank_apply_owner_gated(self):
        inv = build_material_store_inventory(
            goal_id="g:dc", store_id="store:materials", store_revision="r:3",
            observed_at=OBSERVED_AT, source_snapshot_ref="snap:3",
            backup_ref="backup:3", source_digest="sha256:abcdef0123456789",
            lifecycle_counts={"candidate": 5, "active": 12, "archived": 3},
            stable_ids_verified=True, backup_verified=True)
        proposal = build_material_rerank_proposal(
            goal_id="g:dc", proposal_id="prop:rerank",
            inventory_ref=str(inv["inventory_ref"]),
            decision_evidence_ref="decision-evidence-abc",
            observed_at=OBSERVED_AT, target_window_size=10,
            max_moved_items=2, max_rank_displacement=4,
            moves=[{"material_ref": "mat:2", "from_rank": 5, "to_rank": 1,
                    "reason_code": "current_objective_fit"}])
        receipt = build_material_rerank_apply_receipt(
            goal_id="g:dc", receipt_id="rec:rerank-1",
            proposal_ref=str(proposal["proposal_ref"]),
            observed_at=OBSERVED_AT, status="applied",
            before_revision="r:3", after_revision="r:4",
            owner_gate_ref="gate:owner-approval",
            validation_ref="validation:rerank-1",
            applied_material_refs=["mat:2"], rollback_ref="rollback:r:3")
        assert receipt["raw_content_captured"] is False
        assert receipt["owner_gate_ref"] == "gate:owner-approval"
        assert receipt["validation_ref"] == "validation:rerank-1"
        assert "cursor_commit_ref" not in receipt
        assert _public_safe(receipt)

    def test_lifecycle_transition_authority(self):
        receipt = build_material_lifecycle_receipt(
            goal_id="g:dc", receipt_id="rec:archive-5",
            material_ref="mat:5", from_state="active", to_state="archived",
            observed_at=OBSERVED_AT, source_ref="source:repo",
            source_revision="r:3",
            transition_authority_ref="decision-outcome:archive-5",
            archive_ref="archive:mat-5")
        assert receipt["raw_content_captured"] is False
        assert receipt["transition_authority_ref"] == "decision-outcome:archive-5"
        assert receipt["from_state"] == "active"
        assert receipt["to_state"] == "archived"
        assert _public_safe(receipt)

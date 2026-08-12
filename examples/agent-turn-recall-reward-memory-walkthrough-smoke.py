#!/usr/bin/env python3
"""Contributor-facing walkthrough: Agent Turn Recall ↔ Reward Memory.

Covers the shipped pipeline from corpus health through scoped recall:

1. **Architecture** — design contract: default-off, advisory only, creates no authority
2. **Corpus registry** — 7 reference corpora declare surface, scope, and class coverage
3. **Corpus health** — per-case health checks report pipeline steps and readiness
4. **Candidate creation** — synthetically built from verified outcomes; raw content
   never captured; guard checks authority and scope
5. **Candidate review** — accept / reject / edit / retire / no_write decisions;
   accepted candidates transition to active; guard-blocked candidates reject write
6. **Active record** — scoped to corpus; carries lifecycle with optional expiry;
   only accepted guard-passed candidates can become active
7. **Agent Turn Situation** — built from a synthetic quota decision; prompt-independent;
   fingerprints material changes; never includes user prompt
8. **Recall preview** — query evidence without provider call; guidance is empty
   until executed
9. **Recall request** — scoped to corpus, surface, and revision; guard checks scope,
   authority, freshness, and conflict
10. **Recall execution** — runs through a provider; returns public-safe packet and
    transient in-process items
11. **Apply recall** — caller-owned reasoning callback; fail-open to base output;
    never grants new authority
12. **Full pipeline** — candidate → review → active record → recall → apply

No provider payloads, raw sessions, credentials, private locators, or external sinks.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.agent_turn_recall.core import (  # noqa: E402
    build_agent_turn_recall_preview,
    build_agent_turn_situation,
)
from loopx.capabilities.context_providers.base import (  # noqa: E402
    ContextProviderItem,
    ContextProviderRetrieval,
)
from loopx.capabilities.reward_memory import (  # noqa: E402
    apply_reward_memory_recall,
    build_active_reward_memory_record,
    build_reward_memory_architecture_packet,
    build_reward_memory_candidate,
    build_reward_memory_corpus_health_packet,
    build_reward_memory_corpus_registry_packet,
    build_reward_memory_recall_request,
    execute_reward_memory_recall,
    review_reward_memory_candidate,
    reward_memory_health_case,
)

OBSERVED_AT = "2026-08-10T12:00:00+00:00"
WORKSPACE = "workspace:rm-walkthrough"
PROJECT = "repository:loopx"
SURFACE = "agent_workflow.turn_admission"
SCOPE_REF = "viking://user/example/memories/agent-turn"

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


# ── Helpers ──────────────────────────────────────────────────────────

def _corpus(*, corpus_id: str, class_id: str, surface: str) -> dict[str, Any]:
    """Build a minimal valid corpus dict for testing."""
    return {
        "corpus_id": corpus_id,
        "class_id": class_id,
        "provider_id": "fake_provider",
        "owner_ref": "owner:example",
        "source_of_truth": "reviewed_owner_feedback",
        "read_authority": "module_scoped",
        "write_authority": "provider_managed",
        "scope": {
            "workspace_ref": WORKSPACE,
            "project_ref": PROJECT,
            "surface_ids": [surface],
        },
        "freshness": {
            "mode": "revision_bound",
            "source_revision": "revision:abc123",
        },
        "lifecycle": {"state": "active", "supersedes": []},
        "retrieval": {
            "index_required": True,
            "readback_required": True,
            "application_receipt_required": True,
        },
        "maintenance": {
            "writeback_triggers": ["reviewed_candidate"],
            "closure_policy": "provider_write_then_revision_verified_read",
            "retirement_authority": "owner:example",
        },
        "privacy": {"visibility": "private", "raw_content_in_registry": False},
        "provider_scope_ref_digest": hashlib.sha256(
            SCOPE_REF.encode("utf-8")
        ).hexdigest()[:16],
    }


def _candidate_scope(corpus: dict[str, Any]) -> dict[str, Any]:
    """Return a candidate scope that satisfies the corpus revision check."""
    scope = dict(corpus["scope"])
    if corpus["freshness"]["mode"] == "revision_bound":
        scope["revision_ref"] = corpus["freshness"]["source_revision"]
    return scope


def _binding(corpus_id: str) -> dict[str, Any]:
    return {
        "corpus_id": corpus_id,
        "provider_id": "fake_provider",
        "namespace": "reward_memory",
        "scope_ref": SCOPE_REF,
        "timeout_seconds": 5,
    }


def _checkpoint(corpus_id: str, surface: str) -> dict[str, Any]:
    return {
        "verified": True,
        "corpus_id": corpus_id,
        "workspace_ref": WORKSPACE,
        "project_ref": PROJECT,
        "surface_id": surface,
        "read_authority": "module_scoped",
        "source_ref": "repository:authority-map",
    }


def _quota_decision(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ok": True,
        "status_health_ok": True,
        "decision": "run",
        "lifecycle_phase": "reviewing",
        "recommended_action": "Review, refine, validate, and close the selected work.",
        "latest_run_recommended_action": "Inspect the exact diff before changing it.",
        "selected_todo": {
            "todo_id": "todo:walkthrough-001",
            "text": "Review and refine the selected advancement task.",
            "action_kind": "review_refine_merge",
            "target_key": "pr:walkthrough",
            "claimed_by": "agent:codex-alpha",
        },
    }
    base.update(overrides)
    return base


def _review(decision: str, **extra: Any) -> dict[str, Any]:
    return {
        "decision": decision,
        "reviewer_ref": "github:user:maintainer",
        "review_ref": f"review:smoke:{decision}",
        "reasoning_summary": "The scoped candidate was reviewed.",
        **extra,
    }


class FakeProvider:
    """Returns synthetic recall items without requiring a live daemon."""

    provider_id = "fake_provider"

    def __init__(
        self,
        content: str | None = None,
        *,
        status: str = "completed",
    ) -> None:
        self.content = content
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def retrieve(self, **kwargs: Any) -> ContextProviderRetrieval:
        self.calls.append(dict(kwargs))
        if self.status != "completed":
            return ContextProviderRetrieval(
                provider=self.provider_id,
                namespace=str(kwargs["namespace"]),
                status=self.status,
                query_summary=str(kwargs["query_summary"]),
                observed_at=str(kwargs["observed_at"]),
                search_performed=False,
                read_performed=False,
                items=(),
                reason_code="provider_service_unavailable",
                requested_limit=int(kwargs["max_results"]),
            )
        items = (
            (
                ContextProviderItem(
                    resource_ref=f"{SCOPE_REF}/turn-guidance.json",
                    summary="Scoped turn guidance.",
                    content=self.content or "{}",
                    score=0.97,
                ),
            )
            if self.content
            else ()
        )
        return ContextProviderRetrieval(
            provider=self.provider_id,
            namespace=str(kwargs["namespace"]),
            status="completed",
            query_summary=str(kwargs["query_summary"]),
            observed_at=str(kwargs["observed_at"]),
            search_performed=True,
            read_performed=bool(items),
            items=items,
            requested_limit=int(kwargs["max_results"]),
        )


# ── Scenario 1: Architecture declares default-off, no authority ──

def test_reward_memory_architecture_boundary() -> None:
    """Reward Memory is default-off, advisory only, creates no authority."""
    arch = build_reward_memory_architecture_packet()
    assert arch["ok"] is True
    assert arch["schema_version"] == "reward_memory_architecture_v0"
    assert arch["status"] == "design_contract"
    # Stage boundaries confirm Stage 3 is opt-in, not default-on.
    assert arch["stage_boundaries"]["stage_3"].startswith("implemented_opt_in")
    # Safety invariants: confidence never increases authority.
    assert "confidence_never_increases_authority" in arch["safety_invariants"]
    # Existing capability: recall application is opt-in.
    assert (
        arch["existing_capability_reuse"]["recall_application"]["automatic_recall"]
        is False
    )
    _assert_public_safe(arch, label="rm-arch")


# ── Scenario 2: Corpus registry declares 7 reference corpora ──

def test_corpus_registry_shape() -> None:
    """The reference corpus registry declares surface, scope, and evaluation
    rules for each corpus.  7 corpora are defined covering 5 classes."""
    registry = build_reward_memory_corpus_registry_packet()
    assert registry["schema_version"] == "reward_memory_corpus_registry_v0"
    assert registry["status"] == "reference_registry"
    assert registry["corpus_count"] == 7
    assert set(registry["class_coverage"]) == {
        "run_bound_reward",
        "hard_policy",
        "soft_preference",
        "procedural_experience",
        "working_context",
    }
    assert registry["raw_memory_captured"] is False
    assert registry["registry_persisted"] is False
    for corpus in registry["corpora"]:
        assert corpus["privacy"]["raw_content_in_registry"] is False
    _assert_public_safe(registry, label="rm-registry")


# ── Scenario 3: Corpus health reports per-case pipeline status ──

def test_corpus_health_shape() -> None:
    """Each health case reports pipeline steps: corpus presence, index,
    retrieval, readback, application."""
    # Health case "empty" — corpus present but zero records.
    corpus, observation = reward_memory_health_case("empty")
    health = build_reward_memory_corpus_health_packet(corpus, observation)
    assert health["health_state"] == "empty"
    assert health["memory_patch_authority"] is False
    assert health["pipeline"]["corpus_present"] is True
    assert health["pipeline"]["record_count"] == 0
    assert health["may_apply_memory"] is False

    # Health case "retrieval-verified" — ready to apply.
    corpus2, obs2 = reward_memory_health_case("retrieval-verified")
    health2 = build_reward_memory_corpus_health_packet(corpus2, obs2)
    assert health2["health_state"] == "retrieval_verified"
    assert health2["may_apply_memory"] is True

    _assert_public_safe(health, label="rm-health-empty")
    _assert_public_safe(health2, label="rm-health-verified")


# ── Scenario 4: Candidate creation — raw content never captured ──

def test_candidate_creation_raw_content_absent() -> None:
    """Every candidate declares ``raw_content_captured: False``.
    The guard checks authority and scope; hard_policy requires a checkpoint."""
    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "hard_policy",
            "content_summary": (
                "A verified decision outcome produced a measurable improvement."
            ),
            "source": {
                "source_kind": "verified_decision_outcome",
                "source_ref": "decision-outcome:example-1",
                "actor_ref": "owner:goal",
                "actor_role": "verified_decision_owner",
            },
            "scope": {
                "workspace_ref": WORKSPACE,
                "project_ref": PROJECT,
                "surface_ids": ["agent_workflow.turn_admission"],
                "revision_ref": "revision:abc123",
            },
            "reasoning": {
                "summary": "An exact-read-verified claim and a verified outcome.",
                "confidence": "high",
            },
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
        authority_checkpoint={
            "verified": True,
            "source_ref": "repository:authority-map",
            "actor_ref": "owner:goal",
            "actor_role": "verified_decision_owner",
            "project_ref": PROJECT,
            "action_scopes": [],
        },
    )
    assert candidate_packet["schema_version"] == "reward_memory_candidate_v0"
    assert candidate_packet["raw_content_captured"] is False
    assert candidate_packet["candidate_persisted"] is False
    assert candidate_packet["provider_write_performed"] is False
    _assert_public_safe(candidate_packet, label="rm-candidate")


# ── Scenario 5: Candidate review — accept / reject / edit / no_write ──

def test_candidate_review_paths() -> None:
    """Candidates transition through review decisions.
    accept → active, reject → rejected, edit → new candidate, no_write → retained."""
    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "soft_preference",
            "content_summary": "Keep analysis concise with evidence links.",
            "source": {
                "source_kind": "explicit_feedback",
                "source_ref": "feedback:example-2",
                "actor_ref": "user:example",
                "actor_role": "verified_project_owner_or_operator",
            },
            "scope": {
                "workspace_ref": WORKSPACE,
                "project_ref": PROJECT,
                "surface_ids": ["agent_workflow.turn_admission"],
                "revision_ref": "revision:abc123",
            },
            "reasoning": {"summary": "Test candidate.", "confidence": "medium"},
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
    )

    # Accept.
    accepted = review_reward_memory_candidate(candidate_packet, _review("accept"))
    assert accepted["effective_decision"] == "accept"
    assert accepted["status"] == "active"
    assert accepted["grants_new_action_authority"] is False

    # Reject.
    rejected = review_reward_memory_candidate(candidate_packet, _review("reject"))
    assert rejected["status"] == "rejected"

    # Edit creates a new candidate.
    edited = review_reward_memory_candidate(
        candidate_packet,
        _review(
            "edit",
            edited_content_summary="Keep analysis concise with linked evidence.",
        ),
    )
    assert edited["status"] == "review_ready"
    assert (
        edited["record"]["candidate_ref"]
        != candidate_packet["candidate"]["candidate_ref"]
    )

    # no_write retains state.
    no_write = review_reward_memory_candidate(candidate_packet, _review("no_write"))
    assert no_write["status"] == "no_write"

    _assert_public_safe(accepted, label="rm-review-accept")
    _assert_public_safe(rejected, label="rm-review-reject")


# ── Scenario 6: Guard-blocked candidates reject write ──

def test_guard_blocked_rejects_write() -> None:
    """An unverified checkpoint blocks the guard.
    Guard-blocked candidates cannot become active even on accept."""
    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "hard_policy",
            "content_summary": "Policy without verified authority.",
            "source": {
                "source_kind": "repository_policy",
                "source_ref": "policy:unverified",
                "actor_ref": "owner:goal",
                "actor_role": "verified_decision_owner",
            },
            "scope": {
                "workspace_ref": WORKSPACE,
                "project_ref": PROJECT,
                "surface_ids": ["agent_workflow.turn_admission"],
                "revision_ref": "revision:abc123",
            },
            "reasoning": {"summary": "Missing checkpoint.", "confidence": "low"},
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
        authority_checkpoint={
            "verified": False,
            "source_ref": None,
            "actor_ref": "owner:goal",
            "actor_role": "verified_decision_owner",
            "project_ref": PROJECT,
            "action_scopes": [],
        },
    )
    assert candidate_packet["status"] == "guard_blocked"

    blocked_review = review_reward_memory_candidate(
        candidate_packet, _review("accept")
    )
    assert blocked_review["effective_decision"] == "no_write"
    assert blocked_review["status"] == "guard_blocked"

    _assert_public_safe(blocked_review, label="rm-guard-blocked")


# ── Scenario 7: Active record is scoped and carries lifecycle ──

def test_active_record_scoped_and_lifecycle() -> None:
    """An active reward memory record is scoped to a corpus and carries
    lifecycle state.  Only accepted guard-passed candidates become active."""
    corpus = _corpus(
        corpus_id="agent_turn_prefs", class_id="soft_preference", surface=SURFACE
    )

    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "soft_preference",
            "content_summary": "Prefer small, reversible changes.",
            "expires_at": "2026-09-01T00:00:00+00:00",
            "source": {
                "source_kind": "explicit_feedback",
                "source_ref": "feedback:example-3",
                "actor_ref": "user:example",
                "actor_role": "verified_project_owner_or_operator",
            },
            "scope": _candidate_scope(corpus),
            "reasoning": {
                "summary": "Explicit scoped preference.",
                "confidence": "high",
            },
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
    )
    accepted = review_reward_memory_candidate(candidate_packet, _review("accept"))
    active = build_active_reward_memory_record(
        accepted,
        corpus,
        activated_at=OBSERVED_AT,
    )
    assert active["schema_version"] == "reward_memory_active_record_v0"
    assert active["corpus_id"] == "agent_turn_prefs"
    assert active["target_class"] == "soft_preference"
    assert active["lifecycle"] == {
        "state": "active",
        "expires_at": "2026-09-01T00:00:00+00:00",
    }
    assert active["provider_write_performed"] is False
    _assert_public_safe(active, label="rm-active")


# ── Scenario 8: Agent Turn Situation is prompt-independent ──

def test_agent_turn_situation_is_prompt_independent() -> None:
    """A turn situation is built from a synthetic quota decision.
    It is prompt-independent, fingerprints material changes, and never
    includes user prompt text."""
    situation = build_agent_turn_situation(
        _quota_decision(),
        goal_id="goal:rm-walkthrough",
        agent_id="agent:codex-alpha",
        turn_instance_id="2026-08-10T12:00:00+00:00",
        workspace_ref=WORKSPACE,
        project_ref=PROJECT,
    )
    assert situation["schema_version"] == "agent_turn_situation_v0"
    assert situation["user_prompt_included"] is False
    assert "situation_fingerprint" in situation
    assert "turn_recall_id" in situation
    assert situation["selected_todo"]["todo_id"] == "todo:walkthrough-001"

    # Same inputs → same fingerprint.
    again = build_agent_turn_situation(
        _quota_decision(),
        goal_id="goal:rm-walkthrough",
        agent_id="agent:codex-alpha",
        turn_instance_id="2026-08-10T12:00:00+00:00",
        workspace_ref=WORKSPACE,
        project_ref=PROJECT,
    )
    assert situation["situation_fingerprint"] == again["situation_fingerprint"]

    # Different turn → different recall ID.
    next_turn = build_agent_turn_situation(
        _quota_decision(),
        goal_id="goal:rm-walkthrough",
        agent_id="agent:codex-alpha",
        turn_instance_id="2026-08-10T12:01:00+00:00",
        workspace_ref=WORKSPACE,
        project_ref=PROJECT,
    )
    assert situation["turn_recall_id"] != next_turn["turn_recall_id"]

    _assert_public_safe(situation, label="turn-situation")


# ── Scenario 9: Recall preview — no provider call, guidance empty ──

def test_recall_preview_no_provider_call() -> None:
    """The recall preview builds query evidence without calling a provider.
    Guidance is always empty until execution."""
    situation = build_agent_turn_situation(
        _quota_decision(),
        goal_id="goal:rm-walkthrough",
        agent_id="agent:codex-alpha",
        turn_instance_id="2026-08-10T12:00:00+00:00",
        workspace_ref=WORKSPACE,
        project_ref=PROJECT,
    )
    preview = build_agent_turn_recall_preview(situation)
    assert preview["status"] == "preview"
    assert preview["provider_call_count"] == 0
    assert preview["context"]["guidance"] == []
    assert preview["execute_required_for_recall"] is True
    assert preview["query_evidence"]["exact_query_exposed"] is False
    assert preview["grants_new_action_authority"] is False
    _assert_public_safe(preview, label="recall-preview")


# ── Scenario 10: Recall request is scoped and guarded ──

def test_recall_request_scoped_and_guarded() -> None:
    """A recall request is scoped to corpus, surface, and revision.
    The guard checks scope, authority, freshness, and conflict."""
    corpus = _corpus(
        corpus_id="agent_turn_prefs", class_id="soft_preference", surface=SURFACE
    )
    request = build_reward_memory_recall_request(
        corpus,
        {
            "workspace_ref": WORKSPACE,
            "project_ref": PROJECT,
            "surface_id": SURFACE,
            "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [
                {"query": "turn guidance", "query_summary": "agent turn admission"}
            ],
            "limit": 3,
            "observed_at": OBSERVED_AT,
            "freshness_context": {
                "source_truth_current": True,
                "source_revision": "revision:abc123",
            },
            "conflict_state": "clear",
            "raw_content_captured": False,
        },
        read_authority_checkpoint=_checkpoint("agent_turn_prefs", SURFACE),
    )
    assert request["status"] == "ready"
    assert request["guard"]["passed"] is True
    assert request["request"]["query_evidence"][0]["exact_query_exposed"] is False

    # Wrong project → guard blocked.
    blocked = build_reward_memory_recall_request(
        corpus,
        {
            "workspace_ref": WORKSPACE,
            "project_ref": "repository:other",
            "surface_id": SURFACE,
            "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [
                {"query": "turn guidance", "query_summary": "agent turn admission"}
            ],
            "limit": 3,
            "observed_at": OBSERVED_AT,
            "freshness_context": {
                "source_truth_current": True,
                "source_revision": "revision:abc123",
            },
            "conflict_state": "clear",
            "raw_content_captured": False,
        },
        read_authority_checkpoint=_checkpoint("agent_turn_prefs", SURFACE),
    )
    assert blocked["status"] == "guard_blocked"
    assert "project_scope_mismatch" in blocked["guard"]["reason_codes"]

    _assert_public_safe(request, label="recall-request")
    _assert_public_safe(blocked, label="recall-request-blocked")


# ── Scenario 11: Recall execution and application with fake provider ──

def test_recall_execution_and_application() -> None:
    """Recall executes through a provider and returns items.
    Application runs a caller-owned callback; fail-open preserves base output."""
    corpus = _corpus(
        corpus_id="agent_turn_prefs", class_id="soft_preference", surface=SURFACE
    )

    # Build an active record content so the fake provider can return it.
    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "soft_preference",
            "content_summary": (
                "Prefer small reversible changes over large refactors."
            ),
            "source": {
                "source_kind": "explicit_feedback",
                "source_ref": "feedback:example-4",
                "actor_ref": "user:example",
                "actor_role": "verified_project_owner_or_operator",
            },
            "scope": _candidate_scope(corpus),
            "reasoning": {"summary": "Scoped preference.", "confidence": "high"},
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
    )
    accepted = review_reward_memory_candidate(candidate_packet, _review("accept"))
    active = build_active_reward_memory_record(
        accepted,
        corpus,
        activated_at=OBSERVED_AT,
    )

    request = build_reward_memory_recall_request(
        corpus,
        {
            "workspace_ref": WORKSPACE,
            "project_ref": PROJECT,
            "surface_id": SURFACE,
            "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [
                {"query": "turn guidance", "query_summary": "agent turn admission"}
            ],
            "limit": 3,
            "observed_at": OBSERVED_AT,
            "freshness_context": {
                "source_truth_current": True,
                "source_revision": "revision:abc123",
            },
            "conflict_state": "clear",
            "raw_content_captured": False,
        },
        read_authority_checkpoint=_checkpoint("agent_turn_prefs", SURFACE),
    )

    provider = FakeProvider(json.dumps(active, ensure_ascii=False))
    session = execute_reward_memory_recall(
        request,
        provider_binding=_binding("agent_turn_prefs"),
        provider=provider,
    )
    assert session.public_packet["status"] == "completed"
    assert session.public_packet["result_count"] == 1
    assert session.public_packet["provider_call_count"] == 1

    # Apply recall with a callback.
    context: dict[str, Any] = {"guidance": []}
    applied = apply_reward_memory_recall(
        context,
        session,
        application_id="turn-recall:walkthrough",
        apply_memory=lambda base, items: {
            "outcome": "applied",
            "output": dict(base)
            | {
                "guidance": [
                    {
                        "candidate_ref": item.candidate_ref,
                        "target_class": item.target_class,
                        "content_summary": item.content_summary,
                    }
                    for item in items
                ],
            },
            "memory_refs": [item.memory_ref for item in items],
            "reasoning_summary": "Guidance injected into private turn context.",
            "current_artifact_verified": True,
        },
    )
    assert applied["status"] == "applied"
    assert len(applied["output"]["guidance"]) == 1
    assert applied["output"]["guidance"][0]["content_summary"] == (
        "Prefer small reversible changes over large refactors."
    )

    # Provider unavailable → fail-open.
    bad_provider = FakeProvider(status="unavailable")
    bad_session = execute_reward_memory_recall(
        request,
        provider_binding=_binding("agent_turn_prefs"),
        provider=bad_provider,
    )
    assert bad_session.public_packet["status"] == "provider_unavailable"
    fail_open = apply_reward_memory_recall(
        context,
        bad_session,
        application_id="turn-recall:walkthrough-fail",
    )
    assert fail_open["status"] == "not_available"
    assert fail_open["fail_open_preserved_base"] is True

    _assert_public_safe(applied, label="recall-applied")
    _assert_public_safe(fail_open, label="recall-fail-open")


# ── Scenario 12: Recall items are advisory hints, never authority ──

def test_recall_items_are_advisory() -> None:
    """Each active record item is an advisory hint — it never grants
    new action authority.  The recall application receipt asserts this."""
    corpus = _corpus(
        corpus_id="agent_turn_prefs", class_id="soft_preference", surface=SURFACE
    )
    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "soft_preference",
            "content_summary": "Keep diffs under 200 lines.",
            "source": {
                "source_kind": "explicit_feedback",
                "source_ref": "feedback:hint",
                "actor_ref": "user:example",
                "actor_role": "verified_project_owner_or_operator",
            },
            "scope": _candidate_scope(corpus),
            "reasoning": {"summary": "Scoped hint.", "confidence": "high"},
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
    )
    accepted = review_reward_memory_candidate(candidate_packet, _review("accept"))
    assert accepted["grants_new_action_authority"] is False

    active = build_active_reward_memory_record(
        accepted,
        corpus,
        activated_at=OBSERVED_AT,
    )
    # The record itself never carries raw content.
    assert active["privacy"]["raw_content_captured"] is False

    _assert_public_safe(active, label="rm-hint")


# ── Scenario 13: Full walkthrough pipeline ──

def test_full_walkthrough_pipeline() -> None:
    """End-to-end: architecture → registry → health → candidate → review →
    active record → situation → preview → recall → apply."""
    goal_id = "goal:rm-walkthrough"
    agent_id = "agent:codex-alpha"
    corpus = _corpus(
        corpus_id="agent_turn_prefs", class_id="soft_preference", surface=SURFACE
    )

    # Step 1: Architecture.
    arch = build_reward_memory_architecture_packet()
    assert arch["ok"] is True

    # Step 2: Registry.
    registry = build_reward_memory_corpus_registry_packet()
    assert registry["corpus_count"] == 7

    # Step 3: Health.
    c, o = reward_memory_health_case("retrieval-verified")
    health = build_reward_memory_corpus_health_packet(c, o)
    assert health["may_apply_memory"] is True

    # Step 4: Candidate.
    candidate_packet = build_reward_memory_candidate(
        {
            "target_class": "soft_preference",
            "content_summary": (
                "After merging, report refinements and suggest rebase."
            ),
            "source": {
                "source_kind": "explicit_feedback",
                "source_ref": "feedback:pipeline",
                "actor_ref": "user:example",
                "actor_role": "verified_project_owner_or_operator",
            },
            "scope": _candidate_scope(corpus),
            "reasoning": {"summary": "Pipeline test.", "confidence": "high"},
            "guard_context": {
                "source_freshness": "current",
                "conflict_state": "clear",
                "current_artifact_verified": True,
            },
            "requested_action_scopes": [],
            "raw_content_captured": False,
        },
    )
    assert candidate_packet["raw_content_captured"] is False

    # Step 5: Review and accept.
    accepted = review_reward_memory_candidate(candidate_packet, _review("accept"))
    assert accepted["effective_decision"] == "accept"
    assert accepted["status"] == "active"

    # Step 6: Active record.
    active = build_active_reward_memory_record(
        accepted,
        corpus,
        activated_at=OBSERVED_AT,
    )
    assert active["lifecycle"]["state"] == "active"

    # Step 7: Turn situation.
    situation = build_agent_turn_situation(
        _quota_decision(),
        goal_id=goal_id,
        agent_id=agent_id,
        turn_instance_id="2026-08-10T12:00:00+00:00",
        workspace_ref=WORKSPACE,
        project_ref=PROJECT,
    )
    assert situation["user_prompt_included"] is False

    # Step 8: Preview.
    preview = build_agent_turn_recall_preview(situation)
    assert preview["provider_call_count"] == 0

    # Step 9: Recall request.
    request = build_reward_memory_recall_request(
        corpus,
        {
            "workspace_ref": WORKSPACE,
            "project_ref": PROJECT,
            "surface_id": SURFACE,
            "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [
                {"query": "turn guidance", "query_summary": "agent turn admission"}
            ],
            "limit": 3,
            "observed_at": OBSERVED_AT,
            "freshness_context": {
                "source_truth_current": True,
                "source_revision": "revision:abc123",
            },
            "conflict_state": "clear",
            "raw_content_captured": False,
        },
        read_authority_checkpoint=_checkpoint("agent_turn_prefs", SURFACE),
    )
    assert request["status"] == "ready"

    # Step 10: Execute recall.
    provider = FakeProvider(json.dumps(active, ensure_ascii=False))
    session = execute_reward_memory_recall(
        request,
        provider_binding=_binding("agent_turn_prefs"),
        provider=provider,
    )
    assert session.public_packet["status"] == "completed"

    # Step 11: Apply recall.
    applied = apply_reward_memory_recall(
        {"guidance": []},
        session,
        application_id="turn-recall:pipeline",
        apply_memory=lambda base, items: {
            "outcome": "applied",
            "output": dict(base)
            | {
                "guidance": [
                    {
                        "candidate_ref": item.candidate_ref,
                        "target_class": item.target_class,
                        "content_summary": item.content_summary,
                    }
                    for item in items
                ],
            },
            "memory_refs": [item.memory_ref for item in items],
            "reasoning_summary": "Pipeline guidance applied.",
            "current_artifact_verified": True,
        },
    )
    assert applied["status"] == "applied"
    assert len(applied["output"]["guidance"]) == 1

    # Every payload public-safe.
    for label, payload in [
        ("arch", arch),
        ("registry", registry),
        ("health", health),
        ("candidate", candidate_packet),
        ("accepted", accepted),
        ("active", active),
        ("situation", situation),
        ("preview", preview),
        ("request", request),
        ("session-public", session.public_packet),
        ("applied", applied),
    ]:
        _assert_public_safe(payload, label=label)


def main() -> int:
    tests: list[tuple[str, Any]] = [
        ("rm architecture boundary", test_reward_memory_architecture_boundary),
        ("corpus registry shape", test_corpus_registry_shape),
        ("corpus health shape", test_corpus_health_shape),
        ("candidate creation raw content absent", test_candidate_creation_raw_content_absent),
        ("candidate review paths", test_candidate_review_paths),
        ("guard blocked rejects write", test_guard_blocked_rejects_write),
        ("active record scoped and lifecycle", test_active_record_scoped_and_lifecycle),
        (
            "agent turn situation prompt-independent",
            test_agent_turn_situation_is_prompt_independent,
        ),
        ("recall preview no provider call", test_recall_preview_no_provider_call),
        ("recall request scoped and guarded", test_recall_request_scoped_and_guarded),
        ("recall execution and application", test_recall_execution_and_application),
        ("recall items are advisory", test_recall_items_are_advisory),
        ("full walkthrough pipeline", test_full_walkthrough_pipeline),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("agent-turn-recall-reward-memory-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

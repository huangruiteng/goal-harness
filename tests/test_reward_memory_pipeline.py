"""Thin pytest: reward memory pipeline — architecture, corpus registry, health,
candidate lifecycle, turn situation, recall preview/request/execution/apply.

Covers GH-C71 core assertions.
"""

from __future__ import annotations

import hashlib
import json
import re

from loopx.capabilities.agent_turn_recall.core import (
    build_agent_turn_recall_preview,
    build_agent_turn_situation,
)
from loopx.capabilities.context_providers.base import (
    ContextProviderItem,
    ContextProviderRetrieval,
)
from loopx.capabilities.reward_memory import (
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

SCOPE_REF = "viking://user/example/memories/agent-turn"
OBSERVED_AT = "2026-08-10T12:00:00+00:00"
WORKSPACE = "workspace:rm-test"
PROJECT = "repository:loopx"
SURFACE = "agent_workflow.turn_admission"

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


def _corpus(corpus_id="agent_turn_prefs", class_id="soft_preference", surface=SURFACE):
    return {
        "corpus_id": corpus_id, "class_id": class_id, "provider_id": "fake_provider",
        "owner_ref": "owner:example", "source_of_truth": "reviewed_owner_feedback",
        "read_authority": "module_scoped", "write_authority": "provider_managed",
        "scope": {"workspace_ref": WORKSPACE, "project_ref": PROJECT, "surface_ids": [surface]},
        "freshness": {"mode": "revision_bound", "source_revision": "revision:abc123"},
        "lifecycle": {"state": "active", "supersedes": []},
        "retrieval": {"index_required": True, "readback_required": True,
                      "application_receipt_required": True},
        "maintenance": {"writeback_triggers": ["reviewed_candidate"],
                        "closure_policy": "provider_write_then_revision_verified_read",
                        "retirement_authority": "owner:example"},
        "privacy": {"visibility": "private", "raw_content_in_registry": False},
        "provider_scope_ref_digest": hashlib.sha256(SCOPE_REF.encode()).hexdigest()[:16],
    }


def _candidate_scope(corpus):
    scope = dict(corpus["scope"])
    if corpus["freshness"]["mode"] == "revision_bound":
        scope["revision_ref"] = corpus["freshness"]["source_revision"]
    return scope


def _checkpoint(corpus_id="agent_turn_prefs", surface=SURFACE):
    return {"verified": True, "corpus_id": corpus_id, "workspace_ref": WORKSPACE,
            "project_ref": PROJECT, "surface_id": surface,
            "read_authority": "module_scoped", "source_ref": "repository:authority-map"}


def _binding(corpus_id="agent_turn_prefs"):
    return {"corpus_id": corpus_id, "provider_id": "fake_provider",
            "namespace": "reward_memory", "scope_ref": SCOPE_REF, "timeout_seconds": 5}


def _qd(**kw):
    d = {"ok": True, "status_health_ok": True, "decision": "run",
         "lifecycle_phase": "reviewing",
         "recommended_action": "Review and refine.",
         "selected_todo": {"todo_id": "todo:001", "text": "Advance.",
                           "action_kind": "review_refine_merge",
                           "target_key": "pr:test", "claimed_by": "agent:alpha"}}
    d.update(kw)
    return d


class FakeProvider:
    provider_id = "fake_provider"
    def __init__(self, content=None, status="completed"):
        self.content = content
        self.status = status
        self.calls = []
    def retrieve(self, **kw):
        self.calls.append(dict(kw))
        if self.status != "completed":
            return ContextProviderRetrieval(
                provider=self.provider_id, namespace=str(kw["namespace"]),
                status=self.status, query_summary=str(kw["query_summary"]),
                observed_at=str(kw["observed_at"]), search_performed=False,
                read_performed=False, items=(), reason_code="provider_service_unavailable",
                requested_limit=int(kw["max_results"]))
        items = (ContextProviderItem(resource_ref=f"{SCOPE_REF}/guidance.json",
                                      summary="Scoped guidance.",
                                      content=self.content or "{}", score=0.97),) if self.content else ()
        return ContextProviderRetrieval(
            provider=self.provider_id, namespace=str(kw["namespace"]),
            status="completed", query_summary=str(kw["query_summary"]),
            observed_at=str(kw["observed_at"]), search_performed=True,
            read_performed=bool(items), items=items, requested_limit=int(kw["max_results"]))


class TestArchitecture:
    def test_default_off_advisory_only(self):
        arch = build_reward_memory_architecture_packet()
        assert arch["ok"] is True
        assert arch["schema_version"] == "reward_memory_architecture_v0"
        assert arch["status"] == "design_contract"
        assert arch["stage_boundaries"]["stage_3"].startswith("implemented_opt_in")
        assert "confidence_never_increases_authority" in arch["safety_invariants"]
        assert arch["existing_capability_reuse"]["recall_application"]["automatic_recall"] is False
        assert _public_safe(arch)


class TestCorpusRegistry:
    def test_seven_corpora_five_classes(self):
        registry = build_reward_memory_corpus_registry_packet()
        assert registry["schema_version"] == "reward_memory_corpus_registry_v0"
        assert registry["corpus_count"] == 7
        assert set(registry["class_coverage"]) == {
            "run_bound_reward", "hard_policy", "soft_preference",
            "procedural_experience", "working_context"}
        assert registry["raw_memory_captured"] is False
        for c in registry["corpora"]:
            assert c["privacy"]["raw_content_in_registry"] is False
        assert _public_safe(registry)


class TestCorpusHealth:
    def test_empty_and_retrieval_verified(self):
        c1, o1 = reward_memory_health_case("empty")
        h1 = build_reward_memory_corpus_health_packet(c1, o1)
        assert h1["health_state"] == "empty"
        assert h1["memory_patch_authority"] is False
        assert h1["may_apply_memory"] is False

        c2, o2 = reward_memory_health_case("retrieval-verified")
        h2 = build_reward_memory_corpus_health_packet(c2, o2)
        assert h2["health_state"] == "retrieval_verified"
        assert h2["may_apply_memory"] is True
        assert _public_safe(h1)
        assert _public_safe(h2)


class TestCandidate:
    def test_raw_content_never_captured(self):
        pkt = build_reward_memory_candidate({
            "target_class": "hard_policy",
            "content_summary": "A verified decision outcome.",
            "source": {"source_kind": "verified_decision_outcome",
                       "source_ref": "do:ex-1", "actor_ref": "owner:goal",
                       "actor_role": "verified_decision_owner"},
            "scope": {"workspace_ref": WORKSPACE, "project_ref": PROJECT,
                      "surface_ids": [SURFACE], "revision_ref": "revision:abc123"},
            "reasoning": {"summary": "Verified claim.", "confidence": "high"},
            "guard_context": {"source_freshness": "current", "conflict_state": "clear",
                              "current_artifact_verified": True},
            "requested_action_scopes": [], "raw_content_captured": False,
        }, authority_checkpoint=_checkpoint())
        assert pkt["schema_version"] == "reward_memory_candidate_v0"
        assert pkt["raw_content_captured"] is False
        assert pkt["candidate_persisted"] is False
        assert pkt["provider_write_performed"] is False
        assert _public_safe(pkt)


class TestCandidateReview:
    def _make_candidate(self):
        return build_reward_memory_candidate({
            "target_class": "soft_preference",
            "content_summary": "Keep analysis concise.",
            "source": {"source_kind": "explicit_feedback", "source_ref": "fb:ex-2",
                       "actor_ref": "user:example",
                       "actor_role": "verified_project_owner_or_operator"},
            "scope": _candidate_scope(_corpus()),
            "reasoning": {"summary": "Test.", "confidence": "medium"},
            "guard_context": {"source_freshness": "current", "conflict_state": "clear",
                              "current_artifact_verified": True},
            "requested_action_scopes": [], "raw_content_captured": False,
        })

    def _review(self, decision, **extra):
        return {"decision": decision, "reviewer_ref": "github:user:maintainer",
                "review_ref": f"review:{decision}",
                "reasoning_summary": "Reviewed.", **extra}

    def test_accept_creates_active(self):
        accepted = review_reward_memory_candidate(self._make_candidate(), self._review("accept"))
        assert accepted["effective_decision"] == "accept"
        assert accepted["status"] == "active"
        assert accepted["grants_new_action_authority"] is False

    def test_reject(self):
        rejected = review_reward_memory_candidate(self._make_candidate(), self._review("reject"))
        assert rejected["status"] == "rejected"

    def test_edit_creates_new_candidate(self):
        edited = review_reward_memory_candidate(
            self._make_candidate(),
            self._review("edit", edited_content_summary="Keep concise with linked evidence."))
        assert edited["status"] == "review_ready"

    def test_no_write_retains_state(self):
        nw = review_reward_memory_candidate(self._make_candidate(), self._review("no_write"))
        assert nw["status"] == "no_write"

    def test_guard_blocked_rejects_write(self):
        pkt = build_reward_memory_candidate({
            "target_class": "hard_policy",
            "content_summary": "Policy without verified authority.",
            "source": {"source_kind": "repository_policy", "source_ref": "pol:unverified",
                       "actor_ref": "owner:goal", "actor_role": "verified_decision_owner"},
            "scope": _candidate_scope(_corpus()),
            "reasoning": {"summary": "Missing checkpoint.", "confidence": "low"},
            "guard_context": {"source_freshness": "current", "conflict_state": "clear",
                              "current_artifact_verified": True},
            "requested_action_scopes": [], "raw_content_captured": False,
        }, authority_checkpoint={"verified": False, "source_ref": None,
                                  "actor_ref": "owner:goal",
                                  "actor_role": "verified_decision_owner",
                                  "project_ref": PROJECT, "action_scopes": []})
        assert pkt["status"] == "guard_blocked"
        blocked = review_reward_memory_candidate(pkt, self._review("accept"))
        assert blocked["effective_decision"] == "no_write"
        assert blocked["status"] == "guard_blocked"


class TestActiveRecord:
    def test_scoped_with_lifecycle(self):
        corpus = _corpus()
        pkt = build_reward_memory_candidate({
            "target_class": "soft_preference",
            "content_summary": "Prefer small changes.", "expires_at": "2026-09-01T00:00:00+00:00",
            "source": {"source_kind": "explicit_feedback", "source_ref": "fb:ex-3",
                       "actor_ref": "user:example",
                       "actor_role": "verified_project_owner_or_operator"},
            "scope": _candidate_scope(corpus),
            "reasoning": {"summary": "Scoped preference.", "confidence": "high"},
            "guard_context": {"source_freshness": "current", "conflict_state": "clear",
                              "current_artifact_verified": True},
            "requested_action_scopes": [], "raw_content_captured": False,
        })
        accepted = review_reward_memory_candidate(pkt, {
            "decision": "accept", "reviewer_ref": "github:user:maintainer",
            "review_ref": "review:accept", "reasoning_summary": "Reviewed."})
        active = build_active_reward_memory_record(accepted, corpus, activated_at=OBSERVED_AT)
        assert active["schema_version"] == "reward_memory_active_record_v0"
        assert active["corpus_id"] == "agent_turn_prefs"
        assert active["lifecycle"] == {"state": "active", "expires_at": "2026-09-01T00:00:00+00:00"}
        assert active["provider_write_performed"] is False
        assert _public_safe(active)


class TestTurnSituation:
    def test_prompt_independent_fingerprint(self):
        s1 = build_agent_turn_situation(
            _qd(), goal_id="g:rm", agent_id="agent:alpha",
            turn_instance_id="2026-08-10T12:00:00+00:00",
            workspace_ref=WORKSPACE, project_ref=PROJECT)
        assert s1["schema_version"] == "agent_turn_situation_v0"
        assert s1["user_prompt_included"] is False
        assert "situation_fingerprint" in s1
        assert "turn_recall_id" in s1

        s2 = build_agent_turn_situation(
            _qd(), goal_id="g:rm", agent_id="agent:alpha",
            turn_instance_id="2026-08-10T12:00:00+00:00",
            workspace_ref=WORKSPACE, project_ref=PROJECT)
        assert s1["situation_fingerprint"] == s2["situation_fingerprint"]

        s3 = build_agent_turn_situation(
            _qd(), goal_id="g:rm", agent_id="agent:alpha",
            turn_instance_id="2026-08-10T12:01:00+00:00",
            workspace_ref=WORKSPACE, project_ref=PROJECT)
        assert s1["turn_recall_id"] != s3["turn_recall_id"]
        assert _public_safe(s1)


class TestRecallPreview:
    def test_no_provider_call_guidance_empty(self):
        situation = build_agent_turn_situation(
            _qd(), goal_id="g:rm", agent_id="agent:alpha",
            turn_instance_id="2026-08-10T12:00:00+00:00",
            workspace_ref=WORKSPACE, project_ref=PROJECT)
        preview = build_agent_turn_recall_preview(situation)
        assert preview["status"] == "preview"
        assert preview["provider_call_count"] == 0
        assert preview["context"]["guidance"] == []
        assert preview["execute_required_for_recall"] is True
        assert preview["grants_new_action_authority"] is False
        assert _public_safe(preview)


class TestRecallRequest:
    def test_scoped_and_guarded(self):
        corpus = _corpus()
        request = build_reward_memory_recall_request(corpus, {
            "workspace_ref": WORKSPACE, "project_ref": PROJECT,
            "surface_id": SURFACE, "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [{"query": "guidance", "query_summary": "turn admission"}],
            "limit": 3, "observed_at": OBSERVED_AT,
            "freshness_context": {"source_truth_current": True, "source_revision": "revision:abc123"},
            "conflict_state": "clear", "raw_content_captured": False,
        }, read_authority_checkpoint=_checkpoint())
        assert request["status"] == "ready"
        assert request["guard"]["passed"] is True

    def test_wrong_project_guard_blocked(self):
        corpus = _corpus()
        blocked = build_reward_memory_recall_request(corpus, {
            "workspace_ref": WORKSPACE, "project_ref": "repository:other",
            "surface_id": SURFACE, "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [{"query": "guidance", "query_summary": "turn admission"}],
            "limit": 3, "observed_at": OBSERVED_AT,
            "freshness_context": {"source_truth_current": True, "source_revision": "revision:abc123"},
            "conflict_state": "clear", "raw_content_captured": False,
        }, read_authority_checkpoint=_checkpoint())
        assert blocked["status"] == "guard_blocked"
        assert "project_scope_mismatch" in blocked["guard"]["reason_codes"]


class TestRecallExecution:
    def test_execute_and_apply_with_fake_provider(self):
        corpus = _corpus()
        pkt = build_reward_memory_candidate({
            "target_class": "soft_preference",
            "content_summary": "Prefer small reversible changes.",
            "source": {"source_kind": "explicit_feedback", "source_ref": "fb:ex-4",
                       "actor_ref": "user:example",
                       "actor_role": "verified_project_owner_or_operator"},
            "scope": _candidate_scope(corpus),
            "reasoning": {"summary": "Preference.", "confidence": "high"},
            "guard_context": {"source_freshness": "current", "conflict_state": "clear",
                              "current_artifact_verified": True},
            "requested_action_scopes": [], "raw_content_captured": False,
        })
        accepted = review_reward_memory_candidate(pkt, {
            "decision": "accept", "reviewer_ref": "github:user:maintainer",
            "review_ref": "review:accept", "reasoning_summary": "Reviewed."})
        active = build_active_reward_memory_record(accepted, corpus, activated_at=OBSERVED_AT)

        request = build_reward_memory_recall_request(corpus, {
            "workspace_ref": WORKSPACE, "project_ref": PROJECT,
            "surface_id": SURFACE, "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [{"query": "guidance", "query_summary": "turn admission"}],
            "limit": 3, "observed_at": OBSERVED_AT,
            "freshness_context": {"source_truth_current": True, "source_revision": "revision:abc123"},
            "conflict_state": "clear", "raw_content_captured": False,
        }, read_authority_checkpoint=_checkpoint())

        provider = FakeProvider(json.dumps(active, ensure_ascii=False))
        session = execute_reward_memory_recall(request, provider_binding=_binding(), provider=provider)
        assert session.public_packet["status"] == "completed"
        assert session.public_packet["result_count"] == 1

        ctx = {"guidance": []}
        applied = apply_reward_memory_recall(ctx, session, application_id="recall:test",
            apply_memory=lambda base, items: {
                "outcome": "applied",
                "output": dict(base) | {"guidance": [{
                    "candidate_ref": i.candidate_ref, "target_class": i.target_class,
                    "content_summary": i.content_summary} for i in items]},
                "memory_refs": [i.memory_ref for i in items],
                "reasoning_summary": "Guidance injected.",
                "current_artifact_verified": True})
        assert applied["status"] == "applied"
        assert len(applied["output"]["guidance"]) == 1
        assert _public_safe(applied)

    def test_provider_unavailable_fail_open(self):
        corpus = _corpus()
        request = build_reward_memory_recall_request(corpus, {
            "workspace_ref": WORKSPACE, "project_ref": PROJECT,
            "surface_id": SURFACE, "revision_ref": "revision:abc123",
            "mode": "function_boundary",
            "queries": [{"query": "guidance", "query_summary": "turn admission"}],
            "limit": 3, "observed_at": OBSERVED_AT,
            "freshness_context": {"source_truth_current": True, "source_revision": "revision:abc123"},
            "conflict_state": "clear", "raw_content_captured": False,
        }, read_authority_checkpoint=_checkpoint())
        bad = FakeProvider(status="unavailable")
        session = execute_reward_memory_recall(request, provider_binding=_binding(), provider=bad)
        assert session.public_packet["status"] == "provider_unavailable"
        fail_open = apply_reward_memory_recall({"guidance": []}, session, application_id="recall:fail")
        assert fail_open["status"] == "not_available"
        assert fail_open["fail_open_preserved_base"] is True

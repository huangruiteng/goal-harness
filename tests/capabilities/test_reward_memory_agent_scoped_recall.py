from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from loopx.capabilities.context_providers.base import (
    ContextProviderItem,
    ContextProviderRetrieval,
    ContextProviderSync,
)
from loopx.capabilities.reward_memory.application import (
    apply_reward_memory_recall,
    build_reward_memory_recall_request,
    execute_reward_memory_recall,
)
from loopx.capabilities.reward_memory.scoped_feedback import (
    ingest_scoped_feedback_reward_memory_event,
)


OBSERVED_AT = "2026-08-02T12:00:00+00:00"
WORKSPACE = "workspace:example"
PROJECT = "project:example"
USER = "user:owner"
PEER = "agent:quality-reviewer"
SESSION = "task:integration-loop"
SURFACE = "agent_workflow.post_merge"
SCOPE_REF = "viking://resources/reward-memory/agent-scoped-steering"


class MemoryProvider:
    provider_id = "fake_provider"

    def __init__(self, *, return_on_query: str | None = None) -> None:
        self.resources: dict[str, str] = {}
        self.return_on_query = return_on_query
        self.sync_calls = 0
        self.retrieve_calls = 0

    def sync(self, **kwargs: Any) -> ContextProviderSync:
        self.sync_calls += 1
        source, target = kwargs["resources"][0]
        self.resources[target] = Path(source).read_text(encoding="utf-8")
        return ContextProviderSync(
            provider=self.provider_id,
            namespace=str(kwargs["namespace"]),
            status="completed",
            observed_at=str(kwargs["observed_at"]),
            requested_count=1,
            completed_count=1,
            write_count=1,
            result_refs=(target,),
        )

    def retrieve(self, **kwargs: Any) -> ContextProviderRetrieval:
        self.retrieve_calls += 1
        include = self.return_on_query in (None, str(kwargs["query"]))
        items = (
            tuple(
                ContextProviderItem(
                    resource_ref=target,
                    summary="Agent-scoped temporary steering memory.",
                    content=content,
                    score=0.95,
                )
                for target, content in self.resources.items()
            )
            if include
            else ()
        )
        return ContextProviderRetrieval(
            provider=self.provider_id,
            namespace=str(kwargs["namespace"]),
            status="completed",
            query_summary=str(kwargs["query_summary"]),
            observed_at=str(kwargs["observed_at"]),
            search_performed=True,
            read_performed=True,
            items=items,
            requested_limit=int(kwargs["max_results"]),
        )


def corpus(*, lifecycle: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "corpus_id": "agent_scoped_steering",
        "class_id": "soft_preference",
        "provider_id": "fake_provider",
        "owner_ref": "agent:quality-reviewer",
        "source_of_truth": "reviewed_owner_feedback",
        "read_authority": "actor_scoped",
        "write_authority": "provider_managed",
        "scope": {
            "workspace_ref": WORKSPACE,
            "project_ref": PROJECT,
            "user_ref": USER,
            "peer_ref": PEER,
            "session_ref": SESSION,
            "surface_ids": [SURFACE],
        },
        "freshness": {"mode": "time_bound", "max_age_seconds": 3600},
        "lifecycle": lifecycle or {"state": "active", "supersedes": []},
        "retrieval": {
            "index_required": True,
            "readback_required": True,
            "application_receipt_required": True,
        },
        "maintenance": {
            "writeback_triggers": ["reviewed_owner_feedback"],
            "closure_policy": "write_exact_readback_then_recall",
            "retirement_authority": "agent:quality-reviewer",
        },
        "privacy": {"visibility": "private", "raw_content_in_registry": False},
        "provider_scope_ref_digest": hashlib.sha256(
            SCOPE_REF.encode("utf-8")
        ).hexdigest()[:16],
    }


def standing_policy() -> dict[str, Any]:
    return {
        "schema_version": "reward_memory_standing_policy_v0",
        "policy_id": "policy:agent-scoped-steering",
        "enabled": True,
        "auto_activate": True,
        "owner_ref": "agent:quality-reviewer",
        "reviewer_ref": "user:owner",
        "authority_source_ref": "feedback:owner:agent-steering",
        "scope": dict(corpus()["scope"]),
        "allowed_target_classes": ["soft_preference"],
        "allowed_source_kinds": ["owner_correction"],
        "allowed_actor_roles": ["verified_project_owner_or_operator"],
        "allowed_action_scopes": [],
        "raw_content_captured": False,
    }


def event() -> dict[str, Any]:
    return {
        "schema_version": "scoped_feedback_reward_memory_event_v0",
        "feedback_ref": "feedback:agent:post-merge-handoff",
        "workspace_ref": WORKSPACE,
        "project_ref": PROJECT,
        "user_ref": USER,
        "peer_ref": PEER,
        "session_ref": SESSION,
        "surface_id": SURFACE,
        "revision_ref": None,
        "target_class": "soft_preference",
        "content_summary": (
            "After integrating a related change, summarize the refinement to the "
            "originating task and request an integration-branch refresh."
        ),
        "source": {
            "source_kind": "owner_correction",
            "source_ref": "feedback:owner:agent-steering",
            "actor_ref": "user:owner",
            "actor_role": "verified_project_owner_or_operator",
        },
        "reasoning": {
            "summary": "The preference is temporary and specific to one agent task.",
            "confidence": "high",
        },
        "guard_context": {
            "source_freshness": "current",
            "conflict_state": "clear",
            "current_artifact_verified": True,
        },
        "requested_action_scopes": [],
        "raw_content_captured": False,
    }


def binding() -> dict[str, Any]:
    return {
        "corpus_id": "agent_scoped_steering",
        "provider_id": "fake_provider",
        "namespace": "reward_memory",
        "scope_ref": SCOPE_REF,
        "timeout_seconds": 5,
    }


def checkpoint() -> dict[str, Any]:
    return {
        "verified": True,
        "corpus_id": "agent_scoped_steering",
        "workspace_ref": WORKSPACE,
        "project_ref": PROJECT,
        "user_ref": USER,
        "peer_ref": PEER,
        "session_ref": SESSION,
        "surface_id": SURFACE,
        "read_authority": "actor_scoped",
        "source_ref": "feedback:owner:agent-steering",
    }


def recall_request(
    *,
    selected_corpus: dict[str, Any] | None = None,
    user_ref: str | None = USER,
    peer_ref: str | None = PEER,
    session_ref: str | None = SESSION,
    age_seconds: int = 30,
    mode: str = "function_boundary",
    queries: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return build_reward_memory_recall_request(
        selected_corpus or corpus(),
        {
            "workspace_ref": WORKSPACE,
            "project_ref": PROJECT,
            "user_ref": user_ref,
            "peer_ref": peer_ref,
            "session_ref": session_ref,
            "surface_id": SURFACE,
            "revision_ref": None,
            "mode": mode,
            "queries": queries
            or [
                {
                    "query": "What should happen after a related merge?",
                    "query_summary": "post-merge task coordination",
                }
            ],
            "limit": 5,
            "observed_at": OBSERVED_AT,
            "freshness_context": {
                "source_truth_current": True,
                "source_revision": None,
                "age_seconds": age_seconds,
            },
            "conflict_state": "clear",
            "raw_content_captured": False,
        },
        read_authority_checkpoint=checkpoint(),
    )


def active_record(*, scope_changes: dict[str, Any] | None = None) -> dict[str, Any]:
    scope = dict(corpus()["scope"])
    scope.update(scope_changes or {})
    return {
        "schema_version": "reward_memory_active_record_v0",
        "corpus_id": "agent_scoped_steering",
        "candidate_ref": "candidate:agent-scoped-steering",
        "target_class": "soft_preference",
        "content_summary": event()["content_summary"],
        "scope": scope,
        "lifecycle": {"state": "active"},
    }


def test_scoped_feedback_ingest_and_recall_preserve_agent_task_scope() -> None:
    provider = MemoryProvider()

    receipt = ingest_scoped_feedback_reward_memory_event(
        event(),
        corpus=corpus(),
        standing_policy=standing_policy(),
        provider_binding=binding(),
        observed_at=OBSERVED_AT,
        execute=True,
        provider=provider,
    )
    session = execute_reward_memory_recall(
        recall_request(),
        provider_binding=binding(),
        provider=provider,
    )
    applied = apply_reward_memory_recall(
        {"next": "finish"},
        session,
        application_id="application:agent-scoped-steering",
        apply_memory=lambda base, items: {
            "outcome": "applied",
            "output": {"next": "handoff_then_refresh"},
            "memory_refs": [item.memory_ref for item in items],
            "reasoning_summary": "Applied the matching temporary steering memory.",
            "current_artifact_verified": True,
        },
    )

    assert receipt["status"] == "activated"
    assert receipt["exact_readback_verified"] is True
    assert session.public_packet["status"] == "completed"
    assert applied["status"] == "applied"
    assert applied["receipt"]["grants_new_action_authority"] is False


def test_scoped_feedback_wrong_peer_is_rejected_before_provider_write() -> None:
    provider = MemoryProvider()

    receipt = ingest_scoped_feedback_reward_memory_event(
        event() | {"peer_ref": "agent:other"},
        corpus=corpus(),
        standing_policy=standing_policy(),
        provider_binding=binding(),
        observed_at=OBSERVED_AT,
        execute=True,
        provider=provider,
    )

    assert receipt["status"] == "guard_blocked"
    assert "candidate_peer_ref_policy_mismatch" in receipt["guard"]["reason_codes"]
    assert "candidate_peer_ref_corpus_mismatch" in receipt["guard"]["reason_codes"]
    assert provider.sync_calls == 0


@pytest.mark.parametrize(
    ("scope_field", "request_value", "reason_code"),
    [
        ("user_ref", "user:other", "user_ref_scope_mismatch"),
        ("peer_ref", "agent:other", "peer_ref_scope_mismatch"),
        ("session_ref", "task:other", "session_ref_scope_mismatch"),
        ("session_ref", None, "session_ref_scope_mismatch"),
    ],
)
def test_wrong_or_missing_agent_task_scope_blocks_before_provider(
    scope_field: str,
    request_value: str | None,
    reason_code: str,
) -> None:
    provider = MemoryProvider()
    request_scope = {
        "user_ref": USER,
        "peer_ref": PEER,
        "session_ref": SESSION,
    }
    request_scope[scope_field] = request_value

    request = recall_request(**request_scope)
    session = execute_reward_memory_recall(
        request,
        provider_binding=binding(),
        provider=provider,
    )

    assert request["status"] == "guard_blocked"
    assert reason_code in request["guard"]["reason_codes"]
    assert session.public_packet["status"] == "guard_blocked"
    assert provider.retrieve_calls == 0


@pytest.mark.parametrize(
    "scope_changes",
    [
        {"user_ref": "user:other"},
        {"peer_ref": "agent:other"},
        {"session_ref": "task:other"},
    ],
)
def test_provider_result_cannot_cross_agent_task_scope(
    scope_changes: dict[str, Any],
) -> None:
    provider = MemoryProvider()
    provider.resources[f"{SCOPE_REF}/memory.json"] = json.dumps(
        active_record(scope_changes=scope_changes)
    )

    session = execute_reward_memory_recall(
        recall_request(),
        provider_binding=binding(),
        provider=provider,
    )

    assert session.public_packet["status"] == "empty"
    assert session.public_packet["result_count"] == 0
    assert provider.retrieve_calls == 1


@pytest.mark.parametrize(
    ("selected_corpus", "age_seconds", "reason_code"),
    [
        (None, 3601, "source_age_exceeded"),
        (
            corpus(
                lifecycle={
                    "state": "superseded",
                    "supersedes": [],
                    "superseded_by": "replacement_memory",
                }
            ),
            30,
            "corpus_not_active",
        ),
    ],
)
def test_expired_or_superseded_memory_blocks_before_provider(
    selected_corpus: dict[str, Any] | None,
    age_seconds: int,
    reason_code: str,
) -> None:
    provider = MemoryProvider()

    request = recall_request(
        selected_corpus=selected_corpus,
        age_seconds=age_seconds,
    )
    session = execute_reward_memory_recall(
        request,
        provider_binding=binding(),
        provider=provider,
    )

    assert request["status"] == "guard_blocked"
    assert reason_code in request["guard"]["reason_codes"]
    assert session.public_packet["status"] == "guard_blocked"
    assert provider.retrieve_calls == 0


def test_bounded_agentic_queries_find_subtle_semantics_and_ignore_unrelated() -> None:
    queries = [
        {"query": "Which checks passed?", "query_summary": "validation status"},
        {"query": "Who owns the PR?", "query_summary": "PR ownership"},
        {
            "query": "Should the originating task refresh its integration branch?",
            "query_summary": "post-merge coordination semantics",
        },
    ]
    matching = MemoryProvider(return_on_query=queries[-1]["query"])
    matching.resources[f"{SCOPE_REF}/memory.json"] = json.dumps(active_record())

    found = execute_reward_memory_recall(
        recall_request(mode="bounded_agentic_search", queries=queries),
        provider_binding=binding(),
        provider=matching,
    )
    unrelated = MemoryProvider(return_on_query="never matches")
    unrelated.resources[f"{SCOPE_REF}/memory.json"] = json.dumps(active_record())
    empty = execute_reward_memory_recall(
        recall_request(mode="bounded_agentic_search", queries=queries),
        provider_binding=binding(),
        provider=unrelated,
    )

    assert found.public_packet["status"] == "completed"
    assert found.public_packet["provider_call_count"] == 3
    assert empty.public_packet["status"] == "empty"
    assert empty.public_packet["provider_call_count"] == 3

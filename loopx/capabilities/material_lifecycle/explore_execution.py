"""Bounded provider execution for Material Lifecycle exploration intents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..context_providers.base import (
    ContextProvider,
    ContextProviderItem,
    ContextProviderRetrieval,
    opaque_provider_ref,
)
from ._validation import (
    capability_contract,
    compact_token,
    iso_timestamp,
    packet_ref,
    positive_int,
)
from .decision_planning import (
    MATERIAL_EXPLORE_INTENT_SCHEMA_VERSION,
    build_material_explore_intent,
)

MATERIAL_EXPLORE_EXECUTION_RECEIPT_SCHEMA_VERSION = (
    "material_explore_execution_receipt_v0"
)
MAX_MATERIAL_EXPLORE_QUERY_LENGTH = 500


@dataclass(frozen=True)
class MaterialExploreCandidate:
    """One transient provider hit that still requires independent exact read."""

    topic_ref: str
    provider_ref: str
    score: float | None
    resource_ref: str = field(repr=False)
    content: str = field(repr=False)


@dataclass(frozen=True)
class MaterialExploreExecution:
    """Public-safe execution receipt plus private in-process candidates."""

    receipt: Mapping[str, Any]
    candidates: tuple[MaterialExploreCandidate, ...] = field(
        default_factory=tuple,
        repr=False,
    )

    def public_receipt(self) -> dict[str, Any]:
        return dict(self.receipt)


def _canonical_intent(intent: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(intent, Mapping):
        raise TypeError("explore_intent must be an object")
    if intent.get("schema_version") != MATERIAL_EXPLORE_INTENT_SCHEMA_VERSION:
        raise ValueError("explore_intent must use material_explore_intent_v0")
    constraints = intent.get("constraints")
    if not isinstance(constraints, Mapping):
        raise ValueError("explore_intent constraints must be an object")
    rebuilt = build_material_explore_intent(
        goal_id=intent.get("goal_id"),
        intent_id=intent.get("intent_id"),
        inventory_ref=intent.get("inventory_ref"),
        decision_evidence_ref=intent.get("decision_evidence_ref"),
        policy_ref=intent.get("policy_ref"),
        observed_at=intent.get("observed_at"),
        max_explore_topics=constraints.get("max_explore_topics"),
        max_provider_calls=constraints.get("max_provider_calls"),
        max_new_candidates=constraints.get("max_new_candidates"),
        stop_condition=constraints.get("stop_condition"),
        topics=intent.get("topics"),
    )
    if dict(intent) != rebuilt:
        raise ValueError("explore_intent intent_ref or canonical payload does not match")
    return rebuilt


def _query_map(
    queries: Mapping[str, str],
    *,
    topic_refs: tuple[str, ...],
) -> dict[str, str]:
    if not isinstance(queries, Mapping):
        raise TypeError("queries must be a mapping")
    normalized: dict[str, str] = {}
    for topic_ref in topic_refs:
        query = " ".join(str(queries.get(topic_ref) or "").split())
        if not query:
            raise ValueError(f"query is required for topic {topic_ref}")
        if len(query) > MAX_MATERIAL_EXPLORE_QUERY_LENGTH:
            raise ValueError(
                f"query for topic {topic_ref} exceeds "
                f"{MAX_MATERIAL_EXPLORE_QUERY_LENGTH} characters"
            )
        normalized[topic_ref] = query
    unexpected = sorted(set(queries) - set(topic_refs))
    if unexpected:
        raise ValueError("queries contains topics outside the explore intent")
    return normalized


def execute_material_explore_intent(
    *,
    provider: ContextProvider,
    explore_intent: Mapping[str, Any],
    queries: Mapping[str, str],
    namespace: str,
    scope_ref: str,
    execution_authority_ref: str,
    observed_at: str,
    timeout_seconds: float,
) -> MaterialExploreExecution:
    """Execute bounded read-only recall without authorizing material changes.

    Raw queries, resource locations, and content remain in-process. The caller
    must independently exact-read a managed material authority before using a
    candidate in rerank or new-candidate proposals.
    """

    intent = _canonical_intent(explore_intent)
    goal_id = compact_token(intent["goal_id"], field="goal_id")
    authority_ref = compact_token(
        execution_authority_ref,
        field="execution_authority_ref",
    )
    normalized_namespace = compact_token(namespace, field="namespace")
    normalized_scope_ref = str(scope_ref or "").strip()
    if not normalized_scope_ref:
        raise ValueError("scope_ref is required")
    if len(normalized_scope_ref) > 500:
        raise ValueError("scope_ref must be at most 500 characters")
    timestamp = iso_timestamp(observed_at, field="observed_at")
    if isinstance(timeout_seconds, bool):
        raise TypeError("timeout_seconds must be a positive number")
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError) as exc:
        raise TypeError("timeout_seconds must be a positive number") from exc
    if timeout <= 0:
        raise ValueError("timeout_seconds must be a positive number")

    topics = tuple(
        compact_token(topic["topic_ref"], field="topic_ref")
        for topic in intent["topics"]
    )
    bounded_queries = _query_map(queries, topic_refs=topics)
    constraints = intent["constraints"]
    max_calls = positive_int(
        constraints["max_provider_calls"],
        field="max_provider_calls",
    )
    max_candidates = positive_int(
        constraints["max_new_candidates"],
        field="max_new_candidates",
    )
    if len(topics) > max_calls:
        raise ValueError("explore_intent exceeds its provider call budget")

    provider_id = compact_token(
        getattr(provider, "provider_id", ""),
        field="provider",
    )
    candidates: list[MaterialExploreCandidate] = []
    topic_receipts: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    completed_calls = 0
    attempted_calls = 0

    for topic_ref in topics:
        remaining = max_candidates - len(candidates)
        if remaining <= 0:
            topic_receipts.append(
                {
                    "topic_ref": topic_ref,
                    "status": "budget_exhausted",
                    "reason_code": "candidate_budget_exhausted",
                    "requested_limit": 0,
                    "result_count": 0,
                    "provider_refs": [],
                }
            )
            continue
        try:
            attempted_calls += 1
            retrieval = provider.retrieve(
                namespace=normalized_namespace,
                scope_ref=normalized_scope_ref,
                query=bounded_queries[topic_ref],
                query_summary=f"material explore {topic_ref}",
                max_results=remaining,
                timeout_seconds=timeout,
                observed_at=timestamp,
            )
        except Exception:
            retrieval = None

        contract_valid = (
            isinstance(retrieval, ContextProviderRetrieval)
            and retrieval.provider == provider_id
            and retrieval.namespace == normalized_namespace
            and len(retrieval.items) <= remaining
            and all(isinstance(item, ContextProviderItem) for item in retrieval.items)
        )
        if contract_valid:
            try:
                retrieval.public_packet()
            except Exception:
                contract_valid = False
        if not contract_valid or retrieval is None:
            topic_receipts.append(
                {
                    "topic_ref": topic_ref,
                    "status": "unavailable",
                    "reason_code": "provider_retrieval_failed",
                    "requested_limit": remaining,
                    "result_count": 0,
                    "provider_refs": [],
                }
            )
            continue

        if retrieval.status == "completed":
            completed_calls += 1
        provider_refs: list[str] = []
        for item in retrieval.items:
            provider_ref = opaque_provider_ref(
                provider=retrieval.provider,
                namespace=retrieval.namespace,
                resource_ref=item.resource_ref,
            )
            if provider_ref in seen_refs:
                continue
            seen_refs.add(provider_ref)
            provider_refs.append(provider_ref)
            candidates.append(
                MaterialExploreCandidate(
                    topic_ref=topic_ref,
                    provider_ref=provider_ref,
                    score=item.score,
                    resource_ref=item.resource_ref,
                    content=item.content,
                )
            )
            if len(candidates) >= max_candidates:
                break
        topic_receipt = {
            "topic_ref": topic_ref,
            "status": retrieval.status,
            "requested_limit": remaining,
            "result_count": len(provider_refs),
            "provider_refs": sorted(provider_refs),
        }
        if retrieval.reason_code:
            topic_receipt["reason_code"] = compact_token(
                retrieval.reason_code,
                field="reason_code",
            )
        topic_receipts.append(topic_receipt)

    unavailable_topics = sum(
        topic["status"] == "unavailable" for topic in topic_receipts
    )
    status = (
        "completed"
        if completed_calls == attempted_calls and not unavailable_topics
        else "partial"
        if completed_calls
        else "unavailable"
    )
    receipt: dict[str, Any] = {
        "schema_version": MATERIAL_EXPLORE_EXECUTION_RECEIPT_SCHEMA_VERSION,
        "goal_id": goal_id,
        "intent_ref": compact_token(intent["intent_ref"], field="intent_ref"),
        "execution_authority_ref": authority_ref,
        "provider": provider_id,
        "namespace": normalized_namespace,
        "observed_at": timestamp,
        "visibility": "public_safe",
        "capability": capability_contract(packet_role="explore_execution"),
        "status": status,
        "provider_call_count": attempted_calls,
        "completed_call_count": completed_calls,
        "candidate_count": len(candidates),
        "topics": topic_receipts,
        "exact_read_required_for_promotion": True,
        "rerank_authorized": False,
        "new_candidate_apply_authorized": False,
        "source_cursor_apply_authorized": False,
        "provider_fail_open": True,
        "external_writes_performed": False,
        "raw_queries_captured": False,
        "raw_content_captured": False,
        "private_locations_captured": False,
        "credentials_captured": False,
    }
    receipt["receipt_ref"] = packet_ref("material-explore-execution", receipt)
    return MaterialExploreExecution(
        receipt=receipt,
        candidates=tuple(candidates),
    )

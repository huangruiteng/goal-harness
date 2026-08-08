from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .evidence_packet import (
    _compact_public_text_list,
    _compact_public_token,
)
from .research_state import build_research_decision_candidates
from ...rollout_event_log import build_rollout_event


AUTO_RESEARCH_TERMINAL_DECISION_SCHEMA_VERSION = (
    "auto_research_terminal_decision_v0"
)
AUTO_RESEARCH_PEER_REVIEW_SCHEMA_VERSION = "auto_research_peer_review_v0"
AUTO_RESEARCH_TERMINAL_RESULT_QUERY_SCHEMA_VERSION = (
    "auto_research_terminal_result_query_v0"
)

TERMINAL_OUTCOMES = {"promoted", "retired"}
RETIREMENT_REASONS = {
    "contradicted",
    "duplicate",
    "operator_rejected",
    "retry_exhausted",
    "superseded",
}
PEER_REVIEW_VERDICTS = {"approve", "needs_more_evidence", "reject"}


def _canonical_digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def research_evidence_graph_revision(evidence_graph: Mapping[str, Any]) -> str:
    return f"sha256:{_canonical_digest(dict(evidence_graph))}"


def hypothesis_evidence_revision(
    evidence_graph: Mapping[str, Any],
    hypothesis_id: str,
) -> str:
    node = _hypothesis_node(evidence_graph, hypothesis_id)
    scoped_evidence = {
        "goal_id": str(evidence_graph.get("goal_id") or ""),
        "metric": dict(evidence_graph.get("metric") or {}),
        "node": node,
    }
    return f"sha256:{_canonical_digest(scoped_evidence)}"


def _stable_ref(prefix: str, values: Sequence[object]) -> str:
    encoded = json.dumps(
        [str(value or "") for value in values],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:16]}"


def _event_classification(event: Mapping[str, Any]) -> str:
    return str(event.get("classification") or "")


def _event_details(event: Mapping[str, Any]) -> dict[str, Any]:
    details = event.get("details")
    return dict(details) if isinstance(details, Mapping) else {}


def _event_decision_ref(event: Mapping[str, Any]) -> str:
    causality = event.get("causality")
    if not isinstance(causality, Mapping):
        return ""
    return str(causality.get("decision_id") or "")


def _hypothesis_node(
    evidence_graph: Mapping[str, Any],
    hypothesis_id: str,
) -> dict[str, Any]:
    matches = [
        dict(node)
        for node in evidence_graph.get("nodes") or []
        if isinstance(node, Mapping)
        and str(node.get("hypothesis_id") or "") == hypothesis_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"hypothesis_id must resolve to exactly one evidence graph node: {hypothesis_id}"
        )
    return matches[0]


def _terminal_decision_events(
    rollout_events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(event)
        for event in rollout_events
        if _event_classification(event)
        == AUTO_RESEARCH_TERMINAL_DECISION_SCHEMA_VERSION
    ]


def _peer_review_events(
    rollout_events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        dict(event)
        for event in rollout_events
        if _event_classification(event) == AUTO_RESEARCH_PEER_REVIEW_SCHEMA_VERSION
    ]


def _decision_view(event: Mapping[str, Any]) -> dict[str, Any]:
    details = _event_details(event)
    return {
        "decision_ref": _event_decision_ref(event),
        "event_id": str(event.get("event_id") or ""),
        "recorded_at": str(event.get("recorded_at") or ""),
        "goal_id": str(event.get("goal_id") or ""),
        "hypothesis_id": str(details.get("hypothesis_id") or ""),
        "outcome": str(details.get("outcome") or ""),
        "reason": str(details.get("reason") or ""),
        "decided_by": str(event.get("agent_id") or ""),
        "evidence_graph_revision": str(
            details.get("evidence_graph_revision") or ""
        ),
        "hypothesis_evidence_revision": str(
            details.get("hypothesis_evidence_revision") or ""
        ),
        "evidence_refs": list(event.get("artifact_refs") or []),
    }


def _review_view(
    event: Mapping[str, Any],
    *,
    registered_agent_ids: Sequence[str],
) -> dict[str, Any]:
    details = _event_details(event)
    reviewer_agent_id = str(event.get("agent_id") or "")
    decision_agent_id = str(details.get("decision_agent_id") or "")
    producer_agent_id = str(details.get("producer_agent_id") or "")
    registered = set(registered_agent_ids)
    independently_separated = reviewer_agent_id not in {
        decision_agent_id,
        producer_agent_id,
    }
    return {
        "review_ref": _event_decision_ref(event),
        "event_id": str(event.get("event_id") or ""),
        "recorded_at": str(event.get("recorded_at") or ""),
        "goal_id": str(event.get("goal_id") or ""),
        "hypothesis_id": str(details.get("hypothesis_id") or ""),
        "decision_ref": str(details.get("decision_ref") or ""),
        "verdict": str(details.get("verdict") or ""),
        "reviewer_agent_id": reviewer_agent_id,
        "decision_agent_id": decision_agent_id,
        "producer_agent_id": producer_agent_id,
        "independent": bool(details.get("independent"))
        and reviewer_agent_id in registered
        and independently_separated,
        "evidence_graph_revision": str(
            details.get("evidence_graph_revision") or ""
        ),
        "hypothesis_evidence_revision": str(
            details.get("hypothesis_evidence_revision") or ""
        ),
        "evidence_refs": list(event.get("artifact_refs") or []),
    }


def _validate_terminal_decision(
    *,
    evidence_graph: Mapping[str, Any],
    hypothesis_id: str,
    outcome: str,
    reason: str,
) -> dict[str, Any]:
    node = _hypothesis_node(evidence_graph, hypothesis_id)
    normalized_outcome = _compact_public_token(outcome, field="outcome")
    if normalized_outcome not in TERMINAL_OUTCOMES:
        raise ValueError(
            "outcome must be one of: " + ", ".join(sorted(TERMINAL_OUTCOMES))
        )
    normalized_reason = _compact_public_token(reason, field="reason")
    decisions = build_research_decision_candidates(dict(evidence_graph))
    validated_ids = {
        str(item.get("hypothesis_id") or "")
        for item in decisions.get("validated_promotion_candidates") or []
    }
    retirement_ids = {
        str(item.get("hypothesis_id") or "")
        for item in decisions.get("retirement_candidates") or []
    }
    if normalized_outcome == "promoted":
        if normalized_reason != "holdout_validated":
            raise ValueError("promoted decisions require reason=holdout_validated")
        if hypothesis_id not in validated_ids:
            raise ValueError(
                "promoted decisions require a validated holdout promotion candidate"
            )
    else:
        if normalized_reason not in RETIREMENT_REASONS:
            raise ValueError(
                "retired decision reason must be one of: "
                + ", ".join(sorted(RETIREMENT_REASONS))
            )
        if normalized_reason == "contradicted" and hypothesis_id not in retirement_ids:
            raise ValueError(
                "retired reason=contradicted requires negative or guardrail evidence"
            )
    return node


def build_terminal_decision_event(
    *,
    evidence_graph: Mapping[str, Any],
    hypothesis_id: str,
    outcome: str,
    reason: str,
    decided_by: str,
    evidence_refs: Sequence[str] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    hypothesis = _compact_public_token(hypothesis_id, field="hypothesis_id")
    decider = _compact_public_token(decided_by, field="decided_by")
    node = _validate_terminal_decision(
        evidence_graph=evidence_graph,
        hypothesis_id=hypothesis,
        outcome=outcome,
        reason=reason,
    )
    normalized_outcome = _compact_public_token(outcome, field="outcome")
    normalized_reason = _compact_public_token(reason, field="reason")
    graph_revision = research_evidence_graph_revision(evidence_graph)
    hypothesis_revision = hypothesis_evidence_revision(
        evidence_graph,
        hypothesis,
    )
    refs = _compact_public_text_list(evidence_refs, field="evidence_refs")
    decision_ref = _stable_ref(
        "research_decision",
        [
            evidence_graph.get("goal_id"),
            hypothesis,
            hypothesis_revision,
        ],
    )
    return build_rollout_event(
        goal_id=str(evidence_graph.get("goal_id") or ""),
        event_kind="validation",
        agent_id=decider,
        todo_id=str(node.get("todo_id") or ""),
        agent_role="evaluator_promoter",
        decision_id=decision_ref,
        from_state=str(node.get("status") or ""),
        to_state=normalized_outcome,
        status=normalized_outcome,
        classification=AUTO_RESEARCH_TERMINAL_DECISION_SCHEMA_VERSION,
        labels=[
            "auto_research",
            "terminal_decision",
            normalized_outcome,
            normalized_reason,
        ],
        summary=(
            f"Auto Research terminal decision {hypothesis}: "
            f"{normalized_outcome} ({normalized_reason})."
        ),
        artifact_refs=refs,
        details={
            "hypothesis_id": hypothesis,
            "outcome": normalized_outcome,
            "reason": normalized_reason,
            "evidence_graph_revision": graph_revision,
            "hypothesis_evidence_revision": hypothesis_revision,
        },
        recorded_at=recorded_at,
    )


def _current_terminal_decision(
    *,
    rollout_events: Sequence[Mapping[str, Any]],
    hypothesis_id: str,
    hypothesis_evidence_revision: str,
) -> dict[str, Any]:
    current = [
        _decision_view(event)
        for event in _terminal_decision_events(rollout_events)
        if str(_event_details(event).get("hypothesis_id") or "") == hypothesis_id
        and str(
            _event_details(event).get("hypothesis_evidence_revision") or ""
        )
        == hypothesis_evidence_revision
    ]
    signatures = {
        (
            item["decision_ref"],
            item["outcome"],
            item["reason"],
            item["decided_by"],
        )
        for item in current
    }
    if len(signatures) > 1:
        raise ValueError(
            f"conflicting terminal decisions for current evidence revision: {hypothesis_id}"
        )
    if not current:
        raise ValueError(
            f"no terminal decision exists for current evidence revision: {hypothesis_id}"
        )
    return current[-1]


def build_peer_review_event(
    *,
    evidence_graph: Mapping[str, Any],
    rollout_events: Sequence[Mapping[str, Any]],
    hypothesis_id: str,
    reviewer_agent_id: str,
    verdict: str,
    evidence_refs: Sequence[str] | None = None,
    require_independent: bool = False,
    registered_agent_ids: Sequence[str] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    hypothesis = _compact_public_token(hypothesis_id, field="hypothesis_id")
    reviewer = _compact_public_token(
        reviewer_agent_id,
        field="reviewer_agent_id",
    )
    normalized_verdict = _compact_public_token(verdict, field="verdict")
    if normalized_verdict not in PEER_REVIEW_VERDICTS:
        raise ValueError(
            "verdict must be one of: "
            + ", ".join(sorted(PEER_REVIEW_VERDICTS))
        )
    registered = {
        _compact_public_token(agent_id, field="registered_agent_ids[]")
        for agent_id in registered_agent_ids or []
    }
    if reviewer not in registered:
        raise ValueError(
            f"reviewer_agent_id is not registered for this research goal: {reviewer}"
        )
    node = _hypothesis_node(evidence_graph, hypothesis)
    graph_revision = research_evidence_graph_revision(evidence_graph)
    hypothesis_revision = hypothesis_evidence_revision(
        evidence_graph,
        hypothesis,
    )
    decision = _current_terminal_decision(
        rollout_events=rollout_events,
        hypothesis_id=hypothesis,
        hypothesis_evidence_revision=hypothesis_revision,
    )
    producer = str(node.get("claimed_by") or "")
    decision_agent = str(decision.get("decided_by") or "")
    independent = reviewer not in {producer, decision_agent}
    if require_independent and not independent:
        raise ValueError(
            "independent peer review requires a reviewer distinct from both "
            "the hypothesis producer and terminal decision agent"
        )
    refs = _compact_public_text_list(evidence_refs, field="evidence_refs")
    review_ref = _stable_ref(
        "research_review",
        [
            evidence_graph.get("goal_id"),
            hypothesis,
            decision["decision_ref"],
            hypothesis_revision,
            reviewer,
            normalized_verdict,
        ],
    )
    return build_rollout_event(
        goal_id=str(evidence_graph.get("goal_id") or ""),
        event_kind="validation",
        agent_id=reviewer,
        todo_id=str(node.get("todo_id") or ""),
        agent_role="evaluator_promoter",
        decision_id=review_ref,
        source_event_id=str(decision.get("event_id") or ""),
        status=normalized_verdict,
        classification=AUTO_RESEARCH_PEER_REVIEW_SCHEMA_VERSION,
        labels=[
            "auto_research",
            "peer_review",
            normalized_verdict,
            "independent" if independent else "self_review",
        ],
        summary=(
            f"Auto Research review {hypothesis}: {normalized_verdict}; "
            f"independent={str(independent).lower()}."
        ),
        artifact_refs=refs,
        details={
            "hypothesis_id": hypothesis,
            "decision_ref": decision["decision_ref"],
            "verdict": normalized_verdict,
            "decision_agent_id": decision_agent,
            "producer_agent_id": producer,
            "independent": independent,
            "evidence_graph_revision": graph_revision,
            "hypothesis_evidence_revision": hypothesis_revision,
        },
        recorded_at=recorded_at,
    )

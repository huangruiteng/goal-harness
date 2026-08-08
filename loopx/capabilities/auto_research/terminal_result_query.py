from __future__ import annotations

from typing import Any, Mapping, Sequence

from .evidence_packet import _compact_public_token
from .terminal_result_contract import (
    AUTO_RESEARCH_TERMINAL_RESULT_QUERY_SCHEMA_VERSION,
    _decision_view,
    _event_details,
    _peer_review_events,
    _review_view,
    _terminal_decision_events,
    hypothesis_evidence_revision,
    research_evidence_graph_revision,
)


def _review_resolution(
    *,
    reviews: Sequence[Mapping[str, Any]],
    decision_ref: str,
    hypothesis_revision: str,
    registered_agent_ids: Sequence[str],
) -> dict[str, Any]:
    matching = [
        _review_view(
            review,
            registered_agent_ids=registered_agent_ids,
        )
        for review in reviews
        if str(_event_details(review).get("decision_ref") or "") == decision_ref
        and str(
            _event_details(review).get("hypothesis_evidence_revision") or ""
        )
        == hypothesis_revision
    ]
    independent = [item for item in matching if item["independent"]]
    verdicts = {item["verdict"] for item in independent}
    if len(verdicts) > 1:
        return {
            "state": "conflict",
            "independent": True,
            "verdict": None,
            "reviews": matching,
        }
    if independent:
        return {
            "state": "independent_reviewed",
            "independent": True,
            "verdict": independent[-1]["verdict"],
            "reviews": matching,
        }
    if matching:
        return {
            "state": "self_review_only",
            "independent": False,
            "verdict": matching[-1]["verdict"],
            "reviews": matching,
        }
    return {
        "state": "unreviewed",
        "independent": False,
        "verdict": None,
        "reviews": [],
    }


def _result_record(
    *,
    evidence_graph: Mapping[str, Any],
    node: Mapping[str, Any],
    graph_revision: str,
    decisions: Sequence[Mapping[str, Any]],
    reviews: Sequence[Mapping[str, Any]],
    registered_agent_ids: Sequence[str],
) -> dict[str, Any]:
    hypothesis_id = str(node.get("hypothesis_id") or "")
    hypothesis_revision = hypothesis_evidence_revision(
        evidence_graph,
        hypothesis_id,
    )
    history = [
        _decision_view(event)
        for event in decisions
        if str(_event_details(event).get("hypothesis_id") or "") == hypothesis_id
    ]
    current = [
        item
        for item in history
        if item["hypothesis_evidence_revision"] == hypothesis_revision
    ]
    current_signatures = {
        (
            item["decision_ref"],
            item["outcome"],
            item["reason"],
            item["decided_by"],
        )
        for item in current
    }
    conflict = len(current_signatures) > 1
    decision = current[-1] if len(current_signatures) == 1 else None
    stale = bool(history) and not decision and not conflict
    prior_assertion = any(
        item["outcome"] == "promoted"
        or (
            item["outcome"] == "retired"
            and item["reason"] == "contradicted"
        )
        for item in history
        if item["hypothesis_evidence_revision"] != hypothesis_revision
    )
    review = (
        _review_resolution(
            reviews=reviews,
            decision_ref=decision["decision_ref"],
            hypothesis_revision=hypothesis_revision,
            registered_agent_ids=registered_agent_ids,
        )
        if decision
        else {
            "state": "not_applicable",
            "independent": False,
            "verdict": None,
            "reviews": [],
        }
    )
    finding_status = None
    if conflict or stale:
        finding_status = "tentative"
    elif not decision and str(node.get("status") or "") == "supported":
        finding_status = "tentative"
    elif decision and decision["outcome"] == "promoted":
        finding_status = (
            "confirmed"
            if review["state"] == "independent_reviewed"
            and review["verdict"] == "approve"
            else "tentative"
        )
    elif (
        decision
        and decision["outcome"] == "retired"
        and decision["reason"] == "contradicted"
    ):
        finding_status = (
            "refuted"
            if review["state"] == "independent_reviewed"
            and review["verdict"] == "approve"
            else "tentative"
        )
    elif decision and decision["outcome"] == "retired" and prior_assertion:
        finding_status = "tentative"
    return {
        "hypothesis_id": hypothesis_id,
        "parent_hypothesis_id": str(node.get("parent_hypothesis_id") or ""),
        "todo_id": str(node.get("todo_id") or ""),
        "producer_agent_id": str(node.get("claimed_by") or ""),
        "mechanism_family": str(node.get("mechanism_family") or ""),
        "hypothesis": str(node.get("hypothesis") or hypothesis_id),
        "research_status": str(node.get("status") or ""),
        "evidence_graph_revision": graph_revision,
        "hypothesis_evidence_revision": hypothesis_revision,
        "decision_state": (
            "conflict"
            if conflict
            else "current"
            if decision
            else "stale"
            if stale
            else "pending"
        ),
        "terminal_decision": decision,
        "peer_review": review,
        "finding_status": finding_status,
        "decision_history": history,
    }


def build_terminal_result_query(
    *,
    evidence_graph: Mapping[str, Any],
    rollout_events: Sequence[Mapping[str, Any]],
    registered_agent_ids: Sequence[str],
    hypothesis_id: str | None = None,
    include_history: bool = False,
) -> dict[str, Any]:
    graph_revision = research_evidence_graph_revision(evidence_graph)
    decisions = _terminal_decision_events(rollout_events)
    reviews = _peer_review_events(rollout_events)
    requested = (
        _compact_public_token(hypothesis_id, field="hypothesis_id")
        if hypothesis_id
        else None
    )
    records = [
        _result_record(
            evidence_graph=evidence_graph,
            node=node,
            graph_revision=graph_revision,
            decisions=decisions,
            reviews=reviews,
            registered_agent_ids=registered_agent_ids,
        )
        for node in evidence_graph.get("nodes") or []
        if isinstance(node, Mapping)
        and (requested is None or str(node.get("hypothesis_id") or "") == requested)
    ]
    if requested and not records:
        raise ValueError(f"unknown hypothesis_id: {requested}")
    if not include_history:
        records = [
            {
                key: value
                for key, value in record.items()
                if key != "decision_history"
            }
            for record in records
        ]
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_TERMINAL_RESULT_QUERY_SCHEMA_VERSION,
        "goal_id": str(evidence_graph.get("goal_id") or ""),
        "evidence_graph_revision": graph_revision,
        "hypothesis_id": requested,
        "include_history": include_history,
        "result_count": len(records),
        "results": records,
        "boundary": {
            "raw_logs_recorded": False,
            "private_artifacts_recorded": False,
            "absolute_paths_recorded": False,
        },
    }

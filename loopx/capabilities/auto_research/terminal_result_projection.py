from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from ..explore.result_log import (
    build_explore_edge_event,
    build_explore_finding_event,
    build_explore_node_event,
)


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def explore_result_ids(hypothesis_id: str) -> tuple[str, str]:
    suffix = hashlib.sha256(hypothesis_id.encode("utf-8")).hexdigest()[:16]
    return f"research_{suffix}", f"finding_{suffix}"


def _projection_timestamp(record: Mapping[str, Any]) -> str:
    decision = record.get("terminal_decision")
    review = record.get("peer_review")
    review_rows = review.get("reviews") if isinstance(review, Mapping) else []
    if isinstance(review_rows, list) and review_rows:
        return str(review_rows[-1].get("recorded_at") or _now_iso())
    if isinstance(decision, Mapping):
        return str(decision.get("recorded_at") or _now_iso())
    history = record.get("decision_history")
    if isinstance(history, list) and history:
        return str(history[-1].get("recorded_at") or _now_iso())
    return "1970-01-01T00:00:00Z"


def build_terminal_result_explore_events(
    *,
    query: Mapping[str, Any],
) -> list[dict[str, Any]]:
    goal_id = str(query.get("goal_id") or "")
    node_ids = {
        str(record.get("hypothesis_id") or ""): explore_result_ids(
            str(record.get("hypothesis_id") or "")
        )[0]
        for record in query.get("results") or []
        if isinstance(record, Mapping)
        and (
            record.get("finding_status")
            or record.get("decision_state") != "pending"
        )
    }
    events: list[dict[str, Any]] = []
    for raw_record in query.get("results") or []:
        if not isinstance(raw_record, Mapping):
            continue
        record = dict(raw_record)
        if (
            record["decision_state"] == "pending"
            and not record.get("finding_status")
        ):
            continue
        hypothesis_id = str(record["hypothesis_id"])
        node_id, finding_id = explore_result_ids(hypothesis_id)
        decision = record.get("terminal_decision")
        review = record.get("peer_review")
        timestamp = _projection_timestamp(record)
        if record["decision_state"] == "conflict":
            node_status = "blocked"
            blocked_reason = "Conflicting terminal decisions exist for the current evidence revision."
        elif record["decision_state"] == "stale":
            node_status = "exploring"
            blocked_reason = None
        elif isinstance(decision, Mapping) and decision.get("outcome") == "promoted":
            node_status = "resolved"
            blocked_reason = None
        elif record["decision_state"] == "pending":
            node_status = "exploring"
            blocked_reason = None
        else:
            node_status = "dead_end"
            blocked_reason = None
        evidence_refs = []
        if isinstance(decision, Mapping):
            evidence_refs.extend(decision.get("evidence_refs") or [])
        if isinstance(review, Mapping):
            for row in review.get("reviews") or []:
                if isinstance(row, Mapping):
                    evidence_refs.extend(row.get("evidence_refs") or [])
        events.append(
            build_explore_node_event(
                goal_id=goal_id,
                node_id=node_id,
                node_kind="hypothesis",
                title=str(record.get("hypothesis") or hypothesis_id),
                status=node_status,
                summary=(
                    f"Auto Research hypothesis {hypothesis_id}; "
                    f"decision_state={record['decision_state']}; "
                    f"review_state={review.get('state') if isinstance(review, Mapping) else 'not_applicable'}."
                ),
                blocked_reason=blocked_reason,
                parent_id=node_ids.get(str(record.get("parent_hypothesis_id") or "")),
                agent_id=str(record.get("producer_agent_id") or ""),
                evidence_refs=sorted(set(evidence_refs)),
                tags=[
                    "auto_research",
                    str(record.get("mechanism_family") or "research"),
                    record["decision_state"],
                ],
                recorded_at=timestamp,
            )
        )
        parent = str(record.get("parent_hypothesis_id") or "")
        if parent and parent in node_ids:
            events.append(
                build_explore_edge_event(
                    goal_id=goal_id,
                    from_node=node_ids[parent],
                    to_node=node_id,
                    edge_type="leads_to",
                    summary="A later Auto Research hypothesis extends the earlier research path.",
                    recorded_at=timestamp,
                )
            )
        finding_status = record.get("finding_status")
        if not finding_status:
            continue
        outcome = (
            str(decision.get("outcome") or "")
            if isinstance(decision, Mapping)
            else "stale"
        )
        reason = (
            str(decision.get("reason") or "")
            if isinstance(decision, Mapping)
            else "evidence_revision_changed"
        )
        events.append(
            build_explore_finding_event(
                goal_id=goal_id,
                finding_id=finding_id,
                node_id=node_id,
                title=str(record.get("hypothesis") or hypothesis_id),
                status=str(finding_status),
                summary=(
                    f"Terminal outcome={outcome}; reason={reason}; "
                    f"review_state={review.get('state') if isinstance(review, Mapping) else 'not_applicable'}; "
                    f"review_verdict={review.get('verdict') if isinstance(review, Mapping) else None}."
                ),
                agent_id=str(
                    decision.get("decided_by")
                    if isinstance(decision, Mapping)
                    else record.get("producer_agent_id")
                ),
                evidence_refs=sorted(set(evidence_refs)),
                tags=[
                    "auto_research",
                    hypothesis_id,
                    outcome,
                    str(finding_status),
                ],
                recorded_at=timestamp,
            )
        )
    return events

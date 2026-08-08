from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .research_state import build_research_evidence_graph_from_rollout_events
from .terminal_result_contract import (
    AUTO_RESEARCH_PEER_REVIEW_SCHEMA_VERSION,
    AUTO_RESEARCH_TERMINAL_DECISION_SCHEMA_VERSION,
    _decision_view,
    _event_decision_ref,
    _review_view,
    build_peer_review_event,
    build_terminal_decision_event,
)
from .terminal_result_projection import (
    build_terminal_result_explore_events,
    explore_result_ids,
)
from .terminal_result_query import build_terminal_result_query
from ..explore.result_log import (
    append_explore_result_events,
    build_explore_result_projection,
    explore_result_log_path,
    load_explore_result_events_strict,
)
from ...agent_registry import (
    registered_agent_ids_from_registry,
    require_registered_agent_id,
)
from ...history import load_registry
from ...paths import resolve_runtime_root
from ...rollout_event_log import (
    append_rollout_event,
    load_rollout_events,
    rollout_event_log_path,
)


AUTO_RESEARCH_TERMINAL_RESULT_PROJECTION_SCHEMA_VERSION = (
    "auto_research_terminal_result_projection_v0"
)


def _append_validation_event_once(
    *,
    log_path: Path,
    event: Mapping[str, Any],
    rollout_events: Sequence[Mapping[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    decision_ref = _event_decision_ref(event)
    matching = [
        dict(existing)
        for existing in rollout_events
        if _event_decision_ref(existing) == decision_ref
    ]
    if len(matching) > 1:
        raise ValueError(f"duplicate validation decision ref: {decision_ref}")
    if matching:
        existing = matching[0]
        comparable_existing = _validation_event_semantics(existing)
        comparable_new = _validation_event_semantics(event)
        if comparable_existing != comparable_new:
            raise ValueError(f"conflicting validation decision ref: {decision_ref}")
        return {"appended": False, "reused": True, "event": existing}
    if not dry_run:
        append_rollout_event(log_path, event)
    return {
        "appended": not dry_run,
        "reused": False,
        "event": dict(event),
    }


def _validation_event_semantics(event: Mapping[str, Any]) -> dict[str, Any]:
    comparable = {
        key: value
        for key, value in event.items()
        if key not in {"event_id", "recorded_at"}
    }
    details = comparable.get("details")
    if isinstance(details, Mapping):
        comparable["details"] = {
            key: value
            for key, value in details.items()
            if key != "evidence_graph_revision"
        }
    return comparable


def _load_runtime_state(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_arg)
    rollout_path = rollout_event_log_path(runtime_root, goal_id)
    rollout_events = load_rollout_events(rollout_path)
    evidence_graph = build_research_evidence_graph_from_rollout_events(
        goal_id=goal_id,
        rollout_events=rollout_events,
    )
    return runtime_root, rollout_events, evidence_graph


def decide_terminal_result(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    hypothesis_id: str,
    outcome: str,
    reason: str,
    decided_by: str,
    evidence_refs: Sequence[str] | None,
    dry_run: bool,
) -> dict[str, Any]:
    runtime_root, rollout_events, evidence_graph = _load_runtime_state(
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        goal_id=goal_id,
    )
    decider = require_registered_agent_id(
        registry_path=registry_path,
        goal_id=goal_id,
        agent_id=decided_by,
        field="decided_by",
    )
    event = build_terminal_decision_event(
        evidence_graph=evidence_graph,
        hypothesis_id=hypothesis_id,
        outcome=outcome,
        reason=reason,
        decided_by=decider,
        evidence_refs=evidence_refs,
    )
    write = _append_validation_event_once(
        log_path=rollout_event_log_path(runtime_root, goal_id),
        event=event,
        rollout_events=rollout_events,
        dry_run=dry_run,
    )
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_TERMINAL_DECISION_SCHEMA_VERSION,
        "goal_id": goal_id,
        "dry_run": dry_run,
        "decision": _decision_view(write["event"]),
        "appended": write["appended"],
        "reused": write["reused"],
    }


def review_terminal_result(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    hypothesis_id: str,
    reviewer_agent_id: str,
    verdict: str,
    evidence_refs: Sequence[str] | None,
    require_independent: bool,
    dry_run: bool,
) -> dict[str, Any]:
    runtime_root, rollout_events, evidence_graph = _load_runtime_state(
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        goal_id=goal_id,
    )
    reviewer = require_registered_agent_id(
        registry_path=registry_path,
        goal_id=goal_id,
        agent_id=reviewer_agent_id,
        field="reviewer_agent_id",
    )
    event = build_peer_review_event(
        evidence_graph=evidence_graph,
        rollout_events=rollout_events,
        hypothesis_id=hypothesis_id,
        reviewer_agent_id=reviewer,
        verdict=verdict,
        evidence_refs=evidence_refs,
        require_independent=require_independent,
        registered_agent_ids=registered_agent_ids_from_registry(
            registry_path,
            goal_id,
        ),
    )
    write = _append_validation_event_once(
        log_path=rollout_event_log_path(runtime_root, goal_id),
        event=event,
        rollout_events=rollout_events,
        dry_run=dry_run,
    )
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_PEER_REVIEW_SCHEMA_VERSION,
        "goal_id": goal_id,
        "dry_run": dry_run,
        "review": _review_view(
            write["event"],
            registered_agent_ids=registered_agent_ids_from_registry(
                registry_path,
                goal_id,
            ),
        ),
        "appended": write["appended"],
        "reused": write["reused"],
    }


def query_terminal_results(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    hypothesis_id: str | None,
    include_history: bool,
) -> dict[str, Any]:
    runtime_root, rollout_events, evidence_graph = _load_runtime_state(
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        goal_id=goal_id,
    )
    query = build_terminal_result_query(
        evidence_graph=evidence_graph,
        rollout_events=rollout_events,
        registered_agent_ids=registered_agent_ids_from_registry(
            registry_path,
            goal_id,
        ),
        hypothesis_id=hypothesis_id,
        include_history=include_history,
    )
    explore_events = load_explore_result_events_strict(
        explore_result_log_path(runtime_root, goal_id),
        goal_id=goal_id,
    )
    projection = build_explore_result_projection(
        explore_events,
        goal_id=goal_id,
        finding_limit=max(1, len(explore_events)),
    )
    expected_nodes = {
        explore_result_ids(str(record.get("hypothesis_id") or ""))[0]
        for record in query["results"]
        if record.get("finding_status")
        or record.get("decision_state") != "pending"
    }
    projected_nodes = {
        str(node.get("node_id") or "")
        for node in projection.get("nodes") or []
    }
    expected_findings = {
        explore_result_ids(str(record.get("hypothesis_id") or ""))[1]: str(
            record.get("finding_status") or ""
        )
        for record in query["results"]
        if record.get("finding_status")
    }
    projected_findings = {
        str(finding.get("finding_id") or ""): str(finding.get("status") or "")
        for finding in projection.get("findings") or []
    }
    node_current = expected_nodes.issubset(projected_nodes)
    finding_current = all(
        projected_findings.get(finding_id) == status
        for finding_id, status in expected_findings.items()
    )
    query["explore_projection"] = {
        "state": (
            "current"
            if (expected_nodes or expected_findings) and node_current and finding_current
            else "not_required"
            if not expected_nodes and not expected_findings
            else "missing_or_stale"
        ),
        "expected_node_ids": sorted(expected_nodes),
        "projected_node_ids": sorted(expected_nodes & projected_nodes),
        "expected_findings": expected_findings,
        "projected_findings": {
            finding_id: projected_findings.get(finding_id)
            for finding_id in sorted(expected_findings)
            if finding_id in projected_findings
        },
        "counts": projection.get("counts"),
    }
    return query


def project_terminal_results(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    dry_run: bool,
) -> dict[str, Any]:
    runtime_root, rollout_events, evidence_graph = _load_runtime_state(
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        goal_id=goal_id,
    )
    query = build_terminal_result_query(
        evidence_graph=evidence_graph,
        rollout_events=rollout_events,
        registered_agent_ids=registered_agent_ids_from_registry(
            registry_path,
            goal_id,
        ),
        include_history=True,
    )
    events = build_terminal_result_explore_events(query=query)
    write = (
        {
            "requested_event_count": len(events),
            "appended_event_count": 0,
            "reused_event_count": 0,
        }
        if dry_run
        else append_explore_result_events(
            explore_result_log_path(runtime_root, goal_id),
            events,
            expected_goal_id=goal_id,
        )
    )
    projection = build_explore_result_projection(
        events,
        goal_id=goal_id,
        finding_limit=max(1, len(events)),
    )
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_TERMINAL_RESULT_PROJECTION_SCHEMA_VERSION,
        "goal_id": goal_id,
        "dry_run": dry_run,
        "evidence_graph_revision": query["evidence_graph_revision"],
        "result_count": query["result_count"],
        "event_count": len(events),
        "would_append_count": len(events),
        "appended_count": write["appended_event_count"],
        "reused_count": write["reused_event_count"],
        "results": query["results"],
        "explore_projection": projection,
        "boundary": query["boundary"],
    }

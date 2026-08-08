"""Small read-model helpers for auto-research worker state.

This module turns LoopX quota/todo state and rollout evidence events into the
minimal frontier, evidence graph, and decision-candidate shapes that worker
turns need. It intentionally avoids demo boards, starter packs, and other
legacy presentation code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .evidence_packet import (
    METRIC_DIRECTIONS,
    RESEARCH_FAILURE_KINDS,
    RESEARCH_EVIDENCE_EVENT_SCHEMA_VERSION,
    RESEARCH_HYPOTHESIS_SCHEMA_VERSION,
    _compact_public_text,
    _compact_public_text_list,
    _compact_public_token,
    _derive_hypothesis_status,
    _finite_float,
    _is_negative_evidence_event,
    _is_retry_evidence_event,
    _json_list,
    _json_obj,
    _metric_improved,
    _metric_rank_key,
    validate_research_contract,
    validate_research_evidence_event,
    validate_research_hypothesis,
)
from .preset import AUTO_RESEARCH_REQUIRED_HOLDOUT_IMPROVEMENTS


AUTO_RESEARCH_FIXTURE_SCHEMA_VERSION = "decentralized_auto_research_fixture_v0"
AUTO_RESEARCH_PROJECTION_SCHEMA_VERSION = "decentralized_auto_research_projection_v0"
RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION = "research_evidence_graph_v0"
RESEARCH_FRONTIER_SCHEMA_VERSION = "decentralized_research_frontier_v0"
AUTO_RESEARCH_COMPLETION_STATUS_SCHEMA_VERSION = "auto_research_completion_status_v0"
ROLLOUT_EVIDENCE_GRAPH_SOURCE_KIND = "loopx_rollout_event_log"
AUTO_RESEARCH_ACTION_ALIASES = {
    "run_read_only_adapter_tick": "run_dev_eval",
}


def load_auto_research_fixture(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return validate_auto_research_fixture(payload)


def validate_auto_research_fixture(payload: dict[str, Any]) -> dict[str, Any]:
    payload = _json_obj(payload, field="fixture")
    schema = _compact_public_token(payload.get("schema_version"), field="schema_version")
    if schema != AUTO_RESEARCH_FIXTURE_SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {AUTO_RESEARCH_FIXTURE_SCHEMA_VERSION}")

    contract = validate_research_contract(_json_obj(payload.get("research_contract"), field="research_contract"))
    hypotheses = [
        validate_research_hypothesis(_json_obj(item, field="hypotheses[]"))
        for item in _json_list(payload.get("hypotheses"), field="hypotheses")
    ]
    evidence_events = [
        validate_research_evidence_event(_json_obj(item, field="evidence_events[]"))
        for item in _json_list(payload.get("evidence_events"), field="evidence_events")
    ]

    hypothesis_ids = {item["hypothesis_id"] for item in hypotheses}
    todo_ids = {item["todo_id"] for item in hypotheses if item.get("todo_id")}
    for item in evidence_events:
        if item["hypothesis_id"] not in hypothesis_ids:
            raise ValueError(f"evidence references unknown hypothesis_id {item['hypothesis_id']}")
        if item.get("todo_id") and item["todo_id"] not in todo_ids:
            raise ValueError(f"evidence references unknown todo_id {item['todo_id']}")

    agents = [
        _compact_public_token(value, field="agents[]")
        for value in _json_list(payload.get("agents"), field="agents")
    ]

    return {
        "schema_version": schema,
        "generated_at": _compact_public_text(payload.get("generated_at"), field="generated_at"),
        "research_contract": contract,
        "agents": agents,
        "hypotheses": hypotheses,
        "evidence_events": evidence_events,
        "raw_logs_recorded": False,
        "private_artifacts_recorded": False,
    }


def _compact_optional_token(value: Any, *, field: str, default: str) -> str:
    if value is None or str(value).strip() == "":
        return default
    return _compact_public_token(value, field=field)


def _compact_optional_text(value: Any, *, field: str, default: str, max_len: int = 240) -> str:
    if value is None or str(value).strip() == "":
        return default
    text = " ".join(str(value).strip().split())
    if len(text) > max_len:
        prefix = text[: max_len - 1].rstrip()
        if prefix.endswith(".") and not prefix.endswith(".."):
            text = prefix
        else:
            text = prefix.rstrip(".") + "."
    # Strip trailing dot-runs so public text validation does not flag them
    # as parent-directory markers (text may arrive with "..." from upstream).
    while text.endswith(".."):
        text = text[:-1]
    return _compact_public_text(text, field=field, max_len=max_len)


def _live_hypothesis_id(todo_id: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9_:-]+", "_", todo_id.replace("todo_", "", 1))
    return _compact_public_token(f"hyp_{suffix}", field="live.hypothesis_id")


def _claimed_by_current_or_unclaimed(item: dict[str, Any], *, agent_id: str) -> bool:
    claimed_by = str(item.get("claimed_by") or "").strip()
    return not claimed_by or claimed_by == agent_id


def _public_todo_items(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict) and item.get("todo_id")]


def _is_runnable_advancement_todo(item: dict[str, Any]) -> bool:
    task_class = str(item.get("task_class") or "advancement_task").strip()
    if task_class and task_class != "advancement_task":
        return False
    status = str(item.get("status") or "open").strip()
    if status and status not in {"active", "open", "needs_retry"}:
        return False
    resume_when = str(item.get("resume_when") or "").strip()
    if resume_when and item.get("resume_ready") is False:
        return False
    return True


def _unique_todo_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        todo_id = str(item.get("todo_id") or "").strip()
        if not todo_id or todo_id in seen:
            continue
        seen.add(todo_id)
        selected.append(item)
    return selected


def _quota_payload_todo_candidates(
    quota_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gate = quota_payload.get("capability_gate")
    if not isinstance(gate, dict):
        gate = {}
    runnable = _public_todo_items(gate.get("runnable_candidates"))
    blocked = _public_todo_items(gate.get("blocked_candidates"))

    agent_summary = quota_payload.get("agent_todo_summary")
    if not isinstance(agent_summary, dict):
        return _unique_todo_candidates(runnable), _unique_todo_candidates(blocked)

    for key in (
        "active_next_action_executable_items",
        "first_executable_items",
        "claimed_advancement_open_items",
        "unclaimed_advancement_open_items",
    ):
        runnable.extend(
            item
            for item in _public_todo_items(agent_summary.get(key))
            if _is_runnable_advancement_todo(item)
        )

    claim_scope = agent_summary.get("claim_scope")
    if not isinstance(claim_scope, dict):
        claim_scope = {}
    for key in ("claimed_by_others_items", "blocked_claimed_items", "blocked_items"):
        blocked.extend(_public_todo_items(agent_summary.get(key)))
        blocked.extend(_public_todo_items(claim_scope.get(key)))

    return _unique_todo_candidates(runnable), _unique_todo_candidates(blocked)


def normalize_auto_research_action(action: object) -> str:
    raw = str(action or "").strip()
    return AUTO_RESEARCH_ACTION_ALIASES.get(raw, raw)


def _todo_frontier_item(
    item: dict[str, Any],
    *,
    default_agent_id: str,
    blocked_by: str | None = None,
) -> dict[str, Any]:
    todo_id = _compact_public_token(item.get("todo_id"), field="live.todo_id")
    claimed_by = _compact_optional_token(
        item.get("claimed_by"),
        field="live.claimed_by",
        default=default_agent_id,
    )
    status = _compact_optional_token(item.get("status"), field="live.status", default="open")
    summary = {
        "hypothesis_id": _live_hypothesis_id(todo_id),
        "todo_id": todo_id,
        "claimed_by": claimed_by,
        "status": "active" if status == "open" else status,
        "mechanism_family": _compact_optional_text(
            item.get("action_kind") or item.get("task_class") or "advancement_task",
            field="live.mechanism_family",
            default="advancement_task",
            max_len=96,
        ),
        "source_kind": "todo_item_v0",
        "title": _compact_optional_text(
            item.get("title") or item.get("text"),
            field="live.title",
            default=todo_id,
            max_len=220,
        ),
    }
    unblocks_todo_id = _compact_optional_token(
        item.get("unblocks_todo_id"),
        field="live.unblocks_todo_id",
        default="",
    )
    if unblocks_todo_id:
        summary["unblocks_todo_id"] = unblocks_todo_id
    resume_when = _compact_optional_text(
        item.get("resume_when"),
        field="live.resume_when",
        default="",
        max_len=160,
    )
    if resume_when:
        summary["resume_when"] = resume_when
    if blocked_by:
        summary["blocked_by"] = _compact_public_text(blocked_by, field="live.blocked_by", max_len=160)
    else:
        summary["allowed_action"] = _compact_optional_text(
            normalize_auto_research_action(item.get("action_kind") or "advance_todo"),
            field="live.allowed_action",
            default="advance_todo",
            max_len=96,
        )
    return summary


def _rollout_source_refs(event: dict[str, Any]) -> tuple[list[str], str | None]:
    grounding_refs: list[str] = []
    novelty_audit_ref: str | None = None
    for index, ref in enumerate(event.get("source_refs") or []):
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or "").strip()
        ref_id = ref.get("id")
        if not ref_id:
            continue
        if kind == "grounding":
            grounding_refs.append(
                _compact_public_text(ref_id, field=f"rollout.source_refs[{index}].id")
            )
        elif kind == "novelty_audit" and novelty_audit_ref is None:
            novelty_audit_ref = _compact_public_text(
                ref_id,
                field=f"rollout.source_refs[{index}].id",
            )
    return grounding_refs, novelty_audit_ref


def _rollout_hypothesis_text(event: dict[str, Any], details: dict[str, Any]) -> str:
    if details.get("hypothesis"):
        return _compact_public_text(details["hypothesis"], field="rollout.details.hypothesis")
    summary = str(event.get("summary") or "")
    prefix = "auto-research hypothesis "
    if summary.startswith(prefix) and ": " in summary:
        return _compact_public_text(
            summary.split(": ", 1)[1],
            field="rollout.summary.hypothesis",
        )
    fallback = f"Evidence-backed hypothesis {details.get('hypothesis_id') or event.get('todo_id')}"
    return _compact_public_text(fallback, field="rollout.summary.hypothesis")


def _research_hypothesis_from_rollout_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if str(event.get("event_kind") or "") != "research_hypothesis":
        return None
    if str(event.get("classification") or "") != RESEARCH_HYPOTHESIS_SCHEMA_VERSION:
        return None
    details = _json_obj(event.get("details") or {}, field="rollout.hypothesis.details")
    grounding_refs, novelty_audit_ref = _rollout_source_refs(event)
    negative_count = int(details.get("negative_evidence_count") or 0)
    retry_count = int(details.get("needs_retry_count") or 0)
    status = details.get("status") or event.get("status") or "active"
    blocked_by: list[str] = []
    if str(status) == "contradicted" or negative_count:
        blocked_by.append("evidence_or_boundary_guardrail_failed")
    elif str(status) == "needs_retry" or retry_count:
        blocked_by.append("needs_retry_evidence")
    return validate_research_hypothesis(
        {
            "schema_version": RESEARCH_HYPOTHESIS_SCHEMA_VERSION,
            "hypothesis_id": details.get("hypothesis_id"),
            "parent_hypothesis_id": details.get("parent_hypothesis_id") or None,
            "todo_id": event.get("todo_id"),
            "claimed_by": event.get("agent_id") or "unknown_agent",
            "mechanism_family": details.get("mechanism_family") or "rollout_imported",
            "hypothesis": _rollout_hypothesis_text(event, details),
            "status": status,
            "grounding_refs": grounding_refs,
            "novelty_audit_ref": novelty_audit_ref,
            "blocked_by": blocked_by,
        }
    )


def _research_evidence_from_rollout_event(event: dict[str, Any]) -> dict[str, Any] | None:
    if str(event.get("event_kind") or "") != "research_evidence":
        return None
    if str(event.get("classification") or "") != RESEARCH_EVIDENCE_EVENT_SCHEMA_VERSION:
        return None
    details = _json_obj(event.get("details") or {}, field="rollout.evidence.details")
    return validate_research_evidence_event(
        {
            "schema_version": RESEARCH_EVIDENCE_EVENT_SCHEMA_VERSION,
            "hypothesis_id": details.get("hypothesis_id"),
            "todo_id": event.get("todo_id"),
            "agent_id": event.get("agent_id") or "unknown_agent",
            "attempt": details.get("attempt") or 1,
            "split": details.get("split"),
            "metric": {
                "name": details.get("metric_name"),
                "value": details.get("metric_value"),
                "direction": details.get("metric_direction"),
            },
            "baseline_metric": details.get("baseline_metric"),
            "eval_status": details.get("eval_status") or event.get("status"),
            "primary_metric_status": details.get("primary_metric_status") or "inconclusive",
            "failure_kind": details.get("failure_kind") or None,
            "measurement_scope": details.get("measurement_scope") or None,
            "remediation_attempt": bool(details.get("remediation_attempt")),
            "artifact_refs": event.get("artifact_refs") or [],
            "protected_scope_clean": bool(details.get("protected_scope_clean")),
        }
    )


def _synthetic_hypothesis_from_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    first = events[0]
    status = _derive_hypothesis_status(events)
    blocked_by = []
    if status == "contradicted":
        blocked_by.append("evidence_or_boundary_guardrail_failed")
    elif status == "needs_retry":
        blocked_by.append("needs_retry_evidence")
    return validate_research_hypothesis(
        {
            "schema_version": RESEARCH_HYPOTHESIS_SCHEMA_VERSION,
            "hypothesis_id": first["hypothesis_id"],
            "parent_hypothesis_id": None,
            "todo_id": first["todo_id"],
            "claimed_by": first["agent_id"],
            "mechanism_family": "rollout_evidence_only",
            "hypothesis": f"Evidence-backed hypothesis {first['hypothesis_id']}",
            "status": status,
            "grounding_refs": [],
            "novelty_audit_ref": None,
            "blocked_by": blocked_by,
        }
    )


def _best_metric(events: list[dict[str, Any]], *, split: str, direction: str) -> float | None:
    values = [
        event["metric"]["value"]
        for event in events
        if event["split"] == split and event["eval_status"] == "scored"
    ]
    if not values:
        return None
    return max(values, key=lambda value: _metric_rank_key(value, direction=direction))


def _default_failure_kind(
    *,
    status: str,
    events: list[dict[str, Any]],
) -> str | None:
    explicit = [event for event in events if event.get("failure_kind")]
    if explicit:
        return str(explicit[-1]["failure_kind"])
    if any(not event["protected_scope_clean"] for event in events):
        return "guardrail_or_protected_boundary"
    if status == "needs_retry":
        return None
    return "mechanism_contradicted"


def _failure_measurement_scope(events: list[dict[str, Any]]) -> str | None:
    values = [
        str(event.get("measurement_scope") or "").strip()
        for event in events
        if event.get("measurement_scope")
    ]
    return values[-1] if values else None


def _ancestor_hypothesis_ids(
    hypothesis_id: str,
    *,
    hypotheses: dict[str, dict[str, Any]],
) -> set[str]:
    ancestor_ids: set[str] = set()
    current_id = hypothesis_id
    while current_id and current_id not in ancestor_ids:
        ancestor_ids.add(current_id)
        current = hypotheses.get(current_id) or {}
        current_id = str(current.get("parent_hypothesis_id") or "").strip()
    return ancestor_ids


def build_research_evidence_graph_from_records(
    *,
    goal_id: str,
    hypotheses: list[dict[str, Any]],
    evidence_events: list[dict[str, Any]],
    metric_name: str,
    metric_direction: str,
    baseline_metric: float | None,
    source_kind: str = "public_records",
) -> dict[str, Any]:
    goal = _compact_public_token(goal_id, field="goal_id")
    direction = _compact_public_token(metric_direction, field="metric.direction")
    if direction not in METRIC_DIRECTIONS:
        raise ValueError("metric.direction must be maximize or minimize")
    name = _compact_public_token(metric_name, field="metric.name")
    source = _compact_public_token(source_kind, field="source_kind")
    hypotheses = [validate_research_hypothesis(dict(item)) for item in hypotheses]
    events = [validate_research_evidence_event(dict(event)) for event in evidence_events]
    baseline = _finite_float(baseline_metric, field="baseline_metric")
    scored_events = [event for event in events if event["eval_status"] == "scored"]
    best_dev = _best_metric(scored_events, split="dev", direction=direction)
    best_holdout = _best_metric(scored_events, split="holdout", direction=direction)
    hypotheses_by_id = {item["hypothesis_id"]: item for item in hypotheses}
    events_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        events_by_hypothesis.setdefault(event["hypothesis_id"], []).append(event)
    nodes = []
    for item in hypotheses:
        item_events = events_by_hypothesis.get(item["hypothesis_id"], [])
        item_scored_events = [event for event in item_events if event["eval_status"] == "scored"]
        item_best_dev = _best_metric(item_scored_events, split="dev", direction=direction)
        item_best_holdout = _best_metric(item_scored_events, split="holdout", direction=direction)
        item_artifact_refs = sorted(
            {
                ref
                for event in item_events
                for ref in event.get("artifact_refs", [])
                if ref
            }
        )
        item_splits = sorted({event["split"] for event in item_events if event.get("split")})
        item_negative_count = len([event for event in item_events if _is_negative_evidence_event(event)])
        item_retry_count = len([event for event in item_events if _is_retry_evidence_event(event)])
        item_failure_kind = (
            _default_failure_kind(status=item["status"], events=item_events)
            if item["status"] in {"contradicted", "retired", "needs_retry"}
            or item_negative_count
            else None
        )
        lineage_ids = _ancestor_hypothesis_ids(
            item["hypothesis_id"],
            hypotheses=hypotheses_by_id,
        )
        remediation_attempt_count = len(
            [
                event
                for event in events
                if event["hypothesis_id"] in lineage_ids
                and event.get("remediation_attempt")
            ]
        )
        nodes.append(
            {
                "hypothesis_id": item["hypothesis_id"],
                "parent_hypothesis_id": item["parent_hypothesis_id"],
                "todo_id": item["todo_id"],
                "claimed_by": item["claimed_by"],
                "mechanism_family": item["mechanism_family"],
                "hypothesis": item["hypothesis"],
                "status": item["status"],
                "grounding_refs": item["grounding_refs"],
                "novelty_audit_ref": item["novelty_audit_ref"],
                "artifact_refs": item_artifact_refs,
                "splits": item_splits,
                "evidence_event_count": len(item_events),
                "best_dev_metric": item_best_dev,
                "best_holdout_metric": item_best_holdout,
                "dev_improved": _metric_improved(
                    value=item_best_dev,
                    baseline=baseline,
                    direction=direction,
                ),
                "holdout_improved": _metric_improved(
                    value=item_best_holdout,
                    baseline=baseline,
                    direction=direction,
                ),
                "negative_evidence_count": item_negative_count,
                "needs_retry_count": item_retry_count,
                "failure_kind": item_failure_kind,
                "measurement_scope": _failure_measurement_scope(item_events),
                "remediation_attempt_count": remediation_attempt_count,
                "source_kind": source,
            }
        )
    return {
        "schema_version": RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "goal_id": goal,
        "hypothesis_count": len(hypotheses),
        "evidence_event_count": len(events),
        "todo_ids": sorted({item["todo_id"] for item in hypotheses}),
        "agent_ids": sorted({item["claimed_by"] for item in hypotheses}),
        "metric": {
            "name": name,
            "direction": direction,
            "baseline": baseline,
        },
        "baseline_metric": baseline,
        "best_dev_metric": best_dev,
        "best_holdout_metric": best_holdout,
        "holdout_improved": _metric_improved(value=best_holdout, baseline=baseline, direction=direction),
        "negative_evidence_count": len([event for event in events if _is_negative_evidence_event(event)]),
        "needs_retry_count": len(
            [event for event in events if _is_retry_evidence_event(event)]
        ) + len([item for item in hypotheses if item["status"] == "needs_retry"]),
        "remediation_attempt_count": len(
            [event for event in events if event.get("remediation_attempt")]
        ),
        "nodes": nodes,
        "source_kind": source,
    }


def build_research_evidence_graph_from_rollout_events(
    *,
    goal_id: str,
    rollout_events: list[dict[str, Any]],
) -> dict[str, Any]:
    goal = _compact_public_token(goal_id, field="goal_id")
    hypotheses_by_id: dict[str, dict[str, Any]] = {}
    evidence_events: list[dict[str, Any]] = []
    for event in rollout_events:
        hypothesis = _research_hypothesis_from_rollout_event(event)
        if hypothesis:
            hypotheses_by_id[hypothesis["hypothesis_id"]] = hypothesis
            continue
        evidence = _research_evidence_from_rollout_event(event)
        if evidence:
            evidence_events.append(evidence)

    events_by_hypothesis: dict[str, list[dict[str, Any]]] = {}
    for evidence in evidence_events:
        events_by_hypothesis.setdefault(evidence["hypothesis_id"], []).append(evidence)
    for hypothesis_id, events in events_by_hypothesis.items():
        if hypothesis_id not in hypotheses_by_id:
            hypotheses_by_id[hypothesis_id] = _synthetic_hypothesis_from_evidence(events)

    first_metric_event = evidence_events[0] if evidence_events else None
    metric = first_metric_event["metric"] if first_metric_event else {}
    return build_research_evidence_graph_from_records(
        goal_id=goal,
        hypotheses=list(hypotheses_by_id.values()),
        evidence_events=evidence_events,
        metric_name=metric.get("name") or "research_metric",
        metric_direction=metric.get("direction") or "maximize",
        baseline_metric=first_metric_event.get("baseline_metric") if first_metric_event else None,
        source_kind=ROLLOUT_EVIDENCE_GRAPH_SOURCE_KIND,
    )


def build_research_evidence_graph(fixture: dict[str, Any]) -> dict[str, Any]:
    fixture = validate_auto_research_fixture(fixture)
    contract = fixture["research_contract"]
    return build_research_evidence_graph_from_records(
        goal_id=contract["goal_id"],
        hypotheses=fixture["hypotheses"],
        evidence_events=fixture["evidence_events"],
        metric_name=contract["metric"]["name"],
        metric_direction=contract["metric"]["direction"],
        baseline_metric=contract["metric"]["baseline"],
        source_kind="public_fixture",
    )


def build_research_decision_candidates(evidence_graph: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    graph = _json_obj(evidence_graph, field="evidence_graph")
    metric = graph.get("metric") if isinstance(graph.get("metric"), dict) else {}
    direction = str(metric.get("direction") or "maximize")
    if direction not in METRIC_DIRECTIONS:
        direction = "maximize"
    baseline = _finite_float(metric.get("baseline"), field="evidence_graph.metric.baseline")
    source_kind = _compact_optional_token(
        graph.get("source_kind"),
        field="evidence_graph.source_kind",
        default="unknown_source",
    )
    promotion_candidates: list[dict[str, Any]] = []
    dev_promotion_candidates: list[dict[str, Any]] = []
    validated_promotion_candidates: list[dict[str, Any]] = []
    retirement_candidates: list[dict[str, Any]] = []
    for raw_node in graph.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        hypothesis_id = _compact_public_token(raw_node.get("hypothesis_id"), field="node.hypothesis_id")
        todo_id = _compact_public_token(raw_node.get("todo_id"), field="node.todo_id")
        status = _compact_optional_token(raw_node.get("status"), field="node.status", default="active")
        dev_metric = _finite_float(raw_node.get("best_dev_metric"), field="node.best_dev_metric")
        holdout_metric = _finite_float(raw_node.get("best_holdout_metric"), field="node.best_holdout_metric")
        negative_count = int(raw_node.get("negative_evidence_count") or 0)
        evidence_count = int(raw_node.get("evidence_event_count") or 0)
        dev_improved = bool(raw_node.get("dev_improved")) or _metric_improved(
            value=dev_metric,
            baseline=baseline,
            direction=direction,
        )
        holdout_improved = bool(raw_node.get("holdout_improved")) or _metric_improved(
            value=holdout_metric,
            baseline=baseline,
            direction=direction,
        )
        failure_kind = str(raw_node.get("failure_kind") or "")
        retry_exhausted = status == "needs_retry" and failure_kind == "retry_exhausted"
        if status in {"contradicted", "retired"} or negative_count > 0 or retry_exhausted:
            if failure_kind not in RESEARCH_FAILURE_KINDS:
                failure_kind = (
                    "guardrail_or_protected_boundary"
                    if status == "contradicted" and negative_count
                    else "mechanism_contradicted"
                )
            remediation_attempt_count = int(
                raw_node.get("remediation_attempt_count") or 0
            )
            remediation_allowed = (
                failure_kind == "data_or_measurement_gap"
                and remediation_attempt_count < 1
            )
            retirement_candidates.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "todo_id": todo_id,
                    "status": status,
                    "negative_evidence_count": negative_count,
                    "evidence_event_count": evidence_count,
                    "reason": (
                        "retry_exhausted"
                        if retry_exhausted
                        else "negative_or_guardrail_evidence"
                        if negative_count
                        else f"status:{status}"
                    ),
                    "failure_kind": failure_kind,
                    "measurement_scope": raw_node.get("measurement_scope"),
                    "remediation_attempt_count": remediation_attempt_count,
                    "remediation_attempt_limit": 1,
                    "remediation_allowed": remediation_allowed,
                    "next_outcome": (
                        "remediate_data_measurement"
                        if remediation_allowed
                        else "propose_failure_successor"
                    ),
                    "source_kind": source_kind,
                }
            )
            continue
        if status in {"supported", "promoted"} or dev_improved:
            requires = ["boundary_scan"]
            requires.append("promotion_decision" if holdout_improved else "holdout_eval")
            candidate = {
                "hypothesis_id": hypothesis_id,
                "todo_id": todo_id,
                "status": status,
                "dev_metric": dev_metric,
                "holdout_metric": holdout_metric,
                "evidence_event_count": evidence_count,
                "requires": requires,
                "source_kind": source_kind,
            }
            promotion_candidates.append(candidate)
            if holdout_improved:
                validated_promotion_candidates.append(candidate)
            else:
                dev_promotion_candidates.append(candidate)
    return {
        "dev_promotion_candidates": dev_promotion_candidates,
        "validated_promotion_candidates": validated_promotion_candidates,
        "promotion_candidates": promotion_candidates,
        "retirement_candidates": retirement_candidates,
    }


def build_research_failure_continuation_resolution(
    decision_candidates: dict[str, list[dict[str, Any]]],
    *,
    selected_todo_id: str | None = None,
    selected_lineage_todo_id: str | None = None,
    allow_unbound_singleton: bool = False,
    require_selected_failure_match: bool = False,
) -> dict[str, Any]:
    candidates = [
        dict(candidate)
        for candidate in decision_candidates.get("retirement_candidates") or []
        if isinstance(candidate, dict)
    ]
    lineage_todo_id = str(selected_lineage_todo_id or "").strip()
    selected_id = str(selected_todo_id or "").strip()
    selection_bound = bool(lineage_todo_id) if require_selected_failure_match else bool(
        lineage_todo_id or selected_id
    )
    selected_parent_todo_id = (
        lineage_todo_id
        if require_selected_failure_match
        else lineage_todo_id or selected_id
    )
    matched = (
        [
            candidate
            for candidate in candidates
            if str(candidate.get("todo_id") or "").strip() == selected_parent_todo_id
        ]
        if selection_bound
        else []
    )
    candidate = (
        matched[0]
        if selection_bound and len(matched) == 1
        else candidates[0]
        if allow_unbound_singleton and not selection_bound and len(candidates) == 1
        else None
    )
    continuation = (
        {
            "hypothesis_id": candidate["hypothesis_id"],
            "source_todo_id": candidate["todo_id"],
            "failure_kind": candidate["failure_kind"],
            "measurement_scope": candidate.get("measurement_scope"),
            "remediation_attempt_count": candidate["remediation_attempt_count"],
            "remediation_attempt_limit": candidate["remediation_attempt_limit"],
            "next_outcome": candidate["next_outcome"],
            "monitor_allowed": False,
        }
        if candidate
        else None
    )
    return {
        "failure_continuation": continuation,
        "retirement_candidate_count": len(candidates),
        "matched_candidate_count": len(matched),
        "lineage_todo_id": lineage_todo_id or None,
        "selection_bound": selection_bound,
        "ambiguous": not selection_bound and len(candidates) > 1,
        "unresolved": require_selected_failure_match
        and bool(candidates)
        and (not lineage_todo_id or len(matched) != 1),
    }


def build_research_failure_continuation(
    decision_candidates: dict[str, list[dict[str, Any]]],
    *,
    selected_todo_id: str | None = None,
    selected_lineage_todo_id: str | None = None,
    allow_unbound_singleton: bool = True,
    require_selected_failure_match: bool = False,
) -> dict[str, Any] | None:
    resolution = build_research_failure_continuation_resolution(
        decision_candidates,
        selected_todo_id=selected_todo_id,
        selected_lineage_todo_id=selected_lineage_todo_id,
        allow_unbound_singleton=allow_unbound_singleton,
        require_selected_failure_match=require_selected_failure_match,
    )
    return resolution["failure_continuation"]


def _holdout_metric_sequence_from_graph(evidence_graph: dict[str, Any]) -> list[float]:
    sequence: list[float] = []
    for raw_node in evidence_graph.get("nodes") or []:
        if not isinstance(raw_node, dict):
            continue
        value = raw_node.get("best_holdout_metric")
        if value is None or isinstance(value, bool):
            continue
        number = _finite_float(value, field="node.best_holdout_metric")
        if number is not None:
            sequence.append(number)
    return sequence


def _metric_sequence_improvement_count(
    sequence: list[float],
    *,
    baseline: float | None,
    direction: str,
) -> int:
    if baseline is None:
        return 0
    count = 0
    previous = baseline
    minimize = direction == "minimize"
    for metric in sequence:
        improved = metric < previous if minimize else metric > previous
        if improved:
            count += 1
        previous = metric
    return count


def build_auto_research_completion_status(
    evidence_graph: dict[str, Any],
    decision_candidates: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    graph = _json_obj(evidence_graph, field="evidence_graph")
    decisions = decision_candidates or build_research_decision_candidates(graph)
    metric = graph.get("metric") if isinstance(graph.get("metric"), dict) else {}
    direction = str(metric.get("direction") or "maximize")
    if direction not in METRIC_DIRECTIONS:
        direction = "maximize"
    baseline = _finite_float(metric.get("baseline"), field="evidence_graph.metric.baseline")
    holdout_sequence = _holdout_metric_sequence_from_graph(graph)
    holdout_improvement_count = _metric_sequence_improvement_count(
        holdout_sequence,
        baseline=baseline,
        direction=direction,
    )
    required_holdout_improvement_count = AUTO_RESEARCH_REQUIRED_HOLDOUT_IMPROVEMENTS
    dev_pending_count = len(decisions.get("dev_promotion_candidates") or [])
    validated_count = len(decisions.get("validated_promotion_candidates") or [])
    promotion_count = len(decisions.get("promotion_candidates") or [])
    retirement_count = len(decisions.get("retirement_candidates") or [])
    failure_resolution = build_research_failure_continuation_resolution(
        decisions,
        allow_unbound_singleton=True,
    )
    failure_continuation = failure_resolution["failure_continuation"]

    status = "active"
    next_action = "continue_frontier"
    required_actions: list[str] = []
    quiet_completion_allowed = False
    reason = "frontier_still_active"
    if validated_count and holdout_improvement_count >= required_holdout_improvement_count:
        status = "target_reached"
        next_action = "quiet_completion"
        quiet_completion_allowed = True
        reason = "required_holdout_improvements_reached"
    elif dev_pending_count:
        status = "holdout_eval_required"
        next_action = "run_holdout_eval"
        required_actions = ["holdout_eval", "boundary_scan"]
        reason = "dev_promotion_candidate_pending_holdout"
    elif validated_count or promotion_count:
        status = "promotion_review_required"
        next_action = "review_promotion_readiness"
        required_actions = ["boundary_scan", "promotion_decision"]
        reason = "validated_promotion_candidate_pending_decision"
    elif retirement_count:
        status = "failure_successor_required"
        next_action = str(
            (failure_continuation or {}).get("next_outcome")
            or "propose_failure_successor"
        )
        required_actions = [next_action]
        reason = "retirement_candidate_requires_successor_or_exhaustion"

    return {
        "schema_version": AUTO_RESEARCH_COMPLETION_STATUS_SCHEMA_VERSION,
        "status": status,
        "next_action": next_action,
        "reason": reason,
        "quiet_completion_allowed": quiet_completion_allowed,
        "required_actions": required_actions,
        "required_holdout_improvement_count": required_holdout_improvement_count,
        "holdout_improvement_count": holdout_improvement_count,
        "holdout_metric_sequence": holdout_sequence,
        "validated_promotion_candidate_count": validated_count,
        "dev_candidate_pending_holdout_count": dev_pending_count,
        "promotion_candidate_count": promotion_count,
        "retirement_candidate_count": retirement_count,
        "failure_continuation": failure_continuation,
        "failure_continuation_ambiguous": failure_resolution["ambiguous"],
    }


def build_auto_research_projection(
    fixture: dict[str, Any],
    *,
    agent_id: str,
) -> dict[str, Any]:
    fixture = validate_auto_research_fixture(fixture)
    agent = _compact_public_token(agent_id, field="agent_id")
    contract = fixture["research_contract"]
    hypotheses = fixture["hypotheses"]
    evidence_graph = build_research_evidence_graph(fixture)
    decision_candidates = build_research_decision_candidates(evidence_graph)
    completion = build_auto_research_completion_status(evidence_graph, decision_candidates)

    runnable_statuses = {"active", "needs_retry"}
    selected = None
    blocked: list[dict[str, Any]] = []
    runnable: list[dict[str, Any]] = []
    for item in hypotheses:
        item_summary = {
            "hypothesis_id": item["hypothesis_id"],
            "todo_id": item["todo_id"],
            "claimed_by": item["claimed_by"],
            "status": item["status"],
            "mechanism_family": item["mechanism_family"],
        }
        if item["claimed_by"] == agent and item["status"] in runnable_statuses and not item["blocked_by"]:
            runnable.append(item_summary | {"allowed_action": "run_dev_attempt"})
            selected = selected or runnable[-1]
        elif item["claimed_by"] != agent and item["status"] in runnable_statuses:
            blocked.append(item_summary | {"blocked_by": f"claimed_by:{item['claimed_by']}"})
        elif item["blocked_by"]:
            blocked.append(item_summary | {"blocked_by": ",".join(item["blocked_by"])})

    frontier = {
        "schema_version": RESEARCH_FRONTIER_SCHEMA_VERSION,
        "goal_id": contract["goal_id"],
        "agent_id": agent,
        "selected": selected,
        "runnable": runnable,
        "blocked": blocked,
        "promotion_candidates": decision_candidates["promotion_candidates"],
        "retirement_candidates": decision_candidates["retirement_candidates"],
        "completion": completion,
    }
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_PROJECTION_SCHEMA_VERSION,
        "source_schema_version": fixture["schema_version"],
        "frontier": frontier,
        "evidence_graph": evidence_graph,
        "completion": completion,
        "public_boundary": {
            "raw_logs_recorded": False,
            "private_artifacts_recorded": False,
            "source": "public_fixture",
        },
    }


def build_live_auto_research_projection(
    *,
    goal_id: str,
    agent_id: str,
    quota_payload: dict[str, Any],
    rollout_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    goal = _compact_public_token(goal_id, field="goal_id")
    agent = _compact_public_token(agent_id, field="agent_id")
    if not quota_payload.get("ok"):
        raise ValueError("quota payload must be ok for live auto-research projection")

    runnable_candidates, blocked_candidates = _quota_payload_todo_candidates(quota_payload)
    selected_raw = quota_payload.get("agent_lane_next_action")
    selected = None
    if (
        isinstance(selected_raw, dict)
        and selected_raw.get("todo_id")
        and _claimed_by_current_or_unclaimed(selected_raw, agent_id=agent)
    ):
        selected = _todo_frontier_item(selected_raw, default_agent_id=agent)
    else:
        for item in runnable_candidates:
            if _claimed_by_current_or_unclaimed(item, agent_id=agent):
                selected = _todo_frontier_item(item, default_agent_id=agent)
                break

    runnable: list[dict[str, Any]] = []
    seen_todos: set[str] = set()
    for item in runnable_candidates:
        if not item.get("todo_id") or not _claimed_by_current_or_unclaimed(item, agent_id=agent):
            continue
        summary = _todo_frontier_item(item, default_agent_id=agent)
        if summary["todo_id"] in seen_todos:
            continue
        seen_todos.add(summary["todo_id"])
        runnable.append(summary)

    blocked: list[dict[str, Any]] = []
    other_claimed_context = [
        item
        for item in runnable_candidates
        if item.get("todo_id") and not _claimed_by_current_or_unclaimed(item, agent_id=agent)
    ]
    for item in [*other_claimed_context, *blocked_candidates][:12]:
        if not item.get("todo_id"):
            continue
        claimed_by = item.get("claimed_by")
        status = item.get("status") or "blocked"
        reason = f"claimed_by:{claimed_by}" if claimed_by and claimed_by != agent else f"status:{status}"
        blocked.append(_todo_frontier_item(item, default_agent_id=agent, blocked_by=reason))

    todo_graph = {
        "schema_version": RESEARCH_EVIDENCE_GRAPH_SCHEMA_VERSION,
        "goal_id": goal,
        "hypothesis_count": len(runnable) + len(blocked),
        "evidence_event_count": 0,
        "todo_ids": sorted({item["todo_id"] for item in [*runnable, *blocked]}),
        "agent_ids": sorted({item["claimed_by"] for item in [*runnable, *blocked]}),
        "metric": {
            "name": "runnable_hypotheses",
            "direction": "maximize",
            "baseline": 0.0,
        },
        "baseline_metric": None,
        "best_dev_metric": None,
        "best_holdout_metric": None,
        "holdout_improved": False,
        "negative_evidence_count": 0,
        "needs_retry_count": 0,
        "nodes": [
            {
                "hypothesis_id": item["hypothesis_id"],
                "parent_hypothesis_id": None,
                "todo_id": item["todo_id"],
                "claimed_by": item["claimed_by"],
                "status": item["status"],
                "source_kind": item["source_kind"],
            }
            for item in [*runnable, *blocked]
        ],
        "source_kind": "loopx_live_quota_status",
    }
    rollout_graph = build_research_evidence_graph_from_rollout_events(
        goal_id=goal,
        rollout_events=rollout_events or [],
    )
    evidence_graph = (
        rollout_graph
        if rollout_graph["evidence_event_count"] or rollout_graph["hypothesis_count"]
        else todo_graph
    )
    decisions = build_research_decision_candidates(evidence_graph)
    completion = build_auto_research_completion_status(evidence_graph, decisions)
    frontier = {
        "schema_version": RESEARCH_FRONTIER_SCHEMA_VERSION,
        "goal_id": goal,
        "agent_id": agent,
        "selected": selected,
        "runnable": runnable,
        "blocked": blocked,
        "promotion_candidates": decisions["promotion_candidates"],
        "retirement_candidates": decisions["retirement_candidates"],
        "completion": completion,
        "source_kind": "loopx_live_quota_status",
    }
    return {
        "ok": True,
        "schema_version": AUTO_RESEARCH_PROJECTION_SCHEMA_VERSION,
        "source_schema_version": "loopx_live_quota_status_v0",
        "frontier": frontier,
        "evidence_graph": evidence_graph,
        "decision_candidates": decisions,
        "completion": completion,
        "public_boundary": {
            "raw_logs_recorded": False,
            "private_artifacts_recorded": False,
            "source": (
                "live_quota_status_and_rollout_event_log"
                if evidence_graph.get("source_kind") == ROLLOUT_EVIDENCE_GRAPH_SOURCE_KIND
                else "live_quota_status_projection"
            ),
        },
    }

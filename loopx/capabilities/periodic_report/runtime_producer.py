from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from ...rollout_event_log import ROLLOUT_EVENT_SCHEMA_VERSION
from .core import (
    _integer,
    _object,
    _reject_raw_keys,
    _text,
    _timestamp,
    _token,
)
from .triggers import (
    build_periodic_report_trigger_decision,
    normalize_periodic_report_trigger_policy,
)


RUNTIME_TRIGGER_REQUEST_SCHEMA = "periodic_report_runtime_trigger_request_v0"
RUNTIME_PRODUCER_RECEIPT_SCHEMA = "periodic_report_runtime_producer_v0"
_MAX_RELEVANT_ROLLOUT_EVENTS = 4096

_SAFE_BOUNDARY_FIELDS = (
    "raw_task_text_recorded",
    "raw_logs_recorded",
    "raw_trajectory_recorded",
    "raw_session_transcript_recorded",
    "credential_values_recorded",
    "absolute_paths_recorded",
)


def _parsed_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event_digest(event_ids: Sequence[str]) -> str:
    encoded = json.dumps(
        sorted(event_ids),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _safe_durable_event(
    raw: Mapping[str, Any],
    *,
    goal_id: str,
    window_start: datetime,
    window_end: datetime,
    index: int,
) -> dict[str, Any] | None:
    label = f"rollout_events[{index}]"
    event = _object(raw, label)
    if event.get("schema_version") != ROLLOUT_EVENT_SCHEMA_VERSION:
        raise ValueError(f"{label} must use {ROLLOUT_EVENT_SCHEMA_VERSION}")
    if event.get("goal_id") != goal_id:
        return None
    kind = str(event.get("event_kind") or "").strip()
    if kind not in {"todo_complete", "refresh_state"}:
        return None
    recorded_at = _timestamp(event.get("recorded_at"), f"{label}.recorded_at")
    if not window_start <= _parsed_timestamp(recorded_at) <= window_end:
        return None
    event_id = _text(event.get("event_id"), f"{label}.event_id", maximum=128)
    boundary = _object(event.get("boundary"), f"{label}.boundary")
    if any(boundary.get(field) is not False for field in _SAFE_BOUNDARY_FIELDS):
        raise ValueError(f"{label}.boundary does not prove a public-safe event")
    details = (
        dict(event["details"])
        if isinstance(event.get("details"), Mapping)
        else {}
    )
    return {
        "event_id": event_id,
        "event_kind": kind,
        "recorded_at": recorded_at,
        "todo_id": str(event.get("todo_id") or "").strip() or None,
        "replan_recorded": details.get("autonomous_replan_recorded") is True,
    }


def build_periodic_report_runtime_trigger_decision(
    request: Mapping[str, Any],
    *,
    rollout_events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Promote durable control-plane events into one normal trigger decision.

    This is the provider-neutral post-writeback producer seam. It reads no files
    and performs no writes; the CLI adapter supplies events read from the durable
    rollout log, then the existing trigger decision remains authoritative.
    """

    payload = _object(request, "request")
    _reject_raw_keys(payload, "request")
    unknown = sorted(
        set(payload)
        - {
            "schema_version",
            "evaluated_at",
            "goal_id",
            "profile",
            "trigger_policy",
            "segment",
            "last_report",
        }
    )
    if unknown:
        raise ValueError("request contains unsupported fields: " + ", ".join(unknown))
    if payload.get("schema_version") != RUNTIME_TRIGGER_REQUEST_SCHEMA:
        raise ValueError(f"schema_version must be {RUNTIME_TRIGGER_REQUEST_SCHEMA!r}")
    evaluated_at = _timestamp(payload.get("evaluated_at"), "evaluated_at")
    goal_id = _token(payload.get("goal_id"), "goal_id")
    policy = normalize_periodic_report_trigger_policy(
        payload.get("trigger_policy", {})
    )
    aggregation = policy.get("aggregation")
    if not isinstance(aggregation, Mapping):
        raise ValueError("trigger_policy.aggregation is required for runtime promotion")

    segment = _object(payload.get("segment"), "segment")
    segment_ref = _token(segment.get("segment_ref"), "segment.segment_ref")
    start_at = _timestamp(segment.get("start_at"), "segment.start_at")
    end_at = _timestamp(segment.get("end_at"), "segment.end_at")
    window_start = _parsed_timestamp(start_at)
    window_end = _parsed_timestamp(end_at)
    if window_start >= window_end:
        raise ValueError("segment.start_at must be earlier than segment.end_at")
    if end_at != evaluated_at:
        raise ValueError("segment.end_at must match evaluated_at")
    duration = int((window_end - window_start).total_seconds())
    if duration > int(aggregation["window_seconds"]):
        raise ValueError("segment window exceeds trigger_policy.aggregation.window_seconds")
    remaining_todo_count = _integer(
        segment.get("remaining_todo_count"),
        "segment.remaining_todo_count",
        maximum=1_000_000,
    )
    if isinstance(rollout_events, (str, bytes, Mapping)):
        raise ValueError("rollout_events must be an iterable of objects")

    relevant: list[dict[str, Any]] = []
    relevant_count = 0
    seen_event_ids: set[str] = set()
    for index, raw_event in enumerate(rollout_events):
        event = _safe_durable_event(
            raw_event,
            goal_id=goal_id,
            window_start=window_start,
            window_end=window_end,
            index=index,
        )
        if event is None:
            continue
        relevant_count += 1
        if relevant_count > _MAX_RELEVANT_ROLLOUT_EVENTS:
            raise ValueError(
                "rollout_events must contain at most "
                f"{_MAX_RELEVANT_ROLLOUT_EVENTS} relevant window items"
            )
        event_id = str(event["event_id"])
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        relevant.append(event)
    relevant.sort(key=lambda item: (item["recorded_at"], item["event_id"]))

    completions: list[dict[str, Any]] = []
    seen_completion_keys: set[str] = set()
    replans: list[dict[str, Any]] = []
    for event in relevant:
        if event["event_kind"] == "todo_complete":
            completion_key = str(event.get("todo_id") or event["event_id"])
            if completion_key not in seen_completion_keys:
                seen_completion_keys.add(completion_key)
                completions.append(event)
        elif event["replan_recorded"]:
            replans.append(event)

    transition: str | None = None
    contributing: list[dict[str, Any]] = []
    delivered_count = 0
    if aggregation["promote_replan"] and replans:
        boundary_event = replans[0]
        transition = "replan_entered"
        contributing = [boundary_event]
        delivered_count = sum(
            event["recorded_at"] <= boundary_event["recorded_at"]
            for event in completions
        )
    else:
        threshold = aggregation.get("todo_completed_threshold")
        if threshold is not None and len(completions) >= int(threshold):
            transition = "segment_completed"
            contributing = completions[: int(threshold)]
            delivered_count = int(threshold)

    source_ref = f"rollout-window:{goal_id}:{segment_ref}"
    if transition:
        evidence_ids = [str(event["event_id"]) for event in contributing]
        candidate = {
            "trigger_kind": "bounded_segment_milestone",
            "observed_at": str(contributing[-1]["recorded_at"]),
            "source_ref": source_ref,
            "evidence_digest": _event_digest(evidence_ids),
            "facts": {
                "segment_ref": segment_ref,
                "transition": transition,
                "delivered_count": delivered_count,
                "remaining_todo_count": remaining_todo_count,
                "durable_writeback": True,
            },
        }
        status = "promoted"
        reason = (
            "durable_replan_observed"
            if transition == "replan_entered"
            else "todo_completion_threshold_reached"
        )
    else:
        evidence_ids = [str(event["event_id"]) for event in relevant]
        candidate = {
            "trigger_kind": "state_refreshed",
            "observed_at": end_at,
            "source_ref": source_ref,
            "evidence_digest": _event_digest(evidence_ids or [segment_ref]),
            "facts": {},
        }
        status = "not_promoted"
        reason = "promotion_conditions_not_met"

    trigger_request: dict[str, Any] = {
        "schema_version": "periodic_report_trigger_request_v0",
        "evaluated_at": evaluated_at,
        "profile": payload.get("profile"),
        "trigger_policy": policy,
        "candidates": [candidate],
    }
    if payload.get("last_report") is not None:
        trigger_request["last_report"] = payload["last_report"]
    decision = build_periodic_report_trigger_decision(trigger_request)
    decision["producer_receipt"] = {
        "schema_version": RUNTIME_PRODUCER_RECEIPT_SCHEMA,
        "status": status,
        "reason": reason,
        "goal_id": goal_id,
        "segment_ref": segment_ref,
        "window": {"start_at": start_at, "end_at": end_at},
        "todo_completed_count": len(completions),
        "replan_event_count": len(replans),
        "contributing_event_ids": evidence_ids,
        "transition": transition,
        "boundary": {
            "durable_rollout_events_required": True,
            "provider_neutral": True,
            "external_writes_performed": False,
            "raw_content_persisted": False,
        },
    }
    return decision

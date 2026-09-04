"""Compact read-only diagnostic projection derived from event kinds and timing.

This projection is a sibling of the session-runtime projection, never merged
into it. It carries explicit boundary fields (``mode``, ``authority``) so a
consumer can prove it holds no runtime authority, and every signal is derived
from typed event kinds and observed timestamps only.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .envelope import CAPABILITY_ID, ObserverEnvelope, ObserverEventKind, parse_observed_at
from .receipt import LedgerReading, build_integrity_receipt

DIAGNOSTIC_PROJECTION_SCHEMA_VERSION = "reliability_diagnostic_projection_v0"
DEFAULT_STALL_THRESHOLD_MS = 300_000
DEFAULT_REPETITION_THRESHOLD = 3
_TERMINAL_ERROR_REASONS = frozenset({"error", "failed", "failure", "aborted", "cancelled", "canceled", "timeout"})


class DiagnosticStage(StrEnum):
    UNKNOWN = "unknown"
    IDLE = "idle"
    RUNNING = "running"
    TOOL_RUNNING = "tool_running"
    ERRORED = "errored"
    DISPOSED = "disposed"


class DiagnosticSignal(StrEnum):
    STALL_SUSPECTED = "stall_suspected"
    REPETITION_SUSPECTED = "repetition_suspected"
    UNRECOVERED_ERROR = "unrecovered_error"
    EVENT_LOSS = "event_loss"
    INTEGRITY_NOT_VALID = "integrity_not_valid"


_ACTIVE_STAGES = frozenset({DiagnosticStage.RUNNING, DiagnosticStage.TOOL_RUNNING})


def _stage_after(envelope: ObserverEnvelope) -> DiagnosticStage:
    kind = envelope.event_kind
    if kind is ObserverEventKind.SESSION_DISPOSED:
        return DiagnosticStage.DISPOSED
    if kind is ObserverEventKind.AGENT_ERROR:
        return DiagnosticStage.ERRORED
    if kind is ObserverEventKind.TOOL_CALLED:
        return DiagnosticStage.TOOL_RUNNING
    if kind in {ObserverEventKind.TURN_ENDED, ObserverEventKind.SESSION_STARTED}:
        return DiagnosticStage.IDLE
    if kind is ObserverEventKind.AGENT_STATUS:
        return DiagnosticStage.RUNNING if envelope.summary.get("status") == "running" else DiagnosticStage.IDLE
    if kind is ObserverEventKind.UNSUPPORTED:
        return DiagnosticStage.UNKNOWN
    return DiagnosticStage.RUNNING


def _ms_between(earlier: str, later: str) -> int:
    return int((parse_observed_at(later) - parse_observed_at(earlier)).total_seconds() * 1000)


def build_diagnostic_projection(
    reading: LedgerReading,
    *,
    as_of: str | None = None,
    stall_threshold_ms: int = DEFAULT_STALL_THRESHOLD_MS,
    repetition_threshold: int = DEFAULT_REPETITION_THRESHOLD,
) -> dict[str, Any]:
    receipt = build_integrity_receipt(reading)
    envelopes = reading.ordered_envelopes

    counts = {"turns_started": 0, "turns_ended": 0, "steps": 0, "tool_calls": 0, "errors": 0}
    stage = DiagnosticStage.UNKNOWN
    max_gap_ms = 0
    longest_run = 0
    longest_run_tool: str | None = None
    current_run = 0
    current_tool: str | None = None
    unrecovered_errors = 0
    recovered_errors = 0
    previous: ObserverEnvelope | None = None
    for envelope in envelopes:
        kind = envelope.event_kind
        if previous is not None:
            max_gap_ms = max(max_gap_ms, _ms_between(previous.observed_at, envelope.observed_at))
        if kind is ObserverEventKind.TURN_STARTED:
            counts["turns_started"] += 1
        elif kind is ObserverEventKind.TURN_ENDED:
            counts["turns_ended"] += 1
            if unrecovered_errors and str(envelope.summary.get("reason", "")) not in _TERMINAL_ERROR_REASONS:
                recovered_errors += unrecovered_errors
                unrecovered_errors = 0
        elif kind is ObserverEventKind.STEP_ENDED:
            counts["steps"] += 1
            if unrecovered_errors:
                recovered_errors += unrecovered_errors
                unrecovered_errors = 0
        elif kind is ObserverEventKind.AGENT_ERROR:
            counts["errors"] += 1
            unrecovered_errors += 1
        if kind is ObserverEventKind.TOOL_CALLED:
            counts["tool_calls"] += 1
            tool = str(envelope.summary.get("tool_name", ""))
            current_run = current_run + 1 if tool == current_tool else 1
            current_tool = tool
            if current_run > longest_run:
                longest_run, longest_run_tool = current_run, tool or None
        elif kind not in {ObserverEventKind.TOOL_COMPLETED, ObserverEventKind.AGENT_PRE_STEP}:
            current_run, current_tool = 0, None
        stage = _stage_after(envelope)
        previous = envelope

    last_observed_at = previous.observed_at if previous else None
    effective_as_of = as_of or last_observed_at
    last_event_age_ms = _ms_between(last_observed_at, effective_as_of) if last_observed_at and effective_as_of else 0
    stall_detected = stage in _ACTIVE_STAGES and last_event_age_ms >= stall_threshold_ms
    repetition_detected = longest_run >= repetition_threshold

    signals: list[str] = []
    if stall_detected:
        signals.append(DiagnosticSignal.STALL_SUSPECTED.value)
    if repetition_detected:
        signals.append(DiagnosticSignal.REPETITION_SUSPECTED.value)
    if unrecovered_errors:
        signals.append(DiagnosticSignal.UNRECOVERED_ERROR.value)
    if receipt["lost_event_count"] or receipt["backpressure_drop_count"]:
        signals.append(DiagnosticSignal.EVENT_LOSS.value)
    if receipt["status"] != "valid":
        signals.append(DiagnosticSignal.INTEGRITY_NOT_VALID.value)

    return {
        "schema_version": DIAGNOSTIC_PROJECTION_SCHEMA_VERSION,
        "capability_id": CAPABILITY_ID,
        "goal_id": reading.goal_id,
        "mode": "read_only",
        "authority": "none",
        "write_scope": "diagnostic_ledger_only",
        "worker_influence": "none",
        "provider_ids": receipt["provider_ids"],
        "stage": stage.value,
        "counts": counts,
        "stall": {
            "detected": stall_detected,
            "threshold_ms": stall_threshold_ms,
            "last_event_age_ms": last_event_age_ms,
            "max_inter_event_gap_ms": max_gap_ms,
        },
        "repetition": {
            "detected": repetition_detected,
            "threshold": repetition_threshold,
            "longest_tool_run": longest_run,
            "tool_name": longest_run_tool,
        },
        "recovery": {
            "error_count": counts["errors"],
            "recovered_error_count": recovered_errors,
            "unrecovered_error_count": unrecovered_errors,
        },
        "signals": signals,
        "integrity": {"status": receipt["status"], "reason_codes": receipt["reason_codes"]},
        "evidence": {
            "observed_event_count": receipt["observed_event_count"],
            "lost_event_count": receipt["lost_event_count"],
            "session_count": receipt["session_count"],
            "observed_from": receipt["observed_from"],
            "observed_until": receipt["observed_until"],
            "as_of": effective_as_of,
        },
    }

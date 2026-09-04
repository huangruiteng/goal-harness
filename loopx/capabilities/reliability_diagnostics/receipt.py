"""Treatment-integrity receipt for one goal's shadow-observer ledger.

The receipt answers whether the ledger is admissible passive evidence. It is
computed only from ledger records: accepted envelopes and observer stats. Its
status enum is total and ordered; every non-``valid`` status names typed reason
codes so an operator never has to infer why evidence was downgraded.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .envelope import (
    CAPABILITY_ID,
    OBSERVER_ENVELOPE_SCHEMA_VERSION,
    OBSERVER_STATS_SCHEMA_VERSION,
    EnvelopeRejection,
    ObserverEnvelope,
    ObserverEnvelopeError,
    normalize_observer_envelope,
)
from .intake import ObserverStats, normalize_observer_stats

INTEGRITY_RECEIPT_SCHEMA_VERSION = "reliability_integrity_receipt_v0"
DEFAULT_CLOCK_UNCERTAINTY_DEGRADED_MS = 1000


class ReceiptStatus(StrEnum):
    VALID = "valid"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"
    INVALID = "invalid"


class ReceiptReason(StrEnum):
    NO_OBSERVATIONS = "no_observations"
    OUTBOUND_ENDPOINT_CONFIGURED = "outbound_endpoint_configured"
    OBSERVATION_ENTERED_WORKER_CONTEXT = "observation_entered_worker_context"
    OBSERVER_FAILURE = "observer_failure"
    CONTROL_FIELD_REJECTED = "control_field_rejected"
    LEDGER_RECORD_INVALID = "ledger_record_invalid"
    OBSERVER_STATS_MISSING = "observer_stats_missing"
    OBSERVER_STATS_MISMATCH = "observer_stats_mismatch"
    IDENTITY_REJECTED = "identity_rejected"
    OBSERVATION_ENTERED_SCHEDULER_INPUTS = "observation_entered_scheduler_inputs"
    SEQUENCE_GAP = "sequence_gap"
    SEQUENCE_DUPLICATE = "sequence_duplicate"
    BACKPRESSURE_DROP = "backpressure_drop"
    RAW_MATERIAL_REJECTED = "raw_material_rejected"
    UNSUPPORTED_FIELD_REJECTED = "unsupported_field_rejected"
    CLOCK_UNCERTAINTY_EXCEEDED = "clock_uncertainty_exceeded"


_INVALID_REASONS = frozenset(
    {
        ReceiptReason.NO_OBSERVATIONS,
        ReceiptReason.OUTBOUND_ENDPOINT_CONFIGURED,
        ReceiptReason.OBSERVATION_ENTERED_WORKER_CONTEXT,
        ReceiptReason.OBSERVATION_ENTERED_SCHEDULER_INPUTS,
        ReceiptReason.LEDGER_RECORD_INVALID,
        ReceiptReason.OBSERVER_STATS_MISSING,
        ReceiptReason.OBSERVER_STATS_MISMATCH,
        ReceiptReason.IDENTITY_REJECTED,
    }
)
_QUARANTINE_REASONS = frozenset(
    {
        ReceiptReason.OBSERVER_FAILURE,
        ReceiptReason.CONTROL_FIELD_REJECTED,
    }
)


@dataclass
class LedgerReading:
    """Typed, ordered view over one goal ledger's records."""

    goal_id: str
    envelopes: list[ObserverEnvelope] = field(default_factory=list)
    stats: dict[str, ObserverStats] = field(default_factory=dict)
    invalid_record_count: int = 0

    @property
    def ordered_envelopes(self) -> list[ObserverEnvelope]:
        return sorted(self.envelopes, key=lambda item: (item.observed_at, item.session_id, item.sequence))


def read_ledger(records: Iterable[Any], *, goal_id: str, malformed_line_count: int = 0) -> LedgerReading:
    reading = LedgerReading(goal_id=goal_id, invalid_record_count=malformed_line_count)
    for record in records:
        if not isinstance(record, Mapping):
            reading.invalid_record_count += 1
            continue
        schema = record.get("schema_version")
        try:
            if schema == OBSERVER_ENVELOPE_SCHEMA_VERSION:
                envelope = normalize_observer_envelope(record)
                if envelope.goal_id != goal_id:
                    raise ObserverEnvelopeError(
                        EnvelopeRejection.IDENTITY_INVALID, "goal_id does not match ledger"
                    )
                reading.envelopes.append(envelope)
            elif schema == OBSERVER_STATS_SCHEMA_VERSION:
                stats = normalize_observer_stats(record)
                if stats.goal_id != goal_id:
                    raise ValueError("goal_id does not match ledger")
                # Stats are cumulative per observer instance; the latest wins,
                # but one observer id may never change its identity mid-ledger.
                previous = reading.stats.get(stats.observer_id)
                if previous is not None and (
                    previous.provider_id != stats.provider_id
                    or previous.run_identity != stats.run_identity
                ):
                    raise ValueError("observer stats identity changed within one ledger")
                reading.stats[stats.observer_id] = stats
            else:
                raise ValueError("unknown ledger record schema")
        except ValueError:
            reading.invalid_record_count += 1
    return reading


def _sequence_accounting(envelopes: Iterable[ObserverEnvelope]) -> tuple[int, int]:
    by_session: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for envelope in envelopes:
        by_session[
            (envelope.provider_id, envelope.observer_id, envelope.session_id)
        ].append(envelope.sequence)
    lost = 0
    duplicates = 0
    for sequences in by_session.values():
        ordered = sorted(sequences)
        for previous, current in zip(ordered, ordered[1:]):
            if current == previous:
                duplicates += 1
            else:
                lost += current - previous - 1
    return lost, duplicates


def build_integrity_receipt(
    reading: LedgerReading,
    *,
    clock_uncertainty_degraded_ms: int = DEFAULT_CLOCK_UNCERTAINTY_DEGRADED_MS,
) -> dict[str, Any]:
    envelopes = reading.ordered_envelopes
    stats = list(reading.stats.values())
    lost, duplicates = _sequence_accounting(envelopes)
    rejected_by_reason: dict[str, int] = defaultdict(int)
    for item in stats:
        for reason, count in item.rejected_by_reason.items():
            rejected_by_reason[reason] += count
    outbound_endpoints = sorted({endpoint for item in stats for endpoint in item.outbound_endpoints})
    entered_worker_context = any(item.observation_entered_worker_context for item in stats)
    entered_scheduler_inputs = any(
        item.observation_entered_scheduler_inputs for item in stats
    )
    observer_failures = sum(item.observer_failure_count for item in stats)
    backpressure_drops = sum(item.backpressure_drop_count for item in stats)
    max_uncertainty = max((item.clock.uncertainty_ms for item in envelopes), default=0)
    clock_sources = sorted({item.clock.source.value for item in envelopes} | {item.clock_source.value for item in stats})

    envelopes_by_observer: dict[str, list[ObserverEnvelope]] = defaultdict(list)
    for envelope in envelopes:
        envelopes_by_observer[envelope.observer_id].append(envelope)
    stats_mismatch = False
    for observer_id, observer_envelopes in envelopes_by_observer.items():
        observer_stats = reading.stats.get(observer_id)
        if observer_stats is None:
            continue
        if (
            {item.provider_id for item in observer_envelopes}
            != {observer_stats.provider_id}
            or observer_stats.accepted_event_count != len(observer_envelopes)
        ):
            stats_mismatch = True
    if any(
        item.accepted_event_count and observer_id not in envelopes_by_observer
        for observer_id, item in reading.stats.items()
    ):
        stats_mismatch = True

    reasons: set[ReceiptReason] = set()
    if not envelopes:
        reasons.add(ReceiptReason.NO_OBSERVATIONS)
    if outbound_endpoints:
        reasons.add(ReceiptReason.OUTBOUND_ENDPOINT_CONFIGURED)
    if entered_worker_context:
        reasons.add(ReceiptReason.OBSERVATION_ENTERED_WORKER_CONTEXT)
    if entered_scheduler_inputs:
        reasons.add(ReceiptReason.OBSERVATION_ENTERED_SCHEDULER_INPUTS)
    if observer_failures:
        reasons.add(ReceiptReason.OBSERVER_FAILURE)
    if rejected_by_reason.get(EnvelopeRejection.CONTROL_FIELD_REJECTED.value):
        reasons.add(ReceiptReason.CONTROL_FIELD_REJECTED)
    if reading.invalid_record_count:
        reasons.add(ReceiptReason.LEDGER_RECORD_INVALID)
    if envelopes and any(
        observer_id not in reading.stats for observer_id in envelopes_by_observer
    ):
        reasons.add(ReceiptReason.OBSERVER_STATS_MISSING)
    if stats_mismatch:
        reasons.add(ReceiptReason.OBSERVER_STATS_MISMATCH)
    if lost:
        reasons.add(ReceiptReason.SEQUENCE_GAP)
    if duplicates:
        reasons.add(ReceiptReason.SEQUENCE_DUPLICATE)
    if backpressure_drops:
        reasons.add(ReceiptReason.BACKPRESSURE_DROP)
    if rejected_by_reason.get(EnvelopeRejection.RAW_MATERIAL_FIELD_REJECTED.value):
        reasons.add(ReceiptReason.RAW_MATERIAL_REJECTED)
    if rejected_by_reason.get(EnvelopeRejection.UNSUPPORTED_FIELD_REJECTED.value):
        reasons.add(ReceiptReason.UNSUPPORTED_FIELD_REJECTED)
    if rejected_by_reason.get(EnvelopeRejection.IDENTITY_INVALID.value):
        reasons.add(ReceiptReason.IDENTITY_REJECTED)
    if max_uncertainty > clock_uncertainty_degraded_ms:
        reasons.add(ReceiptReason.CLOCK_UNCERTAINTY_EXCEEDED)

    if reasons & _INVALID_REASONS:
        status = ReceiptStatus.INVALID
    elif reasons & _QUARANTINE_REASONS:
        status = ReceiptStatus.QUARANTINED
    elif reasons:
        status = ReceiptStatus.DEGRADED
    else:
        status = ReceiptStatus.VALID

    return {
        "schema_version": INTEGRITY_RECEIPT_SCHEMA_VERSION,
        "capability_id": CAPABILITY_ID,
        "goal_id": reading.goal_id,
        "status": status.value,
        "reason_codes": sorted(reason.value for reason in reasons),
        "provider_ids": sorted({item.provider_id for item in envelopes} | {item.provider_id for item in stats}),
        "observer_ids": sorted(set(reading.stats) | set(envelopes_by_observer)),
        "session_count": len({item.session_id for item in envelopes}),
        "observed_event_count": sum(item.observed_event_count for item in stats),
        "accepted_event_count": sum(item.accepted_event_count for item in stats),
        "persisted_event_count": len(envelopes),
        "lost_event_count": lost,
        "duplicate_sequence_count": duplicates,
        "ledger_invalid_record_count": reading.invalid_record_count,
        "rejected_event_count": sum(rejected_by_reason.values()),
        "rejected_by_reason": dict(sorted(rejected_by_reason.items())),
        "buffer_bound": max((item.buffer_bound for item in stats), default=None),
        "backpressure_drop_count": backpressure_drops,
        "observer_failure_count": observer_failures,
        "peak_buffered_event_count": max(
            (item.peak_buffered_event_count for item in stats), default=0
        ),
        "flush_attempt_count": sum(item.flush_attempt_count for item in stats),
        "clock": {"sources": clock_sources, "max_uncertainty_ms": max_uncertainty},
        "outbound_endpoints": outbound_endpoints,
        "observation_entered_worker_context": entered_worker_context,
        "observation_entered_scheduler_inputs": entered_scheduler_inputs,
        "run_identities": [
            item.run_identity.as_dict()
            for item in sorted(stats, key=lambda candidate: candidate.observer_id)
        ],
        "event_sources": sorted(
            {source for item in stats for source in item.event_sources}
        ),
        "source_fields_consumed": sorted(
            {field for item in stats for field in item.source_fields_consumed}
        ),
        "event_kinds_consumed": sorted({item.event_kind.value for item in envelopes}),
        "summary_fields_consumed": sorted({key for item in envelopes for key in item.summary}),
        "observed_from": envelopes[0].observed_at if envelopes else None,
        "observed_until": envelopes[-1].observed_at if envelopes else None,
    }

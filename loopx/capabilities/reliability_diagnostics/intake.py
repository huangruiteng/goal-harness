"""Bounded, crash-isolated observer intake and its stats record.

The intake is the provider-neutral reference for the L1 observer runtime
contract: a bounded buffer whose overflow is counted rather than blocking, an
``observe`` call that never raises into the caller, and a stats record that
carries the receipt inputs (buffer bound, drops, failures, outbound endpoints)
next to the envelopes it accepted. The DSH TypeScript observer implements the
same shape and writes the same stats record.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .envelope import (
    CAPABILITY_ID,
    IDENTITY_TOKEN_PATTERN,
    OBSERVER_STATS_SCHEMA_VERSION,
    ClockSource,
    EnvelopeRejection,
    ObserverEnvelope,
    ObserverEnvelopeError,
    normalize_observer_envelope,
)

DEFAULT_BUFFER_BOUND = 256
MAX_BUFFER_BOUND = 65_536
_ENDPOINT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,200}$")

STATS_FIELDS = frozenset(
    {
        "schema_version",
        "capability_id",
        "provider_id",
        "observer_id",
        "goal_id",
        "emitted_at",
        "observed_event_count",
        "accepted_event_count",
        "rejected_event_count",
        "rejected_by_reason",
        "buffer_bound",
        "backpressure_drop_count",
        "observer_failure_count",
        "outbound_endpoints",
        "observation_entered_worker_context",
        "clock_source",
    }
)


@dataclass(frozen=True)
class ObserverStats:
    provider_id: str
    observer_id: str
    goal_id: str
    emitted_at: str
    observed_event_count: int
    accepted_event_count: int
    rejected_event_count: int
    rejected_by_reason: Mapping[str, int]
    buffer_bound: int
    backpressure_drop_count: int
    observer_failure_count: int
    outbound_endpoints: tuple[str, ...]
    observation_entered_worker_context: bool
    clock_source: ClockSource

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OBSERVER_STATS_SCHEMA_VERSION,
            "capability_id": CAPABILITY_ID,
            "provider_id": self.provider_id,
            "observer_id": self.observer_id,
            "goal_id": self.goal_id,
            "emitted_at": self.emitted_at,
            "observed_event_count": self.observed_event_count,
            "accepted_event_count": self.accepted_event_count,
            "rejected_event_count": self.rejected_event_count,
            "rejected_by_reason": dict(self.rejected_by_reason),
            "buffer_bound": self.buffer_bound,
            "backpressure_drop_count": self.backpressure_drop_count,
            "observer_failure_count": self.observer_failure_count,
            "outbound_endpoints": list(self.outbound_endpoints),
            "observation_entered_worker_context": self.observation_entered_worker_context,
            "clock_source": self.clock_source.value,
        }


def _count(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"observer stats {name} must be a non-negative integer")
    return value


def normalize_observer_stats(record: Mapping[str, Any]) -> ObserverStats:
    """Validate one stats record written by any observer implementation."""

    if not isinstance(record, Mapping):
        raise ValueError("observer stats must be an object")
    unknown = sorted(str(key) for key in record if str(key) not in STATS_FIELDS)
    if unknown:
        raise ValueError(f"observer stats carry unsupported fields: {unknown}")
    if record.get("schema_version") != OBSERVER_STATS_SCHEMA_VERSION:
        raise ValueError(f"observer stats schema must be {OBSERVER_STATS_SCHEMA_VERSION}")
    if record.get("capability_id") != CAPABILITY_ID:
        raise ValueError(f"observer stats capability must be {CAPABILITY_ID}")
    for key in ("provider_id", "observer_id", "goal_id"):
        value = record.get(key)
        if not isinstance(value, str) or not IDENTITY_TOKEN_PATTERN.match(value):
            raise ValueError(f"observer stats {key} must be an identity token")
    emitted_at = record.get("emitted_at")
    if not isinstance(emitted_at, str) or not emitted_at.strip():
        raise ValueError("observer stats emitted_at is required")
    reasons = record.get("rejected_by_reason") or {}
    if not isinstance(reasons, Mapping):
        raise ValueError("observer stats rejected_by_reason must be an object")
    normalized_reasons = {
        EnvelopeRejection(str(key)).value: _count(value, name=f"rejected_by_reason.{key}")
        for key, value in reasons.items()
    }
    endpoints = record.get("outbound_endpoints")
    if not isinstance(endpoints, list) or any(
        not isinstance(item, str) or not _ENDPOINT_PATTERN.match(item)
        for item in endpoints
    ):
        raise ValueError("observer stats outbound_endpoints must be a list of endpoint ids")
    entered = record.get("observation_entered_worker_context")
    if not isinstance(entered, bool):
        raise ValueError("observer stats observation_entered_worker_context must be boolean")
    buffer_bound = _count(record.get("buffer_bound"), name="buffer_bound")
    if not 1 <= buffer_bound <= MAX_BUFFER_BOUND:
        raise ValueError(f"observer stats buffer_bound must be within 1..{MAX_BUFFER_BOUND}")
    return ObserverStats(
        provider_id=str(record["provider_id"]),
        observer_id=str(record["observer_id"]),
        goal_id=str(record["goal_id"]),
        emitted_at=emitted_at,
        observed_event_count=_count(
            record.get("observed_event_count"), name="observed_event_count"
        ),
        accepted_event_count=_count(
            record.get("accepted_event_count"), name="accepted_event_count"
        ),
        rejected_event_count=_count(
            record.get("rejected_event_count"), name="rejected_event_count"
        ),
        rejected_by_reason=normalized_reasons,
        buffer_bound=buffer_bound,
        backpressure_drop_count=_count(
            record.get("backpressure_drop_count"), name="backpressure_drop_count"
        ),
        observer_failure_count=_count(
            record.get("observer_failure_count"), name="observer_failure_count"
        ),
        outbound_endpoints=tuple(endpoints),
        observation_entered_worker_context=entered,
        clock_source=ClockSource(str(record.get("clock_source"))),
    )


@dataclass
class ShadowObserverIntake:
    """Reference intake: bounded buffer, counted drops, isolated failures."""

    provider_id: str
    observer_id: str
    goal_id: str
    clock_source: ClockSource
    buffer_bound: int = DEFAULT_BUFFER_BOUND
    observed_event_count: int = 0
    accepted_event_count: int = 0
    rejected_event_count: int = 0
    backpressure_drop_count: int = 0
    observer_failure_count: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)
    _buffer: deque[ObserverEnvelope] = field(default_factory=deque, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.buffer_bound <= MAX_BUFFER_BOUND:
            raise ValueError(f"buffer_bound must be within 1..{MAX_BUFFER_BOUND}")
        for key in ("provider_id", "observer_id", "goal_id"):
            if not IDENTITY_TOKEN_PATTERN.match(getattr(self, key)):
                raise ValueError(f"{key} must be an identity token")

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    def observe(self, record: Any) -> bool:
        """Accept or refuse one record; never raise into the event source."""

        self.observed_event_count += 1
        try:
            envelope = normalize_observer_envelope(record)
        except ObserverEnvelopeError as exc:
            self.rejected_event_count += 1
            reason = exc.reason.value
            self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
            return False
        except Exception:  # noqa: BLE001 - crash isolation is the contract
            self.observer_failure_count += 1
            return False
        if envelope.goal_id != self.goal_id:
            self.rejected_event_count += 1
            reason = EnvelopeRejection.IDENTITY_INVALID.value
            self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
            return False
        if len(self._buffer) >= self.buffer_bound:
            self.backpressure_drop_count += 1
            return False
        self._buffer.append(envelope)
        self.accepted_event_count += 1
        return True

    def drain(self) -> list[ObserverEnvelope]:
        drained = list(self._buffer)
        self._buffer.clear()
        return drained

    def stats(self, *, emitted_at: str) -> ObserverStats:
        return ObserverStats(
            provider_id=self.provider_id,
            observer_id=self.observer_id,
            goal_id=self.goal_id,
            emitted_at=emitted_at,
            observed_event_count=self.observed_event_count,
            accepted_event_count=self.accepted_event_count,
            rejected_event_count=self.rejected_event_count,
            rejected_by_reason=dict(self.rejected_by_reason),
            buffer_bound=self.buffer_bound,
            backpressure_drop_count=self.backpressure_drop_count,
            observer_failure_count=self.observer_failure_count,
            outbound_endpoints=(),
            observation_entered_worker_context=False,
            clock_source=self.clock_source,
        )

    def flush(
        self,
        sink: Callable[[list[dict[str, Any]]], None],
        *,
        emitted_at: str,
    ) -> list[dict[str, Any]]:
        """Hand drained envelopes plus a stats record to ``sink``.

        A failing sink is counted as an observer failure and its envelopes are
        counted as backpressure drops; the failure never propagates.
        """

        envelopes = self.drain()
        records = [envelope.as_dict() for envelope in envelopes]
        try:
            sink([*records, self.stats(emitted_at=emitted_at).as_dict()])
        except Exception:  # noqa: BLE001 - crash isolation is the contract
            self.observer_failure_count += 1
            self.backpressure_drop_count += len(records)
            return []
        return records

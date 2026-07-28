"""Domain-neutral addressable execution traces for Explore Episode V2.

Core records contain only public-safe lineage and agent-history cursors. Live
environment state, screenshots, credentials, and paths remain Adapter-owned.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePath
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence


class TraceEventKind(str, Enum):
    AGENT_CONTEXT = "agent_context"
    ACTION_INTENT = "action_intent"
    ACTION_OUTCOME = "action_outcome"
    ENVIRONMENT_OBSERVATION = "environment_observation"
    VALIDATION = "validation"
    LIFECYCLE = "lifecycle"


_FORBIDDEN_PUBLIC_KEYS = {
    "adapter_state",
    "credential",
    "credentials",
    "environment_state",
    "file_path",
    "handle",
    "live_handle",
    "password",
    "path",
    "raw_screenshot",
    "screenshot_bytes",
    "secret",
    "software_state",
    "token",
}
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _freeze_public_value(value: Any, *, field_path: str) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value.startswith(("/", "\\\\")) or _WINDOWS_ABSOLUTE_PATH.match(value):
            raise ValueError(
                f"public trace payload must not contain absolute paths: {field_path}"
            )
        return value
    if isinstance(value, (bytes, bytearray, memoryview, PurePath)):
        raise TypeError(
            f"public trace payload must not contain binary or path values: {field_path}"
        )
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for raw_key, child in value.items():
            if not isinstance(raw_key, str) or not raw_key:
                raise TypeError("public trace payload keys must be non-empty strings")
            normalized_key = raw_key.strip().lower()
            if normalized_key in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(
                    "adapter-owned or sensitive state must not enter public trace "
                    f"payloads: {field_path}.{raw_key}"
                )
            frozen[raw_key] = _freeze_public_value(
                child,
                field_path=f"{field_path}.{raw_key}",
            )
        return MappingProxyType(frozen)
    if isinstance(value, Sequence):
        return tuple(
            _freeze_public_value(child, field_path=f"{field_path}[{index}]")
            for index, child in enumerate(value)
        )
    raise TypeError(
        "public trace payload values must be JSON-like scalars, mappings, or "
        f"sequences: {field_path}"
    )


def _thaw_public_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_public_value(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_public_value(child) for child in value]
    return value


def freeze_public_mapping(
    value: Mapping[str, Any],
    *,
    field_path: str,
) -> Mapping[str, Any]:
    """Validate and freeze a public-safe mapping for a Core record."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_path} must be a mapping")
    return _freeze_public_value(dict(value), field_path=field_path)


def require_nonempty_text(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


@dataclass(frozen=True)
class AgentCursor:
    history_index: int
    history_digest: str
    context_digest: str

    def __post_init__(self) -> None:
        if int(self.history_index) < 0:
            raise ValueError("history_index must be non-negative")
        object.__setattr__(self, "history_index", int(self.history_index))
        object.__setattr__(
            self,
            "history_digest",
            require_nonempty_text(self.history_digest, "history_digest"),
        )
        object.__setattr__(
            self,
            "context_digest",
            require_nonempty_text(self.context_digest, "context_digest"),
        )


@dataclass(frozen=True)
class TraceCursor:
    trace_id: str
    branch_id: str
    after_event_id: str | None
    next_sequence: int
    agent_cursor: AgentCursor

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "trace_id", require_nonempty_text(self.trace_id, "trace_id")
        )
        object.__setattr__(
            self, "branch_id", require_nonempty_text(self.branch_id, "branch_id")
        )
        if self.after_event_id is not None:
            object.__setattr__(
                self,
                "after_event_id",
                require_nonempty_text(self.after_event_id, "after_event_id"),
            )
        if int(self.next_sequence) < 0:
            raise ValueError("next_sequence must be non-negative")
        object.__setattr__(self, "next_sequence", int(self.next_sequence))


@dataclass(frozen=True)
class TraceEvent:
    event_id: str
    trace_id: str
    branch_id: str
    sequence: int
    parent_event_id: str | None
    kind: TraceEventKind
    public_payload: Mapping[str, Any] = field(default_factory=dict)
    action_id: str | None = None
    causation_id: str | None = None
    replay_point_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", require_nonempty_text(self.event_id, "event_id")
        )
        object.__setattr__(
            self, "trace_id", require_nonempty_text(self.trace_id, "trace_id")
        )
        object.__setattr__(
            self, "branch_id", require_nonempty_text(self.branch_id, "branch_id")
        )
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        object.__setattr__(self, "sequence", int(self.sequence))
        object.__setattr__(self, "kind", TraceEventKind(self.kind))
        for field_name in (
            "parent_event_id",
            "action_id",
            "causation_id",
            "replay_point_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self, field_name, require_nonempty_text(value, field_name)
                )
        if not isinstance(self.public_payload, Mapping):
            raise TypeError("public_payload must be a mapping")
        object.__setattr__(
            self,
            "public_payload",
            freeze_public_mapping(self.public_payload, field_path="public_payload"),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "trace_id": self.trace_id,
            "branch_id": self.branch_id,
            "sequence": self.sequence,
            "parent_event_id": self.parent_event_id,
            "kind": self.kind.value,
            "action_id": self.action_id,
            "causation_id": self.causation_id,
            "replay_point_id": self.replay_point_id,
            "public_payload": _thaw_public_value(self.public_payload),
        }


class TraceLog:
    """Thread-safe append-only trace with addressable event boundaries."""

    def __init__(self, trace_id: str, branch_id: str) -> None:
        self.trace_id = require_nonempty_text(trace_id, "trace_id")
        self.branch_id = require_nonempty_text(branch_id, "branch_id")
        self._events: list[TraceEvent] = []
        self._event_ids: set[str] = set()
        self._lock = threading.RLock()

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def event(self, event_id: str) -> TraceEvent:
        event_id = require_nonempty_text(event_id, "event_id")
        with self._lock:
            for event in self._events:
                if event.event_id == event_id:
                    return event
        raise KeyError(f"unknown trace event_id: {event_id}")

    def append(self, event: TraceEvent) -> None:
        with self._lock:
            self._append_unlocked(event)

    def _validate_append_unlocked(self, event: TraceEvent) -> None:
        if event.trace_id != self.trace_id or event.branch_id != self.branch_id:
            raise ValueError("trace event does not belong to this trace branch")
        if event.event_id in self._event_ids:
            raise ValueError(f"trace event_id is duplicated: {event.event_id!r}")
        expected_sequence = len(self._events)
        if event.sequence != expected_sequence:
            raise ValueError(
                f"trace sequence must be contiguous: expected {expected_sequence}, "
                f"got {event.sequence}"
            )
        expected_parent = self._events[-1].event_id if self._events else None
        if event.parent_event_id != expected_parent:
            raise ValueError(
                "trace parent_event_id must name the current branch head: "
                f"expected {expected_parent!r}, got {event.parent_event_id!r}"
            )

    def _append_unlocked(self, event: TraceEvent) -> None:
        self._validate_append_unlocked(event)
        self._events.append(event)
        self._event_ids.add(event.event_id)

    @contextmanager
    def locked_cursor(self, agent_cursor: AgentCursor) -> Iterator[TraceCursor]:
        """Freeze the branch head while a ReplayPoint captures both states."""

        with self._lock:
            yield TraceCursor(
                trace_id=self.trace_id,
                branch_id=self.branch_id,
                after_event_id=self._events[-1].event_id if self._events else None,
                next_sequence=len(self._events),
                agent_cursor=agent_cursor,
            )

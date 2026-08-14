"""Heartbeat as an event source (RFC Phase 5 comprehensive eventing).

Heartbeat is demoted from a control-plane decision owner to a *trigger*: it
only produces observable event facts (``heartbeat_observed``), while the
"should this task run?" decision is owned by :class:`PolicyEngine`.

Design rules (RFC §11.2, §5.3):

* The heartbeat bounded context still *renders* prompts (``builder.py``), but
  the decision to run is delegated to the unified :class:`PolicyEngine`.
* ``record_heartbeat_observation`` writes a public-safe ``heartbeat_observed``
  audit fact only. It never mutates Task / Goal state and never carries raw
  task text, transcripts, or credentials (the rollout event boundary already
  strips those).
* Recording is idempotent per (goal, agent, source, heartbeat tick) via a
  deterministic observation fingerprint, so repeated polling does not grow the
  event log without bound.
* Everything here is opt-in behind ``LOOPX_HEARTBEAT_EVENT_SOURCE`` (or an
  explicit ``use_event_source`` flag); the default path is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ...rollout_event_log import (
    append_rollout_event_once,
    build_rollout_event,
    rollout_event_log_path,
)
from ..new_architecture import master_switch_enabled
from ..runtime.time import now_utc_iso

HEARTBEAT_EVENT_SOURCE_ENV = "LOOPX_HEARTBEAT_EVENT_SOURCE"

HEARTBEAT_OBSERVED_EVENT_KIND = "heartbeat_observed"
HEARTBEAT_EVENT_SCHEMA_VERSION = "loopx_heartbeat_observation_v0"

DEFAULT_HEARTBEAT_SOURCE = "heartbeat_poll"


def heartbeat_event_source_enabled(use_event_source: bool | None = None) -> bool:
    """Enable the heartbeat event source.

    An explicit ``use_event_source`` wins; otherwise the dedicated env var wins;
    otherwise the new-architecture master switch decides (on by default).
    """
    if use_event_source is not None:
        return bool(use_event_source)
    value = os.environ.get(HEARTBEAT_EVENT_SOURCE_ENV, "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return master_switch_enabled()


def compute_observation_fingerprint(
    *,
    goal_id: str,
    agent_id: str | None,
    source: str,
    tick_id: str | None = None,
) -> str:
    """Deterministic identity for one heartbeat observation occurrence.

    The fingerprint covers the stable observation identity, deliberately
    excluding timestamps and free-form detail so an unchanged poll collapses
    to a single ``heartbeat_observed`` event.
    """
    stable: dict[str, Any] = {
        "goal_id": str(goal_id or "").strip(),
        "agent_id": str(agent_id or "").strip(),
        "source": str(source or "").strip(),
        "tick_id": str(tick_id or "").strip(),
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_heartbeat_observation_event(
    *,
    goal_id: str,
    agent_id: str | None = None,
    source: str = DEFAULT_HEARTBEAT_SOURCE,
    tick_id: str | None = None,
    status: str | None = None,
    details: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build one public-safe ``heartbeat_observed`` rollout event fact.

    This is a fact-only payload: it records *that* a heartbeat observation
    occurred and which trigger produced it. It carries no business decision
    and no sensitive content. The decision belongs to ``PolicyEngine``.
    """
    event = build_rollout_event(
        goal_id=goal_id,
        event_kind=HEARTBEAT_OBSERVED_EVENT_KIND,
        agent_id=agent_id,
        classification=str(source or DEFAULT_HEARTBEAT_SOURCE),
        status=status,
        summary="heartbeat observation fact",
        details={
            "schema_version": HEARTBEAT_EVENT_SCHEMA_VERSION,
            "source": str(source or DEFAULT_HEARTBEAT_SOURCE),
            "tick_id": str(tick_id or "").strip() if tick_id else None,
            **(details or {}),
        },
        recorded_at=recorded_at or now_utc_iso(),
    )
    event["heartbeat_fingerprint"] = compute_observation_fingerprint(
        goal_id=goal_id,
        agent_id=agent_id,
        source=source,
        tick_id=tick_id,
    )
    return event


def record_heartbeat_observation(
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str | None = None,
    event_log_path: Path | None = None,
    source: str = DEFAULT_HEARTBEAT_SOURCE,
    tick_id: str | None = None,
    status: str | None = None,
    details: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
    use_event_source: bool | None = None,
) -> dict[str, Any]:
    """Record one ``heartbeat_observed`` event fact (idempotent per observation).

    Returns a summary with the appended event and whether it was new. When the
    opt-in flag is off, returns a ``disabled`` marker and writes nothing.
    """
    if not heartbeat_event_source_enabled(use_event_source):
        return {
            "ok": True,
            "disabled": True,
            "reason": f"{HEARTBEAT_EVENT_SOURCE_ENV} not enabled",
            "goal_id": str(goal_id or "").strip(),
        }
    log_path = (
        Path(event_log_path)
        if event_log_path is not None
        else rollout_event_log_path(runtime_root, goal_id)
    )
    event = build_heartbeat_observation_event(
        goal_id=goal_id,
        agent_id=agent_id,
        source=source,
        tick_id=tick_id,
        status=status,
        details=details,
        recorded_at=recorded_at,
    )
    appended, is_new = append_rollout_event_once(
        log_path,
        event,
        identity_fields=(
            "goal_id",
            "heartbeat_fingerprint",
        ),
    )
    return {
        "ok": True,
        "goal_id": str(goal_id or "").strip(),
        "event": appended,
        "new": is_new,
    }


class HeartbeatEventSource:
    """Degrade heartbeat into a fact-only event source.

    ``observe()`` writes the ``heartbeat_observed`` fact. Decision evaluation is
    *not* performed here; callers pass the fact to :class:`PolicyEngine`
    (or use ``merge_event_driven_control_plane``) when eventing is enabled.
    """

    def __init__(
        self,
        *,
        runtime_root: Path,
        goal_id: str,
        agent_id: str | None = None,
        event_log_path: Path | None = None,
        source: str = DEFAULT_HEARTBEAT_SOURCE,
    ) -> None:
        self._runtime_root = Path(runtime_root)
        self._goal_id = str(goal_id or "").strip()
        self._agent_id = agent_id
        self._event_log_path = (
            Path(event_log_path)
            if event_log_path is not None
            else rollout_event_log_path(self._runtime_root, self._goal_id)
        )
        self._source = source

    @property
    def goal_id(self) -> str:
        return self._goal_id

    def observe(
        self,
        *,
        tick_id: str | None = None,
        status: str | None = None,
        details: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
        use_event_source: bool | None = None,
    ) -> dict[str, Any]:
        """Record one heartbeat observation event fact."""
        return record_heartbeat_observation(
            runtime_root=self._runtime_root,
            goal_id=self._goal_id,
            agent_id=self._agent_id,
            event_log_path=self._event_log_path,
            source=self._source,
            tick_id=tick_id,
            status=status,
            details=details,
            recorded_at=recorded_at,
            use_event_source=use_event_source,
        )


__all__ = [
    "HEARTBEAT_EVENT_SOURCE_ENV",
    "HEARTBEAT_OBSERVED_EVENT_KIND",
    "HEARTBEAT_EVENT_SCHEMA_VERSION",
    "DEFAULT_HEARTBEAT_SOURCE",
    "heartbeat_event_source_enabled",
    "compute_observation_fingerprint",
    "build_heartbeat_observation_event",
    "record_heartbeat_observation",
    "HeartbeatEventSource",
]

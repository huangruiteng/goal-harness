"""Opt-in policy decision recording.

RFC C2 (Policy Decision Events): decisions must be auditable through persisted
events without turning the Policy Engine into a persistence layer.

Design rules:

* ``PolicyEngine`` itself stays free of persistence side effects. Callers that
  want auditability wrap ``decide()`` with ``record_policy_decision()``.
* Recording is opt-in (default off).
* Events are written through the existing public-safe ``rollout_event_log``
  append-only idempotent writer (``event_kind="policy_decision"``), so no new
  storage system is introduced.
* Deduplication (RFC §8.4): repeated identical decisions must not create
  unbounded event growth. Two mechanisms are supported:
  ``transition_only=True`` records only outcome/source transitions, while
  ``transition_only=False`` relies on deterministic decision fingerprints
  written into the event payload.
* Sensitive task contents and credentials are never persisted (the rollout
  event boundary already strips them).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...rollout_event_log import (
    DEFAULT_ROLLOUT_EVENT_LOG_NAME,
    append_rollout_event_once,
    build_rollout_event,
)
from ..runtime.time import now_utc_iso
from .decision import Decision

POLICY_DECISION_EVENT_KIND = "policy_decision"

#: Identity fields used for idempotent appends. ``decision_fingerprint`` is
#: deterministic for the same (goal, todo, agent, outcome, reason, source).
_DECISION_IDENTITY_FIELDS: tuple[str, ...] = (
    "goal_id",
    "todo_id",
    "agent_id",
    "decision_fingerprint",
)

_DEFAULT_STATE_DIR_NAME = "policy-decision-state"


def compute_decision_fingerprint(
    decision: Decision,
    *,
    goal_id: str,
    todo_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
) -> str:
    """Deterministic fingerprint over the stable decision identity.

    The fingerprint intentionally excludes timestamps and free-form detail so
    that repeated polling of an unchanged state collapses to a single event.
    """
    stable: dict[str, Any] = {
        "goal_id": str(goal_id or "").strip(),
        "todo_id": str(todo_id or "").strip(),
        "agent_id": str(agent_id or "").strip(),
        "run_id": str(run_id or "").strip(),
        "outcome": decision.outcome,
        "reason": decision.reason,
        "source": decision.source,
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


class PolicyDecisionRecorder:
    """Wraps a rollout event log with transition-only deduplication state.

    ``transition_only=True`` (default) persists a compact state file recording
    the last seen fingerprint per (goal, todo, agent). A repeated identical
    decision is suppressed; a new decision (outcome/reason/source change) is
    recorded. This implements RFC §8.4 transition-only recording.
    """

    def __init__(
        self,
        *,
        log_path: Path | None = None,
        state_dir: Path | None = None,
        transition_only: bool = True,
    ) -> None:
        if log_path is None:
            log_path = Path(".") / DEFAULT_ROLLOUT_EVENT_LOG_NAME
        if state_dir is None:
            state_dir = Path(".") / _DEFAULT_STATE_DIR_NAME
        self._log_path = Path(log_path)
        self._state_dir = Path(state_dir)
        self._transition_only = bool(transition_only)
        self._state_path = self._state_dir / "transition-state.json"
        self._cache: dict[str, str] | None = None

    # -- public API ---------------------------------------------------------

    @property
    def log_path(self) -> Path:
        return self._log_path

    @property
    def transition_only(self) -> bool:
        return self._transition_only

    def record(
        self,
        decision: Decision,
        *,
        goal_id: str,
        todo_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        extra_details: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Record one decision; returns (event, was_new).

        When ``transition_only`` is enabled, a decision identical to the last
        recorded one for the same (goal, todo, agent) is suppressed.
        """
        fingerprint = compute_decision_fingerprint(
            decision,
            goal_id=goal_id,
            todo_id=todo_id,
            agent_id=agent_id,
            run_id=run_id,
        )
        if self._transition_only and self._is_repeat(goal_id, todo_id, agent_id, fingerprint):
            return {}, False

        event = build_rollout_event(
            goal_id=goal_id,
            event_kind=POLICY_DECISION_EVENT_KIND,
            agent_id=agent_id,
            todo_id=todo_id,
            run_id=run_id,
            status=decision.outcome,
            classification=decision.reason,
            summary=f"policy decision: {decision.source}:{decision.reason}",
            details={
                "decision_outcome": decision.outcome,
                "decision_reason": decision.reason,
                "decision_source": decision.source,
                "decision_fingerprint_detail": fingerprint,
                **(extra_details or {}),
            },
            recorded_at=recorded_at or now_utc_iso(),
        )
        # The fingerprint is not part of build_rollout_event's schema; attach it
        # as a stable top-level field for idempotency identity matching.
        event["decision_fingerprint"] = fingerprint
        # Identity fields must be non-empty in the payload; include only the
        # identifiers actually supplied so optional goal/todo/agent all work.
        identity_fields = [
            field
            for field in _DECISION_IDENTITY_FIELDS
            if field in ("goal_id", "decision_fingerprint") or event.get(field)
        ]
        appended, was_new = append_rollout_event_once(
            self._log_path,
            event,
            identity_fields=identity_fields,
        )
        if was_new:
            self._remember(goal_id, todo_id, agent_id, fingerprint)
        return appended, was_new

    def replay_identity(self, event: Mapping[str, Any]) -> tuple[str, str, str, str]:
        """Return the stable identity of a recorded decision event."""
        return (
            str(event.get("goal_id") or ""),
            str(event.get("todo_id") or ""),
            str(event.get("agent_id") or ""),
            str(event.get("decision_fingerprint") or ""),
        )

    # -- transition state helpers ------------------------------------------

    def _state(self) -> dict[str, str]:
        if self._cache is None:
            try:
                self._cache = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def _state_key(self, goal_id: str, todo_id: str | None, agent_id: str | None) -> str:
        return "|".join(
            [
                str(goal_id or "").strip(),
                str(todo_id or "").strip(),
                str(agent_id or "").strip(),
            ]
        )

    def _is_repeat(self, goal_id: str, todo_id: str | None, agent_id: str | None, fingerprint: str) -> bool:
        if not self._transition_only:
            return False
        return self._state().get(self._state_key(goal_id, todo_id, agent_id)) == fingerprint

    def _remember(self, goal_id: str, todo_id: str | None, agent_id: str | None, fingerprint: str) -> None:
        if not self._transition_only:
            return
        state = self._state()
        state[self._state_key(goal_id, todo_id, agent_id)] = fingerprint
        self._state_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self._state_path)


def record_policy_decision(
    decision: Decision,
    *,
    goal_id: str,
    todo_id: str | None = None,
    agent_id: str | None = None,
    run_id: str | None = None,
    log_path: Path | None = None,
    state_dir: Path | None = None,
    transition_only: bool = True,
    extra_details: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """One-shot convenience wrapper around :class:`PolicyDecisionRecorder`."""
    recorder = PolicyDecisionRecorder(
        log_path=log_path,
        state_dir=state_dir,
        transition_only=transition_only,
    )
    return recorder.record(
        decision,
        goal_id=goal_id,
        todo_id=todo_id,
        agent_id=agent_id,
        run_id=run_id,
        extra_details=extra_details,
        recorded_at=recorded_at,
    )


def policy_decision_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Read projection: filter a rollout event list down to policy decisions."""
    return [
        dict(event)
        for event in events
        if str(event.get("event_kind") or "") == POLICY_DECISION_EVENT_KIND
    ]

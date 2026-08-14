"""Goal Closure Evaluator + Controller (event-driven, decoupled from Todo).

Implements the elegant goal-closure design: **Todo lifecycle and Goal lifecycle
are separate**. A Todo only answers "did this piece of work get done?"; a Goal
answers "should this goal keep running?". The Closure Evaluator derives whether
a goal is closable purely from current state — it does NOT require every todo to
carry an explicit ``no_followup`` intent.

Closure is a *derived, deterministic event*, not something the agent has to
"figure out". The flow:

    Todo/Event state change
        -> State Reducer
        -> Scheduler (advance_ready_todo_ids)
        -> Closure Evaluator: is_goal_closable(state)?
              - ready_todo_ids empty?
              - pending_dependencies empty?
              - replan_required False?
              - external_followup_required False?
              -> YES -> emit goal_closure_ready(reason, evidence)
                          -> Goal Controller -> goal_closed
                            (kind=derived | explicit)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ...rollout_event_log import append_rollout_event_once, build_rollout_event

GOAL_CLOSURE_EVALUATION_SCHEMA_VERSION = "goal_closure_evaluation_v0"
GOAL_CLOSURE_STATE_SCHEMA_VERSION = "goal_closure_state_v0"

# Wait/close classification (the RUN/WAIT/CLOSE tri-state for a goal).
GOAL_RUN = "RUN"
GOAL_WAIT = "WAIT"
GOAL_CLOSE = "CLOSE"


def _empty(value: Any) -> bool:
    return value is None or value == [] or value == {} or value == set()


def _zero(value: Any) -> bool:
    try:
        return int(value or 0) <= 0
    except (TypeError, ValueError):
        return True


def goal_closure_reason(state: Mapping[str, Any]) -> str | None:
    """Return the reason a goal is not closable, or None when it is closable.

    ``state`` is a compact goal-state read model with the fields:
      ready_todo_ids           (sequence)
      pending_dependency_ids   (sequence)  - blocked / waiting-for-user deps
      replan_required          (bool)
      external_followup_required (bool)
      open_todo_count          (int)       - optional fallback for open work
      claimed_advancement_count (int)      - optional fallback
    """
    if not isinstance(state, dict):
        return "state_missing"
    if state.get("ready_todo_ids"):
        return "ready_work_remaining"
    if state.get("pending_dependency_ids"):
        return "pending_dependencies"
    if state.get("blocked_todo_ids"):
        return "blocked_work_pending"
    if state.get("deferred_todo_ids"):
        return "deferred_work_pending"
    if state.get("replan_required") is True:
        return "replan_required"
    if state.get("external_followup_required") is True:
        return "external_followup_required"
    # Goal Acceptance: the goal must be *actually realized* with sufficient
    # evidence before it can close. Unsatisfied acceptance criteria block close.
    acceptance = state.get("acceptance")
    if isinstance(acceptance, dict):
        from .goal_acceptance import acceptance_blocker

        blocker = acceptance_blocker(acceptance)
        if blocker is not None:
            return blocker
    # Fallbacks when only counts are supplied. (ready_todo_ids is already known
    # to be empty here — it is checked first above — so only the count fallbacks
    # remain meaningful.)
    if not _zero(state.get("open_todo_count")):
        return "open_work_remaining"
    if not _zero(state.get("claimed_advancement_count")):
        return "claimed_advancement_in_flight"
    return None


def is_goal_closable(state: Mapping[str, Any]) -> bool:
    """The elegant single rule: a goal is closable iff there is no work left.

    ``not ready_todos and not pending_dependencies and not replan_required
    and not external_followup_required`` — with no per-todo ``no_followup``
    requirement.
    """
    return goal_closure_reason(state) is None


def classify_goal_continuation(state: Mapping[str, Any]) -> str:
    """Return the RUN/WAIT/CLOSE tri-state for a goal.

    * RUN   — there is ready, executable work.
    * WAIT  — there is future (blocked / deferred / waiting) work, not closable.
    * CLOSE — no executable work, no pending deps, no replan, no follow-up.
    """
    if not isinstance(state, dict):
        return GOAL_WAIT
    if state.get("ready_todo_ids"):
        return GOAL_RUN
    reason = goal_closure_reason(state)
    if reason is None:
        return GOAL_CLOSE
    return GOAL_WAIT


def evaluate_goal_closure(state: Mapping[str, Any]) -> dict[str, Any]:
    """Run the Closure Evaluator and return a structured evaluation.

    Returns ``{ready: bool, tri_state, reason, evidence}``. ``ready=True`` means
    the goal should be closed now (no further agent action required to close it).
    """
    reason = goal_closure_reason(state)
    ready = reason is None
    return {
        "schema_version": GOAL_CLOSURE_EVALUATION_SCHEMA_VERSION,
        "ready": ready,
        "tri_state": GOAL_CLOSE if ready else classify_goal_continuation(state),
        "reason": reason or "no_followup_work",
        "evidence": {
            "ready_todo_ids": list(state.get("ready_todo_ids") or []),
            "blocked_todo_ids": list(state.get("blocked_todo_ids") or []),
            "deferred_todo_ids": list(state.get("deferred_todo_ids") or []),
            "pending_dependency_ids": list(state.get("pending_dependency_ids") or []),
            "replan_required": state.get("replan_required") is True,
            "external_followup_required": state.get("external_followup_required") is True,
            "acceptance_satisfied": bool(
                (state.get("acceptance") or {}).get("satisfied")
            ),
            "acceptance_gap_count": len(
                (state.get("acceptance") or {}).get("acceptance_gaps") or []
            ),
        },
    }


def build_goal_closure_state(
    *,
    ready_todo_ids: Sequence[str] = (),
    pending_dependency_ids: Sequence[str] = (),
    blocked_todo_ids: Sequence[str] = (),
    deferred_todo_ids: Sequence[str] = (),
    replan_required: bool = False,
    external_followup_required: bool = False,
    open_todo_count: int | None = None,
    claimed_advancement_count: int | None = None,
    acceptance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact goal-state read model for the Closure Evaluator.

    ``acceptance`` is the output of :func:`evaluate_goal_acceptance`; when its
    criteria are unsatisfied, the goal is blocked from closing (WAIT / pending).
    """
    return {
        "schema_version": GOAL_CLOSURE_STATE_SCHEMA_VERSION,
        "ready_todo_ids": list(ready_todo_ids or []),
        "blocked_todo_ids": list(blocked_todo_ids or []),
        "deferred_todo_ids": list(deferred_todo_ids or []),
        "pending_dependency_ids": list(pending_dependency_ids or []),
        "replan_required": bool(replan_required),
        "external_followup_required": bool(external_followup_required),
        "open_todo_count": open_todo_count,
        "claimed_advancement_count": claimed_advancement_count,
        "acceptance": dict(acceptance) if acceptance is not None else None,
    }


def emit_goal_closure_ready(
    *,
    log_path: Path,
    goal_id: str,
    reason: str,
    evidence: Mapping[str, Any] | None = None,
    agent_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Emit a ``goal_closure_ready`` audit event (idempotent by goal+kind).

    This is the single point where the system declares "there is no next step";
    it is derived from state, not from an agent calling a tool.
    """
    event = build_rollout_event(
        goal_id=goal_id,
        event_kind="goal_closure_ready",
        agent_id=agent_id,
        recorded_at=recorded_at,
    )
    event["reason"] = reason
    if evidence:
        event["evidence"] = dict(evidence)
    appended, _is_new = append_rollout_event_once(
        Path(log_path),
        event,
        identity_fields=("goal_id", "event_kind"),
    )
    return appended


def emit_goal_closed(
    *,
    log_path: Path,
    goal_id: str,
    kind: str = "derived",
    reason: str = "no_followup_work",
    agent_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Emit a ``goal_closed`` audit event and return it (Goal Controller action).

    ``kind`` distinguishes a system-derived close (``derived``) from an explicit
    user/agent requested close (``explicit``).
    """
    event = build_rollout_event(
        goal_id=goal_id,
        event_kind="goal_closed",
        agent_id=agent_id,
        recorded_at=recorded_at,
    )
    event["kind"] = "derived" if kind == "derived" else "explicit"
    event["reason"] = reason
    appended, _is_new = append_rollout_event_once(
        Path(log_path),
        event,
        identity_fields=("goal_id", "event_kind"),
    )
    return appended


def maybe_close_goal(
    *,
    log_path: Path,
    goal_id: str,
    state: Mapping[str, Any],
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Run the Closure Evaluator and, when ready, emit closure_ready + goal_closed.

    This is the complete, atomic "Goal Controller" step for the event-driven
    path: it evaluates closure and, if closable, records both the readiness event
    and the closed event. Returns the evaluation (``ready`` tells whether it
    closed).

    When the goal-state carries an **unsatisfied acceptance evaluation**, the
    goal is NOT closed; instead a ``goal_acceptance_pending`` event is emitted so
    the evidence gaps must be resolved before the goal can finish.
    """
    evaluation = evaluate_goal_closure(state)
    if not evaluation["ready"]:
        # Surface a goal_acceptance_pending event when evidence is insufficient,
        # so the operator/agent knows the goal is held for verification.
        acceptance = state.get("acceptance") if isinstance(state, dict) else None
        if isinstance(acceptance, dict) and acceptance.get("satisfied") is not True:
            gaps = acceptance.get("acceptance_gaps") or []
            if gaps:
                from .goal_acceptance import emit_goal_acceptance_pending

                emit_goal_acceptance_pending(
                    log_path=log_path,
                    goal_id=goal_id,
                    acceptance_gaps=gaps,
                    agent_id=agent_id,
                )
        return evaluation
    emit_goal_closure_ready(
        log_path=log_path,
        goal_id=goal_id,
        reason=evaluation["reason"],
        evidence=evaluation["evidence"],
        agent_id=agent_id,
    )
    emit_goal_closed(
        log_path=log_path,
        goal_id=goal_id,
        kind="derived",
        reason=evaluation["reason"],
        agent_id=agent_id,
    )
    evaluation["closed"] = True
    evaluation["closed_at"] = None  # timestamp set by the caller via recorded_at
    return evaluation


__all__ = [
    "GOAL_CLOSURE_EVALUATION_SCHEMA_VERSION",
    "GOAL_CLOSURE_STATE_SCHEMA_VERSION",
    "GOAL_RUN",
    "GOAL_WAIT",
    "GOAL_CLOSE",
    "goal_closure_reason",
    "is_goal_closable",
    "classify_goal_continuation",
    "evaluate_goal_closure",
    "build_goal_closure_state",
    "emit_goal_closure_ready",
    "emit_goal_closed",
    "maybe_close_goal",
]

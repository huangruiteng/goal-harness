"""Opt-in merge of event-driven scheduling with the heartbeat polling path.

RFC Phase 5 comprehensive eventing: the heartbeat polling path and the
event-driven dispatch path are formally merged behind an explicit opt-in flag.
When enabled, one heartbeat tick:

    1. records a ``heartbeat_observed`` event fact (heartbeat = event source);
    2. computes the unified decision through :class:`PolicyEngine`;
    3. advances READY successors and enqueues them (event-driven dispatch);
    4. lets a worker acquire the next task (Worker Pool).

When the opt-in flag is off, the legacy heartbeat polling path is untouched and
no event facts, queue writes, or claims happen here.

This merge is *composition*, not a rewrite: it delegates to the existing
``policy/engine``, ``heartbeat/event_source``, and
``scheduler/event_driven_dispatch`` modules.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ...event_sourced_state import AppendOnlyStateEventStore, build_state_projection
from ...rollout_event_log import load_rollout_events, rollout_event_log_path
from ..heartbeat.event_source import (
    HEARTBEAT_OBSERVED_EVENT_KIND,
    heartbeat_event_source_enabled,
    record_heartbeat_observation,
)
from ..new_architecture import master_switch_enabled
from ..policy import PolicyEngine
from ..policy.decision_events import record_policy_decision
from ..runtime.time import now_utc_iso
from .event_driven_dispatch import (
    EVENT_DRIVEN_DISPATCH_ENV,
    build_event_driven_dispatch,
    event_driven_dispatch_enabled,
    load_task_queue,
    task_queue_path,
)

MERGE_PATH_ENV = "LOOPX_MERGE_EVENT_DRIVEN_AND_HEARTBEAT"

MERGE_SCHEMA_VERSION = "loopx_event_driven_heartbeat_merge_v0"

DecisionFactory = Callable[..., Any]


def merge_enabled(
    *,
    use_event_driven: bool | None = None,
    use_event_source: bool | None = None,
    use_merge: bool | None = None,
) -> bool:
    """The merge is on when eventing, event-source, and merge flags allow it.

    An explicit ``use_merge`` wins; otherwise the dedicated env var wins;
    otherwise the new-architecture master switch decides (on by default).
    """
    if use_merge is not None:
        return bool(use_merge)
    value = os.environ.get(MERGE_PATH_ENV, "").strip().lower()
    if value:
        if value not in {"1", "true", "yes", "on"}:
            return False
    elif not master_switch_enabled():
        return False
    return (
        event_driven_dispatch_enabled(use_event_driven)
        and heartbeat_event_source_enabled(use_event_source)
    )


def load_todo_items_from_rollout_log(
    runtime_root: Path,
    goal_id: str,
    event_log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Build todo items from ``todo_add`` / ``todo_complete`` rollout events.

    Real goals record task mutations in the rollout event log (``todo_add`` /
    ``todo_complete``) rather than a separate ``events.jsonl`` state store. This
    reconstructs the latest status per todo_id so the event-driven dispatch can
    recompute readiness for real goal data.

    Only public-safe fields are used (todo_id, status, role); raw task text is
    intentionally not reconstructed here.
    """
    resolved_goal = str(goal_id or "").strip()
    log_path = (
        Path(event_log_path)
        if event_log_path is not None
        else rollout_event_log_path(runtime_root, resolved_goal)
    )
    statuses: dict[str, str] = {}
    roles: dict[str, str] = {}
    unblocks: dict[str, str] = {}
    excluded: dict[str, list[str]] = {}
    task_classes: dict[str, str] = {}
    try:
        events = load_rollout_events(log_path)
    except OSError:
        return []
    for event in events:
        kind = event.get("event_kind")
        if kind not in {"todo_add", "todo_complete"}:
            continue
        todo_id = str(event.get("todo_id") or "").strip()
        if not todo_id:
            continue
        # A todo_complete event is authoritative: the todo has reached a
        # terminal state and must never be recomputed as READY again. Real
        # goal logs replay every todo_add/todo_complete in order, so the
        # *last* event for a todo_id wins; when the last event is
        # todo_complete we normalize the status to the canonical terminal
        # value. This prevents already-done todos (including stale
        # cross-goal zombies like `todo_change_font`) from being re-admitted
        # to the Task Queue by advance_ready_todo_ids — the drift seen in
        # the website1 color session where goal-closure reported ready=6.
        if kind == "todo_complete":
            statuses[todo_id] = "done"
            continue
        # todo_add wins only when not already finalized by a completion.
        statuses.setdefault(todo_id, str(event.get("status") or "open"))
        details = event.get("details") or {}
        if not isinstance(details, dict):
            details = {}
        role = str(details.get("role")) if details.get("role") else "agent"
        roles.setdefault(todo_id, role)
        dep = details.get("unblocks_todo_id")
        if not dep:
            causality = event.get("causality") or {}
            dep_list = causality.get("unblocks") if isinstance(causality, dict) else None
            if isinstance(dep_list, list) and dep_list:
                dep = str(dep_list[0])
        if dep:
            unblocks[todo_id] = str(dep)
        excl = details.get("excluded_agents")
        if isinstance(excl, list):
            excluded[todo_id] = [str(a) for a in excl]
        elif isinstance(excl, str) and excl:
            # Accept both "a,b" and stringified repr lists like "['agent_worker']".
            cleaned = excl.strip()
            if cleaned.startswith("[") and cleaned.endswith("]"):
                cleaned = cleaned[1:-1].replace("'", "").replace('"', "")
            excluded[todo_id] = [a.strip() for a in cleaned.split(",") if a.strip()]
        tc = details.get("task_class")
        if tc:
            task_classes[todo_id] = str(tc)
    items = [
        {
            "todo_id": todo_id,
            "status": status,
            "role": roles.get(todo_id, "agent"),
            "task_class": task_classes.get(todo_id, "advancement_task"),
            "unblocks_todo_id": unblocks.get(todo_id),
            "excluded_agents": excluded.get(todo_id, []),
        }
        for todo_id, status in statuses.items()
    ]
    return items


def _loaded_items(
    runtime_root: Path,
    goal_id: str,
) -> tuple[list[dict[str, Any]], Path]:
    """Load projected user+agent todo items and the rollout event log path.

    Prefers the dedicated ``events.jsonl`` state store; falls back to the
    ``todo_add`` / ``todo_complete`` rollout events when the store is absent
    (the common shape for real goals).
    """
    log_path = rollout_event_log_path(runtime_root, goal_id)
    state_log_path = runtime_root / "goals" / str(goal_id) / "events.jsonl"
    state_events = AppendOnlyStateEventStore(state_log_path).load()
    projection = build_state_projection(state_events, goal_id=goal_id)
    items = [
        *projection.get("user_todos", {}).get("items", []),
        *projection.get("agent_todos", {}).get("items", []),
    ]
    if not items:
        items = load_todo_items_from_rollout_log(runtime_root, goal_id, log_path)
    return items, log_path


def merge_event_driven_and_heartbeat(
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str | None = None,
    completed_todo_id: str | None = None,
    worker_id: str | None = None,
    status_payload: Mapping[str, Any] | None = None,
    items: Sequence[Mapping[str, Any]] | None = None,
    event_log_path: Path | None = None,
    recorded_at: str | None = None,
    tick_id: str | None = None,
    use_event_driven: bool | None = None,
    use_event_source: bool | None = None,
    use_merge: bool | None = None,
    record_policy_decisions: bool | None = None,
) -> dict[str, Any]:
    """Run the merged heartbeat + event-driven path behind the opt-in flag.

    Returns a merged payload with four sections:

    * ``heartbeat`` — the recorded ``heartbeat_observed`` event fact;
    * ``policy_decision`` — the unified :class:`PolicyEngine` decision;
    * ``event_driven_dispatch`` — READY advancement, enqueue, worker claim;
    * ``queue`` — the resulting task queue view.

    When the merge (or any required sub-flag) is off, returns a ``disabled``
    marker and writes nothing.
    """
    resolved_goal_id = str(goal_id or "").strip()
    stamp = recorded_at or now_utc_iso()
    log_path = (
        Path(event_log_path)
        if event_log_path is not None
        else rollout_event_log_path(runtime_root, resolved_goal_id)
    )
    enabled = merge_enabled(
        use_event_driven=use_event_driven,
        use_event_source=use_event_source,
        use_merge=use_merge,
    )
    if not enabled:
        return {
            "ok": True,
            "disabled": True,
            "reason": f"{MERGE_PATH_ENV} not enabled (eventing + event-source + merge all required)",
            "goal_id": resolved_goal_id,
        }

    # 1. Heartbeat = event source: record the observation fact.
    heartbeat = record_heartbeat_observation(
        runtime_root=runtime_root,
        goal_id=resolved_goal_id,
        agent_id=agent_id,
        event_log_path=log_path,
        source="heartbeat_poll",
        tick_id=tick_id,
        status=str((status_payload or {}).get("decision") or None)
        if status_payload
        else None,
        details={
            "cause": "merged_event_driven_and_heartbeat",
            "completed_todo_id": completed_todo_id,
        },
        recorded_at=stamp,
        use_event_source=use_event_source,
    )

    # 2. Decision through the unified PolicyEngine.
    #    Forward scheduler_execution_context (if present in the status payload)
    #    so the policy composition can validate the scheduler context instead of
    #    short-circuiting with "missing required field".
    decision: Any = None
    if status_payload is not None:
        engine = PolicyEngine()
        supplied = dict(status_payload)
        scheduler_ctx = supplied.get("scheduler_execution_context")
        if scheduler_ctx is None and "scheduler_execution_context" in supplied:
            scheduler_ctx = supplied["scheduler_execution_context"]
        decision = engine.decide(
            status_payload=supplied,
            goal_id=resolved_goal_id,
            agent_id=agent_id,
            scheduler_execution_context=scheduler_ctx,
        )
        if record_policy_decisions is None:
            value = os.environ.get("LOOPX_POLICY_DECISION_RECORD", "").strip().lower()
            record_policy_decisions = (
                value in {"1", "true", "yes", "on"} if value else master_switch_enabled()
            )
        if record_policy_decisions:
            record_policy_decision(
                decision,
                goal_id=resolved_goal_id,
                agent_id=agent_id,
                log_path=log_path,
                state_dir=runtime_root / "goals" / resolved_goal_id / "policy-decision-state",
                transition_only=True,
            )

    # 3. Event-driven dispatch advancement.
    if items is None:
        projected_items, _ = _loaded_items(runtime_root, resolved_goal_id)
    else:
        projected_items = [dict(item) for item in items]
    dispatch = build_event_driven_dispatch(
        runtime_root=runtime_root,
        goal_id=resolved_goal_id,
        items=projected_items,
        completed_todo_id=completed_todo_id,
        event_log_path=log_path,
        worker_id=worker_id,
        recorded_at=stamp,
        use_event_driven=use_event_driven,
    )

    queue = load_task_queue(task_queue_path(runtime_root, goal_id=resolved_goal_id))

    return {
        "ok": True,
        "schema_version": MERGE_SCHEMA_VERSION,
        "goal_id": resolved_goal_id,
        "agent_id": agent_id,
        "enabled": True,
        "heartbeat": heartbeat,
        "policy_decision": decision.to_dict() if decision is not None else None,
        "event_driven_dispatch": dispatch.get("event_driven_dispatch"),
        "recorded_events": dispatch.get("recorded_events"),
        "queue": queue,
    }


__all__ = [
    "MERGE_PATH_ENV",
    "MERGE_SCHEMA_VERSION",
    "merge_enabled",
    "merge_event_driven_and_heartbeat",
]

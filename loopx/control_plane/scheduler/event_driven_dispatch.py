"""RFC Phase 6 - Event-Driven Scheduling Pilot (narrow path).

Wires the event-driven narrow path behind an explicit opt-in flag:

    TaskCompleted -> dependency satisfied -> TaskReady -> Queue -> Worker

Everything in this module is opt-in (``LOOPX_EVENT_DRIVEN_DISPATCH=1`` or an
explicit ``use_event_driven=True``).  When disabled every function returns a
``disabled`` marker and no state is written, preserving the legacy heartbeat
behavior (RFC 11.2: heartbeat demoted to a trigger; default unchanged).

Design constraints (RFC 11.4):
- The rollout event log is *not* an execution event bus.  It records public
  audit facts (``task_ready`` / ``task_enqueued`` / ``task_dispatched``) only.
- Readiness is recomputed from the projected todo items via
  ``handoff_ready_successor_todo_ids`` (handoff gates), never replayed from
  rollout events.
- The task queue is a separate append-only JSONL store next to the goal state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ...rollout_event_log import (
    ROLLOUT_EVENT_SCHEMA_VERSION,
    append_rollout_event_once,
    build_rollout_event,
    load_rollout_events,
)
from ..new_architecture import master_switch_enabled
from ..todos.contract import (
    TODO_STATUS_BLOCKED,
    TODO_STATUS_DEFERRED,
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_ADVANCEMENT,
    TODO_TERMINAL_STATUS_VALUES,
    normalize_todo_excluded_agents,
    normalize_todo_id,
    normalize_todo_status,
    normalize_todo_task_class,
)
from ..todos.handoff_gate import (
    handoff_ready_successor_todo_ids,
    todo_summary_handoff_gates,
)

EVENT_DRIVEN_DISPATCH_ENV = "LOOPX_EVENT_DRIVEN_DISPATCH"

TASK_READY_EVENT_KIND = "task_ready"
TASK_ENQUEUED_EVENT_KIND = "task_enqueued"
TASK_DISPATCHED_EVENT_KIND = "task_dispatched"

TASK_QUEUE_SCHEMA_VERSION = "loopx_scheduler_task_queue_v0"
TASK_QUEUE_ENTRY_SCHEMA_VERSION = "loopx_scheduler_task_queue_entry_v0"

QUEUE_STATUS_PENDING = "pending"
QUEUE_STATUS_CLAIMED = "claimed"
QUEUE_STATUS_DONE = "done"
QUEUE_STATUSES = {
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_DONE,
}

DEFAULT_TASK_QUEUE_NAME = "scheduler-task-queue.jsonl"


def event_driven_dispatch_enabled(use_event_driven: bool | None = None) -> bool:
    """Enable event-driven dispatch.

    An explicit ``use_event_driven`` wins; otherwise the dedicated env var wins;
    otherwise the new-architecture master switch decides (on by default).
    """
    if use_event_driven is not None:
        return bool(use_event_driven)
    value = os.environ.get(EVENT_DRIVEN_DISPATCH_ENV, "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return master_switch_enabled()


def _safe_segment(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("goal_id is required")
    safe = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "_"})
    if not safe:
        raise ValueError(f"goal_id must be alphanumeric: {text!r}")
    return safe


def task_queue_path(runtime_root: Path, *, goal_id: str) -> Path:
    """Path to the append-only task queue JSONL for a goal."""
    return (
        Path(runtime_root).expanduser()
        / "goals"
        / _safe_segment(goal_id)
        / DEFAULT_TASK_QUEUE_NAME
    )


def _queue_view(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pending = [e for e in entries if e.get("status") == QUEUE_STATUS_PENDING]
    claimed = [e for e in entries if e.get("status") == QUEUE_STATUS_CLAIMED]
    done = [e for e in entries if e.get("status") == QUEUE_STATUS_DONE]
    return {
        "schema_version": TASK_QUEUE_SCHEMA_VERSION,
        "entry_count": len(entries),
        "pending_count": len(pending),
        "claimed_count": len(claimed),
        "done_count": len(done),
        "pending_todo_ids": [e.get("todo_id") for e in pending],
        "claimed_todo_ids": [e.get("todo_id") for e in claimed],
    }


def load_task_queue(path: Path) -> dict[str, Any]:
    """Load the task queue snapshot (empty view when the file does not exist)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return _queue_view([])
    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema_version") == TASK_QUEUE_ENTRY_SCHEMA_VERSION:
            entries.append(parsed)
    return _queue_view(entries)


def _enqueued_todo_ids(entries: Iterable[Mapping[str, Any]]) -> set[str]:
    return {
        str(entry.get("todo_id") or "").strip()
        for entry in entries
        if str(entry.get("todo_id") or "").strip()
    }


def _queued_todo_ids(path: Path) -> set[str]:
    view = load_task_queue(path)
    return set(view.get("pending_todo_ids", [])) | set(view.get("claimed_todo_ids", []))


def enqueue_tasks(
    path: Path,
    *,
    goal_id: str,
    todo_ids: Sequence[str],
    recorded_at: str,
    source: str = "event_driven_dispatch",
    use_event_driven: bool | None = None,
) -> dict[str, Any]:
    """Append new pending queue entries, idempotent per todo_id.

    Returns a summary with newly enqueued todo ids and skipped duplicates.
    """
    if not event_driven_dispatch_enabled(use_event_driven):
        return {
            "ok": True,
            "disabled": True,
            "reason": f"{EVENT_DRIVEN_DISPATCH_ENV} not enabled",
        }
    goal = _safe_segment(goal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    try:
        existing = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        existing = []
    existing = [e for e in existing if isinstance(e, dict) and e.get("schema_version") == TASK_QUEUE_ENTRY_SCHEMA_VERSION]
    known = _enqueued_todo_ids(existing)

    newly: list[str] = []
    skipped: list[str] = []
    with path.open("a", encoding="utf-8") as handle:
        for todo_id in todo_ids:
            normalized = str(todo_id or "").strip()
            if not normalized:
                continue
            if normalized in known:
                skipped.append(normalized)
                continue
            entry: dict[str, Any] = {
                "schema_version": TASK_QUEUE_ENTRY_SCHEMA_VERSION,
                "goal_id": goal,
                "todo_id": normalized,
                "status": QUEUE_STATUS_PENDING,
                "enqueued_at": recorded_at,
                "enqueued_by": source,
            }
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
            known.add(normalized)
            newly.append(normalized)
    return {
        "ok": True,
        "goal_id": goal,
        "newly_enqueued": newly,
        "skipped_duplicates": skipped,
    }


def claim_next_task(
    path: Path,
    *,
    worker_id: str,
    use_event_driven: bool | None = None,
    capabilities: Sequence[str] | None = None,
    lease_seconds: int | float | None = None,
) -> dict[str, Any] | None:
    """Claim the oldest pending task for a worker (Worker Pool acquire).

    Mutates the queue in place: rewrites the JSONL with the claimed status.
    Returns the claimed entry, or None when the queue is empty.

    ``capabilities`` (optional) enables capability matching: only tasks whose
    ``required_capabilities`` are all present in the worker's capability set are
    claimable. Tasks carrying a legacy ``capability_binding_ref`` additionally
    require the worker to declare the bound pack token, and the pack must be
    ``ready`` in the capability registry (fail closed) — this mirrors the
    legacy capability-pack eligibility contract. ``lease_seconds`` (optional)
    attaches a ``lease_until`` expiry so a crashed worker's task can be
    reclaimed (zombie recovery). Both are opt-in and leave the default FIFO
    claim behavior unchanged when omitted.
    """
    if not event_driven_dispatch_enabled(use_event_driven):
        return None
    if not path.exists():
        return None
    if capabilities is not None or lease_seconds is not None:
        from .task_lifecycle import claim_next_eligible_task
        from ...capabilities.catalog import build_capability_registry

        claimed = claim_next_eligible_task(
            path,
            worker_id=worker_id,
            capabilities=capabilities,
            lease_seconds=lease_seconds,
            registry=build_capability_registry(),
        )
        return claimed
    lines = path.read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema_version") == TASK_QUEUE_ENTRY_SCHEMA_VERSION:
            entries.append(parsed)
    claimed: dict[str, Any] | None = None
    for entry in entries:
        if entry.get("status") == QUEUE_STATUS_PENDING:
            entry["status"] = QUEUE_STATUS_CLAIMED
            entry["claimed_by"] = str(worker_id).strip()
            # Always attach a lease (default TTL) so the task is never mistaken
            # for a legacy un-leased zombie by is_expired/reconcile. A claimed
            # task without lease_until would be reclaimed on the very next
            # reconcile tick, causing a claim->reclaim->claim livelock.
            from .task_lifecycle import lease_expiry

            entry["lease_until"] = lease_expiry(lease_seconds)
            claimed = entry
            break
    if claimed is None:
        return None
    path.write_text(
        "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )
    return claimed


def record_task_event(
    event_log_path: Path,
    *,
    goal_id: str,
    event_kind: str,
    todo_id: str,
    agent_id: str | None = None,
    source_event_id: str | None = None,
    details: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
    use_event_driven: bool | None = None,
) -> dict[str, Any]:
    """Record one public audit event, idempotent by (event_kind, todo_id)."""
    if not event_driven_dispatch_enabled(use_event_driven):
        return {
            "ok": True,
            "disabled": True,
            "reason": f"{EVENT_DRIVEN_DISPATCH_ENV} not enabled",
        }
    event = build_rollout_event(
        goal_id=goal_id,
        event_kind=event_kind,
        agent_id=agent_id,
        todo_id=todo_id,
        source_event_id=source_event_id,
        details=details,
        recorded_at=recorded_at,
    )
    appended, is_new = append_rollout_event_once(
        Path(event_log_path),
        event,
        identity_fields=("goal_id", "event_kind", "todo_id"),
    )
    return {
        "ok": True,
        "event": appended,
        "new": is_new,
    }


def _outstanding_acceptance_pending(
    event_log_path: Path | None,
) -> list[dict[str, Any]]:
    """Return the unresolved acceptance gaps recorded for a goal, if any.

    A ``goal_acceptance_pending`` fact means the goal previously declared
    acceptance criteria that are still unsatisfied. A later criteria-less
    dispatch tick (e.g. heartbeat-driven) must treat those gaps as still open
    and hold the goal in WAIT rather than closing it and silently dropping the
    acceptance gate. The pending fact is only cleared once a subsequent
    ``goal_acceptance_satisfied`` or ``goal_closed`` fact is recorded.
    """
    if event_log_path is None:
        return []
    events = load_rollout_events(event_log_path)
    pending: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = event.get("event_kind")
        if kind == "goal_acceptance_pending":
            gaps = event.get("acceptance_gaps") or []
            if not isinstance(gaps, list):
                gaps = []
            for gap in gaps:
                if isinstance(gap, dict) and gap.get("criterion_id"):
                    pending[str(gap["criterion_id"])] = gap
        elif kind in ("goal_acceptance_satisfied", "goal_closed"):
            # A satisfied/closed fact clears any prior pending gate.
            pending.clear()
    return list(pending.values())


def build_event_driven_dispatch(
    *,
    runtime_root: Path,
    goal_id: str,
    items: Sequence[Mapping[str, Any]],
    completed_todo_id: str | None = None,
    event_log_path: Path | None = None,
    worker_id: str | None = None,
    agent_id: str | None = None,
    recorded_at: str | None = None,
    use_event_driven: bool | None = None,
    reconcile: bool = False,
    worker_capabilities: Sequence[str] | None = None,
    lease_seconds: int | float | None = None,
    acceptance_criteria: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    acceptance_base_dir: Path | None = None,
) -> dict[str, Any]:
    """Advance READY successors, enqueue them, and (optionally) claim for a worker.

    Narrow RFC Phase 6 path:

        TaskCompleted -> dependency satisfied -> TaskReady -> Queue -> Worker

    Steps:
    0. Optional reconciliation (``reconcile=True``): expire stale leases (zombie
       recovery) and promote ready retries, per ``plan/new_plan.md`` P0.
    1. Recompute READY successors from handoff gates (pure function).
    2. Record a ``task_ready`` rollout audit event per successor (idempotent).
    3. Append each successor to the task queue (idempotent).
    4. Optionally claim the next task for a worker (Worker Pool acquire).

    ``worker_id`` names the claimer (written to the queue entry's ``claimed_by``);
    ``agent_id`` names the registered LoopX agent identity recorded on the
    ``task_dispatched`` audit event. When ``agent_id`` is omitted it falls back
    to ``worker_id`` so existing callers keep recording the claimer identity.

    ``worker_capabilities`` and ``lease_seconds`` (optional) are forwarded to
    :func:`claim_next_task` for capability-matched, lease-bound claiming.

    When the opt-in flag is off, returns a ``disabled`` marker and writes nothing.
    """
    from ..runtime.time import now_utc_iso

    if not event_driven_dispatch_enabled(use_event_driven):
        return {
            "ok": True,
            "disabled": True,
            "reason": f"{EVENT_DRIVEN_DISPATCH_ENV} not enabled",
            "goal_id": goal_id,
        }
    stamp = recorded_at or now_utc_iso()
    queue_path = task_queue_path(runtime_root, goal_id=goal_id)

    # 0a. Materialize the completed todo as a terminal fact. The ``--completed-todo-id``
    # flag carries the semantics "this todo is DONE, advance from here", but the
    # legacy path only wrote it into task_ready audit details and never marked the
    # todo complete — so the todo stayed open, readiness kept recomputing it as
    # READY, and closure reported ``ready_work_remaining`` forever. Record a
    # ``todo_complete`` rollout fact so ``load_todo_items_from_rollout_log`` (and
    # the closure evaluator) see the terminal status on this and future ticks.
    if completed_todo_id and event_log_path is not None:
        record_task_event(
            event_log_path,
            goal_id=goal_id,
            event_kind="todo_complete",
            todo_id=completed_todo_id,
            source_event_id=None,
            details={"cause": "event_driven_dispatch_completed_todo_id"},
            recorded_at=stamp,
            use_event_driven=use_event_driven,
        )
    # Reflect the completion on the in-memory item set for THIS tick as well, so
    # readiness and closure evaluate against the terminal state immediately
    # (rather than only on the next tick after the rollout log is replayed).
    if completed_todo_id:
        normalized_completed = normalize_todo_id(completed_todo_id)
        items = [
            dict(item, status="done")
            if isinstance(item, dict)
            and normalize_todo_id(item.get("todo_id")) == normalized_completed
            else item
            for item in items
        ]

    # 0. Optional reconciliation: expire zombie leases and promote ready retries.
    reconcile_result: dict[str, Any] | None = None
    if reconcile:
        from .task_lifecycle import reconcile_queue

        reconcile_result = reconcile_queue(
            queue_path,
            worker_id=worker_id,
            recorded_at=stamp,
        )

    # 1. READY successors (pure; reuses handoff gate readiness).
    ready_successors = advance_ready_todo_ids(items)
    enqueued = _queued_todo_ids(queue_path)
    ready_successors = [todo_id for todo_id in ready_successors if todo_id not in enqueued]

    # 2. Record task_ready audit events.
    ready_events: list[dict[str, Any]] = []
    if event_log_path is not None:
        for todo_id in ready_successors:
            recorded = record_task_event(
                event_log_path,
                goal_id=goal_id,
                event_kind=TASK_READY_EVENT_KIND,
                todo_id=todo_id,
                source_event_id=None,
                details={
                    "completed_todo_id": completed_todo_id,
                    "cause": "handoff_gate_cleared",
                },
                recorded_at=stamp,
                use_event_driven=use_event_driven,
            )
            if not recorded.get("disabled"):
                ready_events.append(recorded["event"])

    # 3. Enqueue.
    enqueued_result = enqueue_tasks(
        queue_path,
        goal_id=goal_id,
        todo_ids=ready_successors,
        recorded_at=stamp,
        use_event_driven=use_event_driven,
    )
    enqueued_events: list[dict[str, Any]] = []
    if event_log_path is not None:
        for todo_id in enqueued_result.get("newly_enqueued", []):
            recorded = record_task_event(
                event_log_path,
                goal_id=goal_id,
                event_kind=TASK_ENQUEUED_EVENT_KIND,
                todo_id=todo_id,
                source_event_id=None,
                details={"queue_position": None},
                recorded_at=stamp,
                use_event_driven=use_event_driven,
            )
            if not recorded.get("disabled"):
                enqueued_events.append(recorded["event"])

    # 4. Worker acquire (optional).
    dispatched: dict[str, Any] | None = None
    if worker_id:
        claimed = claim_next_task(
            queue_path,
            worker_id=worker_id,
            use_event_driven=use_event_driven,
            capabilities=worker_capabilities,
            lease_seconds=lease_seconds,
        )
        if claimed is not None:
            if event_log_path is not None:
                # Prefer the registered LoopX agent identity; fall back to the
                # claimer (worker_id) so legacy callers stay unchanged.
                dispatch_agent_id = (agent_id or "").strip() or worker_id
                record_task_event(
                    event_log_path,
                    goal_id=goal_id,
                    event_kind=TASK_DISPATCHED_EVENT_KIND,
                    todo_id=str(claimed.get("todo_id") or ""),
                    agent_id=dispatch_agent_id,
                    source_event_id=None,
                    details={"status": claimed.get("status")},
                    recorded_at=stamp,
                    use_event_driven=use_event_driven,
                )
            dispatched = {
                "todo_id": claimed.get("todo_id"),
                "claimed_by": claimed.get("claimed_by"),
                "status": claimed.get("status"),
            }

    # 5. Closure evaluation (event-driven, derived): when no ready successors
    # remain and the queue holds no pending/claimed work, the Closure Evaluator
    # decides whether the goal is done. This decouples Goal closure from Todo
    # lifecycle: we do NOT require every todo to carry an explicit no_followup
    # intent — empty ready + empty queue + no replan is enough to emit
    # goal_closure_ready (plan/new_plan.md elegant-close design).
    closure: dict[str, Any] | None = None
    if event_log_path is not None and not ready_successors:
        from ..goals.goal_closure import (
            build_goal_closure_state,
            evaluate_goal_closure,
            maybe_close_goal,
        )
        from ..goals.goal_acceptance import evaluate_goal_acceptance

        queue_view = load_task_queue(queue_path)
        # Derive remaining (non-terminal) work directly from the projected items,
        # NOT hardcoded empty lists. ``advance_ready_todo_ids`` only reports OPEN
        # advancement todos as READY; ``blocked`` / ``deferred`` todos are NOT
        # "ready" but ARE still unfinished work that must block goal closure.
        # Without this, a goal with a blocked (or deferred) todo would be wrongly
        # ``goal_closed`` the moment no *ready* successors remain — e.g. another
        # todo submitted mid-run that is blocked on a dependency, or deferred work
        # that has not been scheduled yet.
        blocked_todo_ids: list[str] = []
        deferred_todo_ids: list[str] = []
        # Remaining *executable advancement* work. Reuse the same readiness rules
        # as ``advance_ready_todo_ids`` (unfiltered by queue membership) so that
        # non-advancement todos — continuous_monitor, user_gate, user_action,
        # blocker — that are still "open" do NOT falsely block goal closure.
        # These todos live on their own lifecycles (background monitor, user
        # action) and are never claimed by the advancement worker pool; counting
        # them as "ready work" would wedge the goal in RUN forever.
        open_todo_ids: list[str] = [
            tid for tid in advance_ready_todo_ids(items)
        ]
        for item in items:
            if not isinstance(item, dict):
                continue
            tid = normalize_todo_id(item.get("todo_id"))
            if not tid:
                continue
            status = normalize_todo_status(item.get("status"))
            if status == TODO_STATUS_BLOCKED:
                blocked_todo_ids.append(tid)
            elif status == TODO_STATUS_DEFERRED:
                deferred_todo_ids.append(tid)
        # Run the Goal Acceptance / Evidence Verification layer up-front. When
        # acceptance criteria + evidence are supplied, the closure state carries
        # them so the Closure Evaluator can distinguish RUN (more work) from WAIT
        # (evidence gaps) from CLOSE (done + verified). This is what lets a single
        # dispatch call drive the full acceptance -> goal_closed loop instead of
        # forcing the agent to hand-run goal-closure --verify --apply (the
        # long refresh-state retry loop seen in the website1 color session).
        acceptance_eval = None
        if acceptance_criteria is not None or evidence is not None:
            acceptance_eval = evaluate_goal_acceptance(
                acceptance_criteria=acceptance_criteria,
                evidence=evidence,
                base_dir=acceptance_base_dir,
            )
        else:
            # No criteria/evidence on this tick. Do NOT silently skip acceptance:
            # if a prior dispatch already recorded a ``goal_acceptance_pending``
            # fact (acceptance criteria were declared earlier and remain
            # unsatisfied), a criteria-less dispatch (e.g. a heartbeat-driven
            # tick) must NOT close the goal and erase the outstanding acceptance
            # gate. Synthesize an unsatisfied acceptance evaluation so the
            # Closure Evaluator holds the goal in WAIT until evidence arrives.
            pending = _outstanding_acceptance_pending(event_log_path)
            if pending:
                acceptance_eval = {
                    "satisfied": False,
                    "acceptance_gaps": pending,
                    "criteria_results": pending,
                    "evidence_count": 0,
                    "verified_count": 0,
                    "criteria_count": len(pending),
                }
        closure_state = build_goal_closure_state(
            ready_todo_ids=open_todo_ids,
            pending_dependency_ids=[],
            blocked_todo_ids=blocked_todo_ids,
            deferred_todo_ids=deferred_todo_ids,
            replan_required=False,
            external_followup_required=False,
            open_todo_count=max(queue_view.get("pending_count", 0), len(open_todo_ids)),
            claimed_advancement_count=queue_view.get("claimed_count", 0),
            acceptance=acceptance_eval,
        )
        closure = evaluate_goal_closure(closure_state)
        if closure["ready"]:
            # Atomic close: emits goal_closure_ready AND goal_closed, including
            # the acceptance-satisfied check. No separate manual step required.
            maybe_close_goal(
                log_path=event_log_path,
                goal_id=goal_id,
                state=closure_state,
                agent_id=agent_id,
            )

    return {
        "ok": True,
        "goal_id": _safe_segment(goal_id),
        "event_driven_dispatch": {
            "enabled": True,
            "ready_successors": ready_successors,
            "newly_enqueued": enqueued_result.get("newly_enqueued", []),
            "skipped_duplicates": enqueued_result.get("skipped_duplicates", []),
            "dispatched": dispatched,
            "reconcile": reconcile_result,
            "closure": closure,
            "queue": load_task_queue(queue_path),
        },
        "recorded_events": {
            "task_ready": ready_events,
            "task_enqueued": enqueued_events,
        },
    }


def _has_excluded_agents(item: Mapping[str, Any]) -> bool:
    """True when the item declares excluded_agents (i.e. it is a handoff gate)."""
    return bool(normalize_todo_excluded_agents(item.get("excluded_agents")))


def advance_ready_todo_ids(
    items: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return the READY todo ids for the given projected items.

    Pure function: recomputes handoff gate readiness from the current item set.

    A todo is READY when it is:
    1. A CLEARED_WITH_SUCCESSOR gate's successor (handoff gate chain); or
    2. An unconstrained open advancement todo that is not gated by any handoff
       gate successor edge and not yet done. This covers the common "initial
       READY todos" shape (RFC Phase 5/6), where an independent agent task has
       no handoff gate dependency and must still enter the Task Queue so a
       resident Worker can claim it.

    Callers filter against already-enqueued ids for idempotency.
    """
    item_list = list(items)
    ready: set[str] = set()

    # Authoritative terminal statuses (done/deferred/closed/...). A todo in a
    # terminal state must NEVER be (re)enqueued or claimed, even when a handoff
    # gate still lists it as a successor. Without this filter, stale successors
    # left over from a previous (font) task are re-enqueued and claimed by the
    # event-driven scheduler even though the markdown active state already
    # considers them done — exactly the drift seen in the website1 color session.
    terminal_todo_ids: set[str] = set()
    for item in item_list:
        if not isinstance(item, dict):
            continue
        normalized = normalize_todo_id(item.get("todo_id"))
        if not normalized:
            continue
        status = str(item.get("status") or "").strip()
        if status in TODO_TERMINAL_STATUS_VALUES or (
            status and status not in {TODO_STATUS_OPEN, "blocked", "in_progress", "active", "pending"}
        ):
            terminal_todo_ids.add(normalized)

    # 1. Handoff gate successors (existing semantics), excluding terminal todos.
    for todo_id in handoff_ready_successor_todo_ids({"items": item_list}):
        normalized = str(todo_id or "").strip()
        if normalized and normalized not in terminal_todo_ids:
            ready.add(normalized)

    # 2. Unconstrained open advancement todos not referenced by any handoff gate.
    # An item is "gated" when some gate either directly unblocks it
    # (gate.unblocks_todo_id) or lists it as a successor edge.
    gated_todo_ids: set[str] = set()
    for gate in todo_summary_handoff_gates({"items": item_list}):
        if not isinstance(gate, dict):
            continue
        direct = normalize_todo_id(gate.get("unblocks_todo_id"))
        if direct:
            gated_todo_ids.add(direct)
        successor_ids = gate.get("successor_todo_ids")
        if isinstance(successor_ids, list):
            for todo_id in successor_ids:
                normalized = normalize_todo_id(todo_id)
                if normalized:
                    gated_todo_ids.add(normalized)
    for item in item_list:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip() != TODO_STATUS_OPEN:
            continue
        todo_id = normalize_todo_id(item.get("todo_id"))
        if not todo_id or todo_id in ready:
            continue
        if normalize_todo_task_class(
            item.get("task_class"),
            text=str(item.get("text") or "").strip(),
            action_kind=item.get("action_kind"),
        ) != TODO_TASK_CLASS_ADVANCEMENT:
            continue
        # Skip handoff gates themselves (excluded_agents) — gate readiness is
        # driven by the gate state machine, not the free-advancement rule.
        if _has_excluded_agents(item):
            continue
        # Skip items that are successors of any gate (gate drives their readiness).
        if todo_id in gated_todo_ids:
            continue
        # Skip items whose readiness is delegated to a "resume_when" / supersede edge.
        if normalize_todo_id(item.get("superseded_by")):
            continue
        ready.add(todo_id)

    return sorted(ready)


__all__ = [
    "EVENT_DRIVEN_DISPATCH_ENV",
    "TASK_READY_EVENT_KIND",
    "TASK_ENQUEUED_EVENT_KIND",
    "TASK_DISPATCHED_EVENT_KIND",
    "TASK_QUEUE_SCHEMA_VERSION",
    "TASK_QUEUE_ENTRY_SCHEMA_VERSION",
    "QUEUE_STATUS_PENDING",
    "QUEUE_STATUS_CLAIMED",
    "QUEUE_STATUS_DONE",
    "QUEUE_STATUSES",
    "DEFAULT_TASK_QUEUE_NAME",
    "event_driven_dispatch_enabled",
    "task_queue_path",
    "load_task_queue",
    "enqueue_tasks",
    "claim_next_task",
    "record_task_event",
    "build_event_driven_dispatch",
    "advance_ready_todo_ids",
]

"""Scheduler converged into a resident Task Queue + Worker Pool (RFC Phase 5).

The Scheduler no longer owns business decisions: it is a resident process that
only answers *timing* and *which task may execute now*. The pipeline is:

    Trigger -> Scheduler -> Policy -> Queue -> Worker -> Agent -> Events

This module provides the resident execution machinery:

* :class:`WorkerPool` — a bounded set of workers that acquire the next pending
  task from the append-only JSONL queue via ``claim_next_task``.
* :class:`ResidentScheduler` — a resident loop that recomputes READY successors
  from handoff gates, enqueues them, and hands them to idle workers.
* ``run_resident_scheduler_loop`` / ``run_resident_scheduler_bounded`` — loop
  drivers (the latter bounded for tests and one-shot cron use).

Design constraints (RFC §11.4):

* The rollout event log is *not* an execution bus; it records public audit
  facts only (``task_ready`` / ``task_enqueued`` / ``task_dispatched``).
* Readiness is recomputed from the projected todo items, never replayed.
* The task queue is a separate append-only JSONL store next to goal state.
* Everything is opt-in behind ``LOOPX_EVENT_DRIVEN_DISPATCH`` (reused) or an
  explicit ``use_event_driven=True``; the legacy heartbeat path is unchanged.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ...rollout_event_log import rollout_event_log_path
from ..runtime.time import now_utc_iso
from .event_driven_dispatch import (
    EVENT_DRIVEN_DISPATCH_ENV,
    QUEUE_STATUS_PENDING,
    TASK_DISPATCHED_EVENT_KIND,
    build_event_driven_dispatch,
    claim_next_task,
    event_driven_dispatch_enabled,
    task_queue_path,
)

RESIDENT_SCHEDULER_SCHEMA_VERSION = "loopx_resident_scheduler_v0"


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def load_todo_items_from_rollout_log(
    runtime_root: Path,
    goal_id: str,
    event_log_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Build todo items from ``todo_add`` / ``todo_complete`` rollout events.

    Real goals record task mutations in the rollout event log rather than a
    separate ``events.jsonl`` state store. This reconstructs the latest status
    per todo_id so event-driven dispatch can recompute readiness for real goal
    data. Only public-safe fields are used.
    """
    resolved_goal = str(goal_id or "").strip()
    log_path = (
        Path(event_log_path)
        if event_log_path is not None
        else rollout_event_log_path(runtime_root, resolved_goal)
    )
    # Reuse the canonical implementation in ``merge`` to avoid divergent copies.
    # (The duplicate here previously lacked the ``todo_complete -> done``
    # authoritative-normalization, so a completed todo whose event carried a
    # non-"done" status field was silently re-admitted as open.)
    from .merge import load_todo_items_from_rollout_log as _canonical

    return _canonical(runtime_root, goal_id, event_log_path)


def _loaded_items(
    runtime_root: Path,
    goal_id: str,
) -> tuple[list[dict[str, Any]], Path]:
    """Load projected user+agent todo items and the rollout event log path.

    Delegates to the canonical ``merge._loaded_items`` to avoid a divergent
    duplicate (single source of truth for events.jsonl vs rollout-log fallback).
    """
    from .merge import _loaded_items as _canonical

    return _canonical(runtime_root, goal_id)


WorkerTaskRunner = Callable[..., dict[str, Any]]


def _command_matches_worker_prefix(command: str | None, prefixes: Sequence[str]) -> bool:
    """Match a worker command against an allow-list of command prefixes.

    Mirrors the original scheduler executor gate (``_command_matches_allowed_prefix``)
    so the new-architecture worker executes only whitelisted commands.
    """
    if not command or not prefixes:
        return False
    try:
        command_parts = shlex.split(command)
    except ValueError:
        command_parts = []
    first = command_parts[0] if command_parts else command.strip().split(None, 1)[0]
    for prefix in prefixes:
        prefix = str(prefix).strip()
        if not prefix:
            continue
        if first == prefix or first == prefix.split(None, 1)[0]:
            return True
        if command.strip() == prefix or command.strip().startswith(f"{prefix} "):
            return True
    return False


def _run_worker_shell_command(
    command: str,
    *,
    timeout_seconds: float = 60.0,
    capture_output: bool = False,
) -> dict[str, Any]:
    """Run a worker task command (default runner for :data:`WorkerTaskRunner`)."""
    import subprocess as _subprocess

    stdout = _subprocess.PIPE if capture_output else _subprocess.DEVNULL
    stderr = _subprocess.STDOUT if capture_output else _subprocess.DEVNULL
    try:
        completed = _subprocess.run(
            command,
            shell=True,
            timeout=timeout_seconds,
            stdout=stdout,
            stderr=stderr,
        )
        output = ""
        if capture_output:
            output = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "timed_out": False,
            "output_captured": capture_output,
            "output": output,
        }
    except _subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "timed_out": True, "output_captured": capture_output, "output": ""}


def execute_claimed_task(
    claimed_entry: Mapping[str, Any],
    *,
    worker_command: str | None = None,
    worker_command_prefixes: Sequence[str] | None = None,
    guard_checked: bool = False,
    runner: WorkerTaskRunner | None = None,
) -> dict[str, Any]:
    """Optionally execute a claimed task behind explicit opt-in gates.

    Mirrors the original scheduler executor gates (``codex_cli_scheduler``):

    * ``worker_command`` + ``worker_command_prefixes`` must both be set, and the
      command must match an allowed prefix.
    * ``guard_checked`` must be True (fresh quota guard confirmation).
    * The ``runner`` is injectable for tests (default runs the shell command).

    A task is executed only when all gates pass; otherwise the execution is
    skipped with a ``reason`` (never auto-run).
    """
    worker_command_prefixes = list(worker_command_prefixes or [])
    runner = runner or _run_worker_shell_command
    command = str(worker_command).strip() if worker_command else None
    result: dict[str, Any] = {
        "todo_id": str(claimed_entry.get("todo_id") or "").strip(),
        "claimed_by": str(claimed_entry.get("claimed_by") or "").strip(),
        "executed": False,
        "reason": None,
        "output_captured": False,
    }
    if not command:
        result["reason"] = "worker_command_missing"
        return result
    if not guard_checked:
        result["reason"] = "fresh_quota_guard_confirmation_required"
        return result
    if not worker_command_prefixes:
        result["reason"] = "worker_command_prefix_required"
        return result
    if not _command_matches_worker_prefix(command, worker_command_prefixes):
        result["reason"] = "worker_command_prefix_mismatch"
        return result
    run_result = runner(command)
    result.update(
        executed=run_result.get("ok") is True,
        ok=run_result.get("ok") is True,
        reason="executed" if run_result.get("ok") is True else "execution_failed",
        output_captured=run_result.get("output_captured") is True,
        returncode=run_result.get("returncode"),
        timed_out=run_result.get("timed_out") is False or run_result.get("timed_out"),
    )
    return result


def _sync_registry_goal_closed_from_runtime(runtime_root: Path, goal_id: str) -> bool:
    """Best-effort registry sync for a closed goal, given only ``runtime_root``.

    The resident scheduler does not carry the project directory; it learns the
    project repo from the global registry (``<runtime_root>/registry.global.json``)
    and then syncs the project-local ``.loopx/registry.json``. A missing/partial
    registry is a silent no-op.
    """
    try:
        import json

        global_path = Path(runtime_root) / "registry.global.json"
        global_registry = json.loads(global_path.read_text())
    except Exception:
        return False
    repo = None
    for entry in global_registry.get("goals", []) or []:
        if str(entry.get("id") or "") == goal_id:
            repo = entry.get("repo")
            break
    if not repo:
        return False
    try:
        from ...registry import sync_registry_goal_closed

        return sync_registry_goal_closed(Path(repo) / ".loopx" / "registry.json", goal_id)
    except Exception:
        return False


def finalize_resident_execution(
    *,
    runtime_root: Path,
    goal_id: str,
    event_log_path: Path | None,
    executed: Sequence[Mapping[str, Any]],
    worker_id: str | None = None,
    recorded_at: str | None = None,
    acceptance_criteria: Sequence[Mapping[str, Any]] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    acceptance_base_dir: Path | None = None,
) -> dict[str, Any]:
    """Close the resident execution loop (task_completed -> acceptance -> closure).

    This is the missing link that turns a claimed+executed task into a fully
    closed goal lifecycle:

    1. For each executed task, mark it ``done`` (``complete_task``) and emit a
       ``task_completed`` audit event; failed executions emit ``task_failed``.
    2. Run the Goal Acceptance evaluator against the declared criteria/evidence.
    3. Run the Closure Evaluator; if evidence is sufficient and no work remains,
       emit ``goal_closure_ready`` + ``goal_closed``. If acceptance has gaps,
       emit ``goal_acceptance_pending`` (goal stays open).

    Returns a summary with per-task results, the acceptance evaluation, and the
    closure evaluation (``closed`` tells whether the goal was closed).
    """
    from ...rollout_event_log import append_rollout_event_once, build_rollout_event
    from ..goals.goal_acceptance import evaluate_goal_acceptance
    from ..goals.goal_closure import (
        build_goal_closure_state,
        maybe_close_goal,
    )
    from .event_driven_dispatch import load_task_queue, task_queue_path as _tqp
    from .task_lifecycle import complete_task, fail_task

    stamp = recorded_at or now_utc_iso()
    queue_path = _tqp(runtime_root, goal_id=goal_id)
    log_path = Path(event_log_path) if event_log_path is not None else rollout_event_log_path(
        runtime_root, goal_id
    )

    task_results: list[dict[str, Any]] = []
    for entry in executed:
        todo_id = str(entry.get("todo_id") or "").strip()
        executed_ok = entry.get("executed") is True or entry.get("ok") is True
        if not todo_id:
            continue
        if executed_ok:
            completed = complete_task(
                queue_path,
                task_id=todo_id,
                worker_id=worker_id or str(entry.get("claimed_by") or "").strip(),
                recorded_at=stamp,
            )
            event = build_rollout_event(
                goal_id=goal_id,
                event_kind="task_completed",
                agent_id=worker_id,
                recorded_at=stamp,
            )
            event["todo_id"] = todo_id
            append_rollout_event_once(
                log_path, event, identity_fields=("goal_id", "event_kind", "todo_id")
            )
            task_results.append(
                {"todo_id": todo_id, "executed": True, "completed": completed is not None}
            )
        else:
            fail_task(
                queue_path,
                task_id=todo_id,
                worker_id=worker_id or str(entry.get("claimed_by") or "").strip(),
                error=str(entry.get("reason") or "execution_failed"),
                transient=False,
                recorded_at=stamp,
            )
            event = build_rollout_event(
                goal_id=goal_id,
                event_kind="task_failed",
                agent_id=worker_id,
                recorded_at=stamp,
            )
            event["todo_id"] = todo_id
            append_rollout_event_once(
                log_path, event, identity_fields=("goal_id", "event_kind", "todo_id")
            )
            task_results.append({"todo_id": todo_id, "executed": False, "completed": False})

    # Acceptance evaluation (evidence verification before closure).
    acceptance = evaluate_goal_acceptance(
        acceptance_criteria=acceptance_criteria,
        evidence=evidence,
        base_dir=acceptance_base_dir,
    )

    # Closure evaluation: acceptance + no-work -> close.
    queue_view = load_task_queue(queue_path)
    state = build_goal_closure_state(
        ready_todo_ids=list(queue_view.get("pending_todo_ids", [])),
        open_todo_count=queue_view.get("pending_count", 0),
        claimed_advancement_count=queue_view.get("claimed_count", 0),
        acceptance=acceptance,
    )
    closure = maybe_close_goal(log_path=log_path, goal_id=goal_id, state=state)

    # When closure derived (goal_closed emitted), keep the registry goal entry's
    # status in lockstep with the rollout log so `status`/registry and
    # start-goal's guided packet agree the goal is closed. The resident loop only
    # knows ``runtime_root``, so resolve the project registry via the global
    # registry's ``repo`` field (best-effort; a missing/partial registry is a
    # silent no-op).
    if closure.get("closed") is True:
        try:
            from ...registry import sync_registry_goal_closed

            _sync_registry_goal_closed_from_runtime(runtime_root, goal_id)
        except Exception:
            pass

    return {
        "ok": True,
        "goal_id": goal_id,
        "task_results": task_results,
        "acceptance": acceptance,
        "closure": closure,
        "closed": closure.get("closed") is True,
        "queue": queue_view,
    }


class WorkerPool:
    """A bounded set of workers claiming tasks from the scheduler queue.

    ``acquire()`` claims the oldest pending task for a worker (Worker Pool
    acquire via ``claim_next_task``), rewriting the queue in place. When the
    queue is empty it returns ``None``. Claiming is opt-in behind the shared
    event-driven flag.
    """

    def __init__(
        self,
        *,
        worker_ids: Sequence[str] = (),
        runtime_root: Path,
        goal_id: str,
        use_event_driven: bool | None = None,
        capabilities_map: Mapping[str, Sequence[str]] | None = None,
        lease_seconds: int | float | None = None,
    ) -> None:
        self._worker_ids = [str(w).strip() for w in worker_ids if str(w).strip()]
        self._runtime_root = Path(runtime_root)
        self._goal_id = str(goal_id or "").strip()
        self._use_event_driven = use_event_driven
        self._capabilities_map = {
            str(worker): [str(c) for c in caps]
            for worker, caps in (capabilities_map or {}).items()
        }
        self._lease_seconds = lease_seconds
        self._acquired: list[dict[str, Any]] = []

    @property
    def worker_ids(self) -> list[str]:
        return list(self._worker_ids)

    @property
    def acquired(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._acquired]

    @property
    def idle_worker_count(self) -> int:
        claimed = {str(e.get("claimed_by") or "") for e in self._acquired}
        return len([w for w in self._worker_ids if w not in claimed])

    def worker_capabilities(self, worker_id: str) -> list[str] | None:
        """Return the declared capabilities for a worker (None when undeclared)."""
        caps = self._capabilities_map.get(str(worker_id).strip())
        return list(caps) if caps is not None else None

    def acquire(self, worker_id: str) -> dict[str, Any] | None:
        """Claim the next pending task for ``worker_id``, or None when empty.

        When capabilities are declared for the worker, only tasks whose required
        capabilities are satisfied are claimable (capability matching, P1). When
        ``lease_seconds`` is set, the claimed entry carries a ``lease_until`` so a
        crashed worker's task can be reclaimed by reconciliation.
        """
        if not event_driven_dispatch_enabled(self._use_event_driven):
            return None
        claimed = claim_next_task(
            task_queue_path(self._runtime_root, goal_id=self._goal_id),
            worker_id=str(worker_id).strip(),
            use_event_driven=self._use_event_driven,
            capabilities=self.worker_capabilities(worker_id),
            lease_seconds=self._lease_seconds,
        )
        if claimed is not None:
            self._acquired.append(dict(claimed))
        return claimed

    def drain(
        self,
        *,
        worker_ids: Sequence[str] | None = None,
        limit: int | None = None,
        capabilities_map: Mapping[str, Sequence[str]] | None = None,
        lease_seconds: int | float | None = None,
    ) -> list[dict[str, Any]]:
        """Claim tasks for each idle worker until the queue is empty or ``limit``.

        ``capabilities_map`` / ``lease_seconds`` (optional) let a caller override
        the pool-level capability and lease settings for a single drain pass.
        """
        caps_map = {
            str(worker): [str(c) for c in caps]
            for worker, caps in (capabilities_map or {}).items()
        } or self._capabilities_map
        lease = lease_seconds if lease_seconds is not None else self._lease_seconds
        pool = [str(w).strip() for w in (worker_ids if worker_ids is not None else self._worker_ids)]
        acquired: list[dict[str, Any]] = []
        claimed = {str(e.get("claimed_by") or "") for e in self._acquired}
        for worker in pool:
            if limit is not None and len(acquired) >= limit:
                break
            if worker in claimed:
                continue
            caps = caps_map.get(worker)
            if not event_driven_dispatch_enabled(self._use_event_driven):
                entry = None
            else:
                entry = claim_next_task(
                    task_queue_path(self._runtime_root, goal_id=self._goal_id),
                    worker_id=str(worker).strip(),
                    use_event_driven=self._use_event_driven,
                    capabilities=caps,
                    lease_seconds=lease,
                )
            if entry is not None:
                self._acquired.append(dict(entry))
                acquired.append(entry)
                claimed.add(worker)
            else:
                # A worker with no eligible task does not stop the drain for the
                # other workers; only stop when the queue is genuinely exhausted.
                if caps is None and self._queue_is_empty():
                    break
        return acquired

    def _queue_is_empty(self) -> bool:
        from .event_driven_dispatch import load_task_queue

        view = load_task_queue(task_queue_path(self._runtime_root, goal_id=self._goal_id))
        return view.get("pending_count", 0) == 0


class ResidentScheduler:
    """A resident scheduler process: Task Queue + Worker Pool, policy-gated.

    One ``tick()`` advances the event-driven narrow path:

        TaskCompleted -> dependency satisfied -> TaskReady -> Queue -> Worker

    The scheduler stays business-agnostic: readiness comes from handoff gates
    (pure projection) and the decision to run is delegated to PolicyEngine by
    the caller via ``build_event_driven_dispatch``. This class only manages
    queue advancement and worker acquisition.
    """

    def __init__(
        self,
        *,
        runtime_root: Path,
        goal_id: str,
        worker_ids: Sequence[str] = (),
        agent_id: str | None = None,
        event_log_path: Path | None = None,
        use_event_driven: bool | None = None,
        reconcile: bool = True,
        worker_capabilities: Mapping[str, Sequence[str]] | None = None,
        lease_seconds: int | float | None = None,
    ) -> None:
        self._runtime_root = Path(runtime_root)
        self._goal_id = str(goal_id or "").strip()
        self._agent_id = str(agent_id or "").strip() or None
        self._event_log_path = (
            Path(event_log_path)
            if event_log_path is not None
            else rollout_event_log_path(self._runtime_root, self._goal_id)
        )
        self._pool = WorkerPool(
            worker_ids=worker_ids,
            runtime_root=self._runtime_root,
            goal_id=self._goal_id,
            use_event_driven=use_event_driven,
        )
        self._use_event_driven = use_event_driven
        self._reconcile = bool(reconcile)
        self._worker_capabilities = {
            str(worker): [str(c) for c in caps]
            for worker, caps in (worker_capabilities or {}).items()
        }
        self._lease_seconds = lease_seconds
        self._tick_count = 0

    @property
    def goal_id(self) -> str:
        return self._goal_id

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def pool(self) -> WorkerPool:
        return self._pool

    def tick(
        self,
        *,
        completed_todo_id: str | None = None,
        recorded_at: str | None = None,
        claim_workers: bool = True,
        worker_exec: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Advance READY successors, enqueue them, and claim for idle workers.

        ``worker_exec`` is an optional per-claimed-task executor hook invoked
        after a worker claims a task (e.g. ``execute_claimed_task``). It runs
        only when supplied; otherwise claimed tasks are not executed (the
        scheduler stays business-agnostic).
        """
        self._tick_count += 1
        stamp = recorded_at or now_utc_iso()
        items, _ = _loaded_items(self._runtime_root, self._goal_id)
        # Claimer capabilities for the primary dispatch worker (if declared).
        claim_worker_caps = None
        primary_worker = self._pool.worker_ids[0] if self._pool.worker_ids else None
        if primary_worker and primary_worker in self._worker_capabilities:
            claim_worker_caps = self._worker_capabilities[primary_worker]
        payload = build_event_driven_dispatch(
            runtime_root=self._runtime_root,
            goal_id=self._goal_id,
            items=items,
            completed_todo_id=completed_todo_id,
            event_log_path=self._event_log_path,
            worker_id=primary_worker,
            agent_id=self._agent_id,
            recorded_at=stamp,
            use_event_driven=self._use_event_driven,
            reconcile=self._reconcile,
            worker_capabilities=claim_worker_caps,
            lease_seconds=self._lease_seconds,
        )
        acquired: list[dict[str, Any]] = []
        if claim_workers:
            acquired = self._pool.drain(capabilities_map=self._worker_capabilities, lease_seconds=self._lease_seconds)
        # Worker execution targets: the task the dispatch claimed this tick
        # (``dispatched``), plus any additional tasks drained by the pool.
        dispatch_summary = payload.get("event_driven_dispatch") or {}
        dispatched = dispatch_summary.get("dispatched")
        exec_targets: list[dict[str, Any]] = []
        if isinstance(dispatched, dict) and dispatched.get("todo_id"):
            exec_targets.append(dispatched)
        exec_target_ids = {str(e.get("todo_id")) for e in exec_targets}
        for entry in acquired:
            if str(entry.get("todo_id")) not in exec_target_ids:
                exec_targets.append(entry)
                exec_target_ids.add(str(entry.get("todo_id")))
        executed: list[dict[str, Any]] = []
        if worker_exec is not None:
            for entry in exec_targets:
                executed.append(worker_exec(entry))
        payload["resident_scheduler"] = {
            "schema_version": RESIDENT_SCHEDULER_SCHEMA_VERSION,
            "goal_id": self._goal_id,
            "tick_count": self._tick_count,
            "reconcile": ((payload.get("event_driven_dispatch") or {}).get("reconcile")),
            "worker_pool": {
                "worker_ids": self._pool.worker_ids,
                "idle_worker_count": self._pool.idle_worker_count,
                "acquired": acquired,
            },
            "worker_executions": executed,
        }
        return payload


def run_resident_scheduler_bounded(
    *,
    runtime_root: Path,
    goal_id: str,
    worker_ids: Sequence[str] = (),
    agent_id: str | None = None,
    max_iterations: int = 1,
    interval_seconds: float = 0.0,
    completed_todo_id: str | None = None,
    use_event_driven: bool | None = None,
    sleep: Callable[[float], None] = time.sleep,
    worker_exec_command: str | None = None,
    worker_exec_command_prefixes: Sequence[str] | None = None,
    guard_checked: bool = False,
    runner: WorkerTaskRunner | None = None,
    reconcile: bool = True,
    worker_capabilities: Mapping[str, Sequence[str]] | None = None,
    lease_seconds: int | float | None = None,
    acceptance_criteria: Sequence[Mapping[str, Any]] | None = None,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    acceptance_base_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the resident scheduler for a bounded number of ticks (test / cron).

    Returns an aggregate summary with per-tick results and a final queue view.

    ``agent_id`` names the registered LoopX agent identity recorded on
    ``task_dispatched`` audit events (falls back to the claimer when omitted).

    Optional worker execution (mirrors the original scheduler executor gates):
    when ``worker_exec_command`` + ``worker_exec_command_prefixes`` are supplied
    and ``guard_checked`` is True, each claimed task is executed after claim via
    :func:`execute_claimed_task`. This is opt-in; without it tasks are only
    claimed, never executed.

    ``reconcile`` (default True) enables lease-expiry (zombie recovery) and
    retry promotion each tick; ``worker_capabilities`` enables capability-matched
    claiming; ``lease_seconds`` bounds how long a claim is held.

    ``acceptance_criteria`` + ``evidence`` (optional) close the full loop: after
    worker execution, tasks are completed, acceptance is verified, and the goal
    is closed (or held pending) via :func:`finalize_resident_execution`. The
    final summary includes ``finalize`` (task_results / acceptance / closure).
    """
    scheduler = ResidentScheduler(
        runtime_root=runtime_root,
        goal_id=goal_id,
        worker_ids=worker_ids,
        agent_id=agent_id,
        use_event_driven=use_event_driven,
        reconcile=reconcile,
        worker_capabilities=worker_capabilities,
        lease_seconds=lease_seconds,
    )
    iterations = max(0, int(max_iterations))

    def _worker_exec(claimed: Mapping[str, Any]) -> dict[str, Any]:
        return execute_claimed_task(
            claimed,
            worker_command=worker_exec_command,
            worker_command_prefixes=worker_exec_command_prefixes,
            guard_checked=guard_checked,
            runner=runner,
        )

    ticks: list[dict[str, Any]] = []
    for _ in range(iterations):
        tick_payload = scheduler.tick(
            completed_todo_id=completed_todo_id,
            worker_exec=_worker_exec if worker_exec_command else None,
        )
        ticks.append(tick_payload)
        if interval_seconds > 0 and _ < iterations - 1:
            sleep(interval_seconds)
    from .event_driven_dispatch import load_task_queue

    # Close the loop: task_completed -> acceptance -> closure (goal_closed).
    finalize: dict[str, Any] | None = None
    if worker_exec_command and (acceptance_criteria is not None or evidence is not None):
        executed_entries: list[dict[str, Any]] = []
        for tick in ticks:
            executed_entries.extend(
                (tick.get("resident_scheduler") or {}).get("worker_executions") or []
            )
        finalize = finalize_resident_execution(
            runtime_root=runtime_root,
            goal_id=goal_id,
            event_log_path=rollout_event_log_path(runtime_root, goal_id),
            executed=executed_entries,
            worker_id=agent_id,
            acceptance_criteria=acceptance_criteria,
            evidence=evidence,
            acceptance_base_dir=acceptance_base_dir,
        )

    return {
        "ok": True,
        "goal_id": goal_id,
        "schema_version": RESIDENT_SCHEDULER_SCHEMA_VERSION,
        "enabled": event_driven_dispatch_enabled(use_event_driven),
        "max_iterations": iterations,
        "tick_count": scheduler.tick_count,
        "worker_exec_command": worker_exec_command,
        "ticks": ticks,
        "queue": load_task_queue(task_queue_path(runtime_root, goal_id=goal_id)),
        "finalize": finalize,
    }


def run_resident_scheduler_loop(
    *,
    runtime_root: Path,
    goal_id: str,
    worker_ids: Sequence[str] = (),
    agent_id: str | None = None,
    interval_seconds: float = 10.0,
    completed_todo_id: str | None = None,
    use_event_driven: bool | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run the resident scheduler as a long-lived polling loop.

    Intended for a launchd / systemd / tmux resident worker. The loop keeps
    running until interrupted (``KeyboardInterrupt``); the interval applies
    between ticks. Use ``run_resident_scheduler_bounded`` for bounded runs.

    ``agent_id`` names the registered LoopX agent identity recorded on
    ``task_dispatched`` audit events (falls back to the claimer when omitted).
    """
    scheduler = ResidentScheduler(
        runtime_root=runtime_root,
        goal_id=goal_id,
        worker_ids=worker_ids,
        agent_id=agent_id,
        use_event_driven=use_event_driven,
    )
    interval = max(0.0, float(interval_seconds))
    started_at = now_utc_iso()
    ticks: list[dict[str, Any]] = []
    try:
        while True:
            tick_payload = scheduler.tick(completed_todo_id=completed_todo_id)
            ticks.append(tick_payload)
            if interval > 0:
                sleep(interval)
    except KeyboardInterrupt:
        pass
    from .event_driven_dispatch import load_task_queue

    return {
        "ok": True,
        "goal_id": goal_id,
        "schema_version": RESIDENT_SCHEDULER_SCHEMA_VERSION,
        "enabled": event_driven_dispatch_enabled(use_event_driven),
        "started_at": started_at,
        "ended_at": now_utc_iso(),
        "tick_count": scheduler.tick_count,
        "tick_summaries": [
            {
                "tick": index + 1,
                "disabled": payload.get("disabled") is True,
                "newly_enqueued": (
                    (payload.get("event_driven_dispatch") or {}).get("newly_enqueued", [])
                    if isinstance(payload.get("event_driven_dispatch"), dict)
                    else []
                ),
            }
            for index, payload in enumerate(ticks)
        ],
        "queue": load_task_queue(task_queue_path(runtime_root, goal_id=goal_id)),
    }


__all__ = [
    "RESIDENT_SCHEDULER_SCHEMA_VERSION",
    "WorkerPool",
    "ResidentScheduler",
    "execute_claimed_task",
    "run_resident_scheduler_bounded",
    "run_resident_scheduler_loop",
]

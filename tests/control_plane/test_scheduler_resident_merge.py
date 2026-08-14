from __future__ import annotations

from pathlib import Path

import pytest

from loopx.control_plane.scheduler.event_driven_dispatch import (
    EVENT_DRIVEN_DISPATCH_ENV,
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_PENDING,
    enqueue_tasks,
    load_task_queue,
    task_queue_path,
)
from loopx.control_plane.scheduler.merge import (
    MERGE_PATH_ENV,
    load_todo_items_from_rollout_log,
    merge_enabled,
    merge_event_driven_and_heartbeat,
)
from loopx.rollout_event_log import (
    build_rollout_event,
    load_rollout_events,
)
from loopx.control_plane.scheduler.resident import (
    ResidentScheduler,
    WorkerPool,
    execute_claimed_task,
    finalize_resident_execution,
    run_resident_scheduler_bounded,
)
from loopx.event_sourced_state import (
    TODO_ADDED,
    TODO_COMPLETED,
    AppendOnlyStateEventStore,
    make_state_event,
)
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path


def _seed_gate_events(tmp_path: Path, goal_id: str) -> None:
    """todo_first done gate unlocks advancement todo_second."""
    store = AppendOnlyStateEventStore(tmp_path / "goals" / goal_id / "events.jsonl")
    store.append(
        make_state_event(
            event_id="evt-gate-add",
            goal_id=goal_id,
            event_type=TODO_ADDED,
            refs={"todo_id": "todo_first"},
            payload={
                "text": "setup done",
                "role": "agent",
                "excluded_agents": ["agent_worker"],
                "unblocks_todo_id": "todo_second",
            },
            recorded_at="2026-08-14T00:00:00Z",
        )
    )
    store.append(
        make_state_event(
            event_id="evt-gate-complete",
            goal_id=goal_id,
            event_type=TODO_COMPLETED,
            refs={"todo_id": "todo_first"},
            payload={"note": "done"},
            recorded_at="2026-08-14T00:00:01Z",
        )
    )
    store.append(
        make_state_event(
            event_id="evt-succ-add",
            goal_id=goal_id,
            event_type=TODO_ADDED,
            refs={"todo_id": "todo_second"},
            payload={
                "text": "followup advancement",
                "role": "agent",
                "task_class": "advancement_task",
                "unblocks_todo_id": "todo_first",
            },
            recorded_at="2026-08-14T00:00:02Z",
        )
    )


def _gate_items() -> list[dict[str, object]]:
    return [
        {
            "todo_id": "todo_first",
            "text": "setup done",
            "status": "done",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_second",
        },
        {
            "todo_id": "todo_second",
            "text": "followup advancement",
            "task_class": "advancement_task",
            "unblocks_todo_id": "todo_first",
            "status": "open",
        },
    ]


# ---------------------------------------------------------------------------
# Worker Pool
# ---------------------------------------------------------------------------


def test_worker_pool_acquires_next_pending_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="pool")
    enqueue_tasks(queue, goal_id="pool", todo_ids=["todo_a", "todo_b"], recorded_at="t")
    pool = WorkerPool(worker_ids=["worker_one", "worker_two"], runtime_root=tmp_path, goal_id="pool")
    claimed = pool.acquire("worker_one")
    assert claimed is not None
    assert claimed["todo_id"] == "todo_a"
    assert claimed["status"] == QUEUE_STATUS_CLAIMED
    assert pool.acquired[0]["claimed_by"] == "worker_one"
    view = load_task_queue(queue)
    assert view["pending_todo_ids"] == ["todo_b"]


def test_worker_pool_drain_claims_for_idle_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="pool-drain")
    enqueue_tasks(queue, goal_id="pool-drain", todo_ids=["a", "b", "c"], recorded_at="t")
    pool = WorkerPool(worker_ids=["w1", "w2"], runtime_root=tmp_path, goal_id="pool-drain")
    acquired = pool.drain()
    assert [e["todo_id"] for e in acquired] == ["a", "b"]
    # Second drain sees both workers busy -> no new acquisitions.
    assert pool.drain() == []
    view = load_task_queue(queue)
    assert view["claimed_todo_ids"] == ["a", "b"]
    assert view["pending_todo_ids"] == ["c"]


def test_worker_pool_acquire_respects_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    queue = task_queue_path(tmp_path, goal_id="pool-off")
    enqueue_tasks(queue, goal_id="pool-off", todo_ids=["a"], recorded_at="t", use_event_driven=True)
    pool = WorkerPool(
        worker_ids=["w1"], runtime_root=tmp_path, goal_id="pool-off", use_event_driven=False
    )
    assert pool.acquire("w1") is None
    assert pool.acquired == []


# ---------------------------------------------------------------------------
# Resident Scheduler
# ---------------------------------------------------------------------------


def test_resident_scheduler_tick_advances_ready_from_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-tick"
    _seed_gate_events(tmp_path, goal_id)
    scheduler = ResidentScheduler(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        use_event_driven=True,
    )
    payload = scheduler.tick()
    assert payload.get("disabled") is not True
    dispatch = payload["event_driven_dispatch"]
    assert dispatch["ready_successors"] == ["todo_second"]
    assert dispatch["newly_enqueued"] == ["todo_second"]
    assert scheduler.tick_count == 1


def test_resident_scheduler_bounded_run_writes_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-bounded"
    _seed_gate_events(tmp_path, goal_id)
    result = run_resident_scheduler_bounded(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        max_iterations=1,
        use_event_driven=True,
    )
    assert result["ok"] is True
    assert result["enabled"] is True
    assert result["tick_count"] == 1
    queue = result["queue"]
    assert "todo_second" in queue["claimed_todo_ids"] or "todo_second" in queue["pending_todo_ids"]


def test_resident_scheduler_tick_reconciles_zombie_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P0 closure: the resident tick runs lease/retry reconciliation each pass."""
    from loopx.control_plane.scheduler.task_lifecycle import (
        claim_next_eligible_task,
    )

    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-reconcile"
    _seed_gate_events(tmp_path, goal_id)
    queue = task_queue_path(tmp_path, goal_id=goal_id)
    # Seed a zombie: enqueue + claim with a short lease that is now expired.
    enqueue_tasks(queue, goal_id=goal_id, todo_ids=["todo_zombie"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(queue, worker_id="worker_one", lease_seconds=10, now=1000.0)
    scheduler = ResidentScheduler(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        use_event_driven=True,
        reconcile=True,
    )
    payload = scheduler.tick()
    reconcile = ((payload.get("event_driven_dispatch") or {}).get("reconcile")) or {}
    assert reconcile.get("expired_count") == 1
    assert reconcile.get("expired_leases") == ["todo_zombie"]
    # The reconcile summary is surfaced on the resident payload too.
    assert (payload.get("resident_scheduler") or {}).get("reconcile") is not None


def test_resident_scheduler_reconcile_disabled_by_default_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loopx.control_plane.scheduler.task_lifecycle import (
        claim_next_eligible_task,
    )

    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-reconcile-off"
    _seed_gate_events(tmp_path, goal_id)
    queue = task_queue_path(tmp_path, goal_id=goal_id)
    enqueue_tasks(queue, goal_id=goal_id, todo_ids=["todo_zombie"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(queue, worker_id="worker_one", lease_seconds=10, now=1000.0)
    scheduler = ResidentScheduler(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        use_event_driven=True,
        reconcile=False,
    )
    payload = scheduler.tick()
    reconcile = ((payload.get("event_driven_dispatch") or {}).get("reconcile"))
    assert reconcile is None


def test_resident_scheduler_bounded_disabled_returns_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    goal_id = "resident-off"
    _seed_gate_events(tmp_path, goal_id)
    result = run_resident_scheduler_bounded(
        runtime_root=tmp_path,
        goal_id=goal_id,
        max_iterations=1,
        use_event_driven=False,
    )
    assert result["enabled"] is False
    assert not task_queue_path(tmp_path, goal_id=goal_id).exists()


# ---------------------------------------------------------------------------
# Merge: event-driven + heartbeat wiring
# ---------------------------------------------------------------------------


def test_merge_enabled_requires_all_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    # The new architecture is ON by default (master switch): with all feature
    # envs unset, merge inherits the master switch and is enabled.
    monkeypatch.delenv(MERGE_PATH_ENV, raising=False)
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    monkeypatch.delenv("LOOPX_HEARTBEAT_EVENT_SOURCE", raising=False)
    monkeypatch.delenv("LOOPX_NEW_ARCHITECTURE", raising=False)
    assert merge_enabled() is True
    # An explicit flag always wins over the master switch.
    assert merge_enabled(use_merge=False) is False
    assert merge_enabled(use_merge=True, use_event_driven=True, use_event_source=True) is True
    # Merge still requires the eventing AND event-source layers; disabling any
    # of them (explicitly) disables the merge.
    assert merge_enabled(use_event_driven=False) is False
    assert merge_enabled(use_event_source=False) is False
    # The master switch can turn the whole new architecture off.
    monkeypatch.setenv("LOOPX_NEW_ARCHITECTURE", "0")
    assert merge_enabled() is False
    # Merge requires all three layers; with the master switch off, all feature
    # envs must be explicitly on to re-enable the merge.
    monkeypatch.setenv(MERGE_PATH_ENV, "1")
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    monkeypatch.setenv("LOOPX_HEARTBEAT_EVENT_SOURCE", "1")
    assert merge_enabled() is True


def test_merge_disabled_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MERGE_PATH_ENV, raising=False)
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    goal_id = "merge-off"
    payload = merge_event_driven_and_heartbeat(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        use_merge=False,
    )
    assert payload.get("disabled") is True
    assert not rollout_event_log_path(tmp_path, goal_id).exists()
    assert not task_queue_path(tmp_path, goal_id=goal_id).exists()


def test_merge_enabled_records_heartbeat_and_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MERGE_PATH_ENV, "1")
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    monkeypatch.setenv("LOOPX_HEARTBEAT_EVENT_SOURCE", "1")
    goal_id = "merge-on"
    payload = merge_event_driven_and_heartbeat(
        runtime_root=tmp_path,
        goal_id=goal_id,
        agent_id="agent_one",
        items=_gate_items(),
        completed_todo_id="todo_first",
        worker_id="worker_one",
        use_event_driven=True,
        use_event_source=True,
        use_merge=True,
        recorded_at="2026-08-14T00:00:00Z",
    )
    assert payload.get("disabled") is not True
    assert payload["heartbeat"]["event"]["event_kind"] == "heartbeat_observed"
    dispatch = payload["event_driven_dispatch"]
    assert dispatch["ready_successors"] == ["todo_second"]
    assert dispatch["newly_enqueued"] == ["todo_second"]

    # Heartbeat fact + task_ready/task_enqueued/task_dispatched events.
    events = load_rollout_events(rollout_event_log_path(tmp_path, goal_id))
    kinds = {e.get("event_kind") for e in events}
    assert "heartbeat_observed" in kinds
    assert "task_ready" in kinds
    assert "task_enqueued" in kinds


def test_merge_policy_decision_attached_when_status_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(MERGE_PATH_ENV, "1")
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    monkeypatch.setenv("LOOPX_HEARTBEAT_EVENT_SOURCE", "1")
    goal_id = "merge-policy"
    status_payload = {"decision": "run", "should_run": True}
    payload = merge_event_driven_and_heartbeat(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        status_payload=status_payload,
        use_event_driven=True,
        use_event_source=True,
        use_merge=True,
    )
    decision = payload["policy_decision"]
    assert decision is not None
    assert decision["outcome"] in {"run", "wait", "deny"}
    assert decision["source"] in {"quota", "scheduler", "capability"}


def test_merge_forwards_scheduler_context_to_policy_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: the merged path must forward scheduler_execution_context from
    # the status payload so PolicyEngine validates it instead of returning
    # "missing required field" (invalid_scheduler_execution_context).
    monkeypatch.setenv(MERGE_PATH_ENV, "1")
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    monkeypatch.setenv("LOOPX_HEARTBEAT_EVENT_SOURCE", "1")
    goal_id = "merge-ctx-forward"
    status_payload = {
        "decision": "run",
        "should_run": True,
        "scheduler_execution_context": {
            "host_surface": "codex_cli",
            "scheduler_owner": "agent_cli_loop",
            "execution_mode": "interactive",
        },
    }
    payload = merge_event_driven_and_heartbeat(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        status_payload=status_payload,
        use_event_driven=True,
        use_event_source=True,
        use_merge=True,
    )
    decision = payload["policy_decision"]
    assert decision is not None
    # Scheduler context now passes validation; the decision proceeds to the
    # quota gate (source != scheduler) instead of short-circuiting on a missing
    # execution-context field.
    assert decision["source"] != "scheduler"
    assert decision["outcome"] in {"run", "wait", "deny"}


def test_load_todo_items_from_rollout_log_reconstructs_real_goal_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: real goals record task mutations in rollout-event-log.jsonl
    # (todo_add / todo_complete) rather than a separate events.jsonl store, so
    # event-driven dispatch must reconstruct items from the rollout log.
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "rollout-items"
    log_path = tmp_path / "goals" / goal_id / "rollout-event-log.jsonl"
    events = [
        ("todo_a", "todo_add", "open", "agent"),
        ("todo_a", "todo_complete", "done", "agent"),
        ("todo_b", "todo_add", "open", "user"),
    ]
    for index, (todo_id, kind, status, role) in enumerate(events):
        event = build_rollout_event(
            goal_id=goal_id,
            event_kind=kind,
            agent_id="agent_one",
            status=status,
            summary=f"{kind} {todo_id}",
            details={"role": role, "todo_command": "add" if kind == "todo_add" else "complete"},
            recorded_at="2026-08-14T00:00:00Z",
        )
        event["todo_id"] = todo_id
        event["event_id"] = f"rollout-r{index}"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(__import__("json").dumps(event, ensure_ascii=True) + "\n")
    items = load_todo_items_from_rollout_log(tmp_path, goal_id)
    by_id = {i["todo_id"]: i for i in items}
    assert by_id["todo_a"]["status"] == "done"
    assert by_id["todo_a"]["role"] == "agent"
    assert by_id["todo_b"]["status"] == "open"
    assert by_id["todo_b"]["role"] == "user"


def test_load_todo_items_reconstructs_dependencies_and_excluded_agents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression: dependencies live in causality.unblocks (build_rollout_event's
    # ``unblocks`` param), and excluded_agents are stored as stringified lists
    # in details. The reconstructor must recover both so handoff gates recompute.
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "rollout-deps"
    log_path = tmp_path / "goals" / goal_id / "rollout-event-log.jsonl"
    entries = [
        # gate: done, excludes agent_worker, unblocks successor (via causality)
        ("todo_gate_abc", "todo_add", "open", "user", ["todo_followup_xyz"],
         {"role": "user", "task_class": "user_gate", "excluded_agents": "agent_worker"}),
        ("todo_gate_abc", "todo_complete", "done", "user", ["todo_followup_xyz"],
         {"role": "user", "task_class": "user_gate", "excluded_agents": "['agent_worker']"}),
        ("todo_followup_xyz", "todo_add", "open", "agent", ["todo_gate_abc"],
         {"role": "agent", "task_class": "advancement_task", "excluded_agents": ""}),
    ]
    for index, (todo_id, kind, status, role, unblocks, details) in enumerate(entries):
        event = build_rollout_event(
            goal_id=goal_id,
            event_kind=kind,
            agent_id="agent_one",
            status=status,
            summary=f"{kind} {todo_id}",
            unblocks=unblocks,
            details=details,
            recorded_at="2026-08-14T00:00:00Z",
        )
        event["todo_id"] = todo_id
        event["event_id"] = f"deps-r{index}"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(__import__("json").dumps(event, ensure_ascii=True) + "\n")
    items = load_todo_items_from_rollout_log(tmp_path, goal_id)
    by_id = {i["todo_id"]: i for i in items}
    assert by_id["todo_gate_abc"]["status"] == "done"
    # Dependencies recovered from causality.unblocks.
    assert by_id["todo_gate_abc"]["unblocks_todo_id"] == "todo_followup_xyz"
    assert by_id["todo_followup_xyz"]["unblocks_todo_id"] == "todo_gate_abc"
    # Excluded agents recovered from both comma-string and stringified repr list.
    assert by_id["todo_gate_abc"]["excluded_agents"] == ["agent_worker"]
    assert by_id["todo_followup_xyz"]["excluded_agents"] == []


# ---------------------------------------------------------------------------
# Worker execution (new-architecture opt-in execution, mirrors original gates)
# ---------------------------------------------------------------------------


def _fake_runner(ok: bool = True):
    def _run(command, **kwargs):
        return {"ok": ok, "returncode": 0 if ok else 1, "timed_out": False,
                "output_captured": False, "output": ""}
    return _run


def test_execute_claimed_task_requires_command_guard_and_prefix() -> None:
    entry = {"todo_id": "todo_x", "claimed_by": "worker_one"}
    # No command
    r = execute_claimed_task(entry)
    assert r["executed"] is False and r["reason"] == "worker_command_missing"
    # Command but no guard
    r = execute_claimed_task(entry, worker_command="sed -i s/a/b/g file")
    assert r["executed"] is False and r["reason"] == "fresh_quota_guard_confirmation_required"
    # Guard but no prefix
    r = execute_claimed_task(entry, worker_command="sed -i s/a/b/g file", guard_checked=True)
    assert r["executed"] is False and r["reason"] == "worker_command_prefix_required"
    # Prefix mismatch
    r = execute_claimed_task(entry, worker_command="rm -rf /", guard_checked=True,
                             worker_command_prefixes=["sed"])
    assert r["executed"] is False and r["reason"] == "worker_command_prefix_mismatch"


def test_execute_claimed_task_runs_whitelisted_command() -> None:
    entry = {"todo_id": "todo_x", "claimed_by": "worker_one"}
    r = execute_claimed_task(
        entry,
        worker_command="sed -i s/Inter/Poppins/g index.html",
        guard_checked=True,
        worker_command_prefixes=["sed"],
        runner=_fake_runner(ok=True),
    )
    assert r["executed"] is True
    assert r["reason"] == "executed"
    assert r["todo_id"] == "todo_x"


def test_resident_bounded_runs_worker_exec_for_claimed_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-exec"
    _seed_gate_events(tmp_path, goal_id)
    result = run_resident_scheduler_bounded(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        max_iterations=1,
        use_event_driven=True,
        worker_exec_command="sed -i s/Inter/Poppins/g index.html",
        worker_exec_command_prefixes=["sed"],
        guard_checked=True,
        runner=_fake_runner(ok=True),
    )
    tick = result["ticks"][0]
    executions = (tick.get("resident_scheduler") or {}).get("worker_executions") or []
    assert executions, "worker should have executed a claimed task"
    assert executions[0]["executed"] is True
    assert executions[0]["claimed_by"] == "worker_one"


def test_resident_closed_loop_complete_acceptance_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full closed loop: claim -> execute -> task_completed -> acceptance -> goal_closed."""
    from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path
    from loopx.control_plane.goals.goal_acceptance import build_grep_evidence

    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-closed-loop"
    _seed_gate_events(tmp_path, goal_id)
    result = run_resident_scheduler_bounded(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        max_iterations=1,
        use_event_driven=True,
        worker_exec_command="sed -i s/Inter/Poppins/g index.html",
        worker_exec_command_prefixes=["sed"],
        guard_checked=True,
        runner=_fake_runner(ok=True),
        acceptance_criteria=[
            {"criterion_id": "font_poppins", "description": "font is Poppins"},
        ],
        evidence=[
            build_grep_evidence(
                ref="index.html",
                pattern="Poppins",
                match=True,
                criterion_ids=["font_poppins"],
            )
        ],
    )
    finalize = result.get("finalize")
    assert finalize is not None, "closed loop finalize must run when exec + acceptance declared"
    # Task was completed.
    assert finalize["task_results"], "completed task result expected"
    assert finalize["task_results"][0]["executed"] is True
    assert finalize["task_results"][0]["completed"] is True
    # Acceptance satisfied.
    assert finalize["acceptance"]["satisfied"] is True
    # Goal closed.
    assert finalize["closed"] is True
    assert finalize["closure"]["ready"] is True
    # Events: task_completed + goal_closure_ready + goal_closed recorded.
    kinds = [e["event_kind"] for e in load_rollout_events(
        rollout_event_log_path(tmp_path, goal_id), limit=100
    )]
    assert "task_completed" in kinds
    assert "goal_closure_ready" in kinds
    assert "goal_closed" in kinds


def test_resident_closed_loop_acceptance_gap_holds_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With an acceptance gap, the goal is held (goal_acceptance_pending), not closed."""
    from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path
    from loopx.control_plane.goals.goal_acceptance import build_grep_evidence

    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "resident-closed-loop-gap"
    _seed_gate_events(tmp_path, goal_id)
    result = run_resident_scheduler_bounded(
        runtime_root=tmp_path,
        goal_id=goal_id,
        worker_ids=["worker_one"],
        max_iterations=1,
        use_event_driven=True,
        worker_exec_command="sed -i s/Inter/Poppins/g index.html",
        worker_exec_command_prefixes=["sed"],
        guard_checked=True,
        runner=_fake_runner(ok=True),
        acceptance_criteria=[
            {"criterion_id": "font_poppins", "description": "font is Poppins"},
        ],
        # Evidence that FAILS (match=False) -> gap -> goal held, not closed.
        evidence=[
            build_grep_evidence(
                ref="index.html", pattern="Poppins", match=False, criterion_ids=["font_poppins"]
            )
        ],
    )
    finalize = result.get("finalize")
    assert finalize is not None
    assert finalize["acceptance"]["satisfied"] is False
    assert finalize["closed"] is False
    kinds = [e["event_kind"] for e in load_rollout_events(
        rollout_event_log_path(tmp_path, goal_id), limit=100
    )]
    assert "goal_acceptance_pending" in kinds
    assert "goal_closed" not in kinds


def test_finalize_resident_execution_direct(
    tmp_path: Path,
) -> None:
    """Direct unit test of finalize_resident_execution."""
    from loopx.control_plane.scheduler.event_driven_dispatch import enqueue_tasks, task_queue_path
    from loopx.control_plane.scheduler.task_lifecycle import claim_next_eligible_task
    from loopx.control_plane.goals.goal_acceptance import build_manual_evidence

    goal_id = "finalize-direct"
    queue = task_queue_path(tmp_path, goal_id=goal_id)
    enqueue_tasks(queue, goal_id=goal_id, todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(queue, worker_id="worker_one", lease_seconds=100, now=1000.0)
    result = finalize_resident_execution(
        runtime_root=tmp_path,
        goal_id=goal_id,
        event_log_path=rollout_event_log_path(tmp_path, goal_id),
        executed=[{"todo_id": "todo_a", "claimed_by": "worker_one", "executed": True, "ok": True}],
        worker_id="worker_one",
        acceptance_criteria=[{"criterion_id": "c1", "description": "d"}],
        evidence=[build_manual_evidence(ref="r", content="c", ok=True, criterion_ids=["c1"])],
    )
    assert result["task_results"][0]["completed"] is True
    assert result["acceptance"]["satisfied"] is True
    assert result["closed"] is True

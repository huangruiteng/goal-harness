#!/usr/bin/env python3
"""Deterministic TEST ONLY Turn/coordination authority canary.

Competing LoopX processes share one file-backed coordination head, but never a
Turn journal or workspace.  A separate crash-recovery case reopens only the
same agent's own journal.  The file provider is the deterministic provider for
the production ``CoordinationAuthorityExecutor`` contract used by the NoKV
adapter.  This proves protocol admission and stale-epoch effect fencing; it
does not claim shared production wiring or exactly-once behavior for arbitrary
Host workspace mutations.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from queue import Empty
from tempfile import TemporaryDirectory
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.fspath(REPOSITORY_ROOT))

from loopx.control_plane.coordination.executor import (
    CoordinationAuthorityExecutor,
    sample_work_envelope,
)
from loopx.control_plane.coordination.file_provider import (
    FileCoordinationProvider,
)
from loopx.control_plane.coordination.head import (
    bootstrap_head,
    validated_head,
)
from loopx.control_plane.turn_driver import (
    build_loopx_turn_plan,
    build_turn_authority_command_guard,
    run_loopx_turn_once,
)
from loopx.file_lock import exclusive_file_lock

GOAL_ID = "goal-authority-turn-canary"
TODO_ID = "todo_authority_canary"
AGENTS = ("agent-a", "agent-b")
LEASE_TTL_SECONDS = 2
RECLAIM_GRACE_SECONDS = 3.0
CRASH_EXIT_CODE = 73


def _todo() -> dict[str, Any]:
    return {
        "todo_revision": 7,
        "status": "open",
        "claimed_by": None,
        "eligibility": {
            "authorization_projection_revision": 3,
            "authorization_projection_digest": "sha256:canary-authority",
            "allowed_agent_ids": list(AGENTS),
            "dependencies_satisfied": True,
            "dependency_revision": 12,
            "gates_open": True,
            "gate_revision": 5,
        },
        "repository": "git:example/authority-canary",
        "code_revision": "0123456789abcdef",
        "last_lease_epoch": 6,
    }


def _bootstrap(store: Path) -> None:
    provider = FileCoordinationProvider(store, GOAL_ID)
    head = bootstrap_head(
        GOAL_ID,
        {TODO_ID: _todo()},
        store_binding=provider.store_identity(),
    )
    outcome = provider.compare_and_put(0, head)
    if outcome.get("result") != "applied":
        raise RuntimeError(f"canary bootstrap failed: {outcome!r}")


def _plan(agent_id: str, scenario: str) -> dict[str, Any]:
    return build_loopx_turn_plan(
        {
            "ok": True,
            "schema_version": "loopx_turn_envelope_v0",
            "goal_id": GOAL_ID,
            "agent_id": agent_id,
            "should_run": True,
            "effective_action": "normal_run",
            "action": {
                "must_attempt": True,
                "delivery_allowed": True,
                "quiet_noop_allowed": False,
                "selected_todo": {
                    "todo_id": TODO_ID,
                    "text": "Run the deterministic authority canary",
                },
            },
            "user": {
                "action_required": False,
                "open_count": 0,
                "notify": "DONT_NOTIFY",
            },
            "writeback": {"spend_after_validation": True},
            "scheduler": {"action": "run_now"},
            "action_signature": {
                "matches": True,
                "source_hash": "sha256:authority-canary",
                "envelope_hash": "sha256:authority-canary",
            },
            "compaction": {"within_budget": True},
        },
        host="generic-cli",
        execution_mode="isolated-headless",
        turn_instance_id=f"{scenario}-{agent_id}",
    )


def _host_result(plan: Mapping[str, Any]) -> dict[str, Any]:
    transaction = plan["transaction"]
    return {
        "schema_version": "loopx_turn_result_v0",
        "turn_key": transaction["turn_key"],
        "result_kind": "validated_completion",
        "completed_phases": ["host_execute", "typed_result"],
        "classification": "authority_canary_completion",
        "recommended_action": "Review the deterministic canary receipt.",
        "next_action": "Finish the canary qualification.",
        "delivery_batch_scale": "implementation",
        "delivery_outcome": "outcome_progress",
        "vision_unchanged_reason": "The canary objective remains unchanged.",
        "summary": "One authority-qualified canary Turn completed.",
    }


def _append_event(path: Path, agent_id: str, stage: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(path), path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"agent_id": agent_id, "stage": stage}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _guard_argv(store: Path, clock: Path, agent_id: str) -> list[str]:
    return [
        sys.executable,
        os.fspath(Path(__file__).with_name("authority_guard.py")),
        "--store-directory",
        os.fspath(store),
        "--clock-file",
        os.fspath(clock),
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        agent_id,
        "--todo-id",
        TODO_ID,
        "--lease-ttl-seconds",
        str(LEASE_TTL_SECONDS),
        "--reclaim-grace-seconds",
        str(RECLAIM_GRACE_SECONDS),
    ]


def _worker(
    store: Path,
    clock: Path,
    base: Path,
    event_log: Path,
    scenario: str,
    agent_id: str,
    start: Any,
    host_started: Any,
    release_host: Any,
    queue: Any,
    crash_before_durable_effect: bool = False,
) -> None:
    try:
        plan = _plan(agent_id, scenario)
        guard = build_turn_authority_command_guard(
            _guard_argv(store, clock, agent_id),
            project=base,
            timeout_seconds=10,
        )
        start.wait(timeout=20)

        def host(_request: Mapping[str, Any]) -> dict[str, Any]:
            _append_event(event_log, agent_id, "host")
            if host_started is not None:
                host_started.set()
            if release_host is not None and not release_host.wait(timeout=20):
                raise RuntimeError("canary Host release timed out")
            return _host_result(plan)

        def writeback(_result: Mapping[str, Any]) -> dict[str, Any]:
            _append_event(event_log, agent_id, "writeback")
            return {"ok": True, "appended": True}

        def completion_writeback(_result: Mapping[str, Any]) -> dict[str, Any]:
            _append_event(event_log, agent_id, "writeback")
            return {
                "ok": True,
                "appended": True,
                "completion": {
                    "todo_id": TODO_ID,
                    "continuation": "no_followup",
                },
            }

        def completion_intent(_result: Mapping[str, Any]) -> dict[str, Any]:
            return {"todo_id": TODO_ID, "continuation": "no_followup"}

        def terminal_closeout(_result: Mapping[str, Any]) -> dict[str, Any]:
            return {
                "ok": True,
                "appended": True,
                "completion": {
                    "todo_id": TODO_ID,
                    "continuation": "no_followup",
                },
            }

        def spend() -> dict[str, Any]:
            _append_event(event_log, agent_id, "quota_spend")
            return {"ok": True, "appended": True, "slots": 1}

        def scheduler(_spend: Mapping[str, Any]) -> dict[str, Any]:
            _append_event(event_log, agent_id, "scheduler")
            return {"completed": True, "acknowledged": False}

        def validate(
            _plan: Mapping[str, Any], _result: Mapping[str, Any]
        ) -> dict[str, Any]:
            if crash_before_durable_effect:
                # The Turn driver has already made the typed Host result durable,
                # but has not reached its first authority-protected effect.
                os._exit(CRASH_EXIT_CODE)
            return {
                "status": "passed",
                "validator_kind": "authority_canary",
                "summary": "deterministic canary postcondition passed",
            }

        payload = run_loopx_turn_once(
            plan,
            host_runner=host,
            project=base / f"workspace-{scenario}-{agent_id}",
            runtime_root=base / f"runtime-{scenario}-{agent_id}",
            goal_id=GOAL_ID,
            timeout_seconds=15,
            execute=True,
            task_validator=validate,
            writeback=writeback,
            completion_writeback=completion_writeback,
            completion_intent=completion_intent,
            terminal_closeout=terminal_closeout,
            spend=spend,
            scheduler=scheduler,
            authority_checkpoint_guard=guard,
        )
        queue.put({"agent_id": agent_id, "payload": payload})
    except BaseException as exc:  # noqa: BLE001 - child reports compact failure
        queue.put(
            {
                "agent_id": agent_id,
                "error": type(exc).__name__,
                "message": str(exc),
            }
        )


def _read_events(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _run_workers(
    *,
    context: multiprocessing.context.BaseContext,
    store: Path,
    clock: Path,
    base: Path,
    event_log: Path,
    scenario: str,
    block_agent_a: bool,
) -> tuple[list[dict[str, Any]], Any, Any, list[Any]]:
    start = context.Event()
    a_started = context.Event() if block_agent_a else None
    release_a = context.Event() if block_agent_a else None
    queue = context.Queue()
    processes = []
    for agent_id in AGENTS:
        process = context.Process(
            target=_worker,
            args=(
                store,
                clock,
                base,
                event_log,
                scenario,
                agent_id,
                start,
                a_started if agent_id == "agent-a" else None,
                release_a if agent_id == "agent-a" else None,
                queue,
            ),
        )
        processes.append(process)
    return [], a_started, release_a, [queue, start, *processes]


def _collect(queue: Any, processes: list[Any]) -> list[dict[str, Any]]:
    results = []
    for _process in processes:
        try:
            results.append(queue.get(timeout=30))
        except Empty as exc:
            raise RuntimeError("canary child did not report") from exc
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            raise RuntimeError("canary child did not exit")
        if process.exitcode != 0:
            raise RuntimeError(f"canary child exited {process.exitcode}")
    if any("error" in result for result in results):
        raise RuntimeError(f"canary worker failed: {results!r}")
    return results


def _receipt_commands(store: Path) -> list[str]:
    provider = FileCoordinationProvider(store, GOAL_ID)
    head_value, _generation = provider.load()
    head = validated_head(head_value, goal_id=GOAL_ID)
    return sorted(
        str(entry["original_receipt"]["command"])
        for entry in head["receipt_index"].values()
    )


def run() -> dict[str, Any]:
    context = multiprocessing.get_context("spawn")
    with TemporaryDirectory(prefix="loopx-authority-turn-canary-") as raw_base:
        base = Path(raw_base)

        race_store = base / "race-store"
        race_clock = base / "race-clock"
        race_events_path = base / "race-events.jsonl"
        race_clock.write_text("1000", encoding="utf-8")
        _bootstrap(race_store)
        _, _, _, race_parts = _run_workers(
            context=context,
            store=race_store,
            clock=race_clock,
            base=base,
            event_log=race_events_path,
            scenario="race",
            block_agent_a=False,
        )
        race_queue, race_start, *race_processes = race_parts
        for process in race_processes:
            process.start()
        race_start.set()
        race_results = _collect(race_queue, race_processes)
        race_committed = [
            result
            for result in race_results
            if result["payload"].get("status") == "committed"
        ]
        race_rejected = [
            result
            for result in race_results
            if result["payload"].get("result_kind") == "authority_rejected"
        ]
        race_events = _read_events(race_events_path)
        if len(race_committed) != 1 or len(race_rejected) != 1:
            raise RuntimeError(f"race did not select one authority: {race_results!r}")
        if [event["stage"] for event in race_events].count("host") != 1:
            raise RuntimeError(f"race invoked more than one Host: {race_events!r}")
        race_commands = _receipt_commands(race_store)

        reclaim_store = base / "reclaim-store"
        reclaim_clock = base / "reclaim-clock"
        reclaim_events_path = base / "reclaim-events.jsonl"
        reclaim_clock.write_text("2000", encoding="utf-8")
        _bootstrap(reclaim_store)
        _, a_started, release_a, reclaim_parts = _run_workers(
            context=context,
            store=reclaim_store,
            clock=reclaim_clock,
            base=base,
            event_log=reclaim_events_path,
            scenario="reclaim",
            block_agent_a=True,
        )
        reclaim_queue, reclaim_start, *reclaim_processes = reclaim_parts
        # Start the old holder first so the test controls the failover epoch.
        reclaim_processes[0].start()
        reclaim_start.set()
        if a_started is None or not a_started.wait(timeout=30):
            raise RuntimeError("old holder never reached Host")
        # A lease that has merely expired is not yet reclaimable. Exercise a
        # separate B Turn just before the explicit skew-grace boundary.
        reclaim_clock.write_text("2004.999", encoding="utf-8")
        early_queue = context.Queue()
        early_start = context.Event()
        early_reclaimer = context.Process(
            target=_worker,
            args=(
                reclaim_store,
                reclaim_clock,
                base,
                reclaim_events_path,
                "reclaim-before-grace",
                "agent-b",
                early_start,
                None,
                None,
                early_queue,
            ),
        )
        early_reclaimer.start()
        early_start.set()
        early_result = _collect(early_queue, [early_reclaimer])[0]
        early_payload = early_result["payload"]
        if early_payload.get("result_kind") != "authority_rejected":
            raise RuntimeError(
                f"reclaimer crossed the grace window early: {early_payload!r}"
            )
        early_events = _read_events(reclaim_events_path)
        early_reclaimer_host_count = sum(
            event["agent_id"] == "agent-b" and event["stage"] == "host"
            for event in early_events
        )
        if early_reclaimer_host_count != 0:
            raise RuntimeError(
                "early reclaimer reached Host before authority admission"
            )

        # At expiry plus the complete grace window, B performs a real reclaim.
        reclaim_clock.write_text("2005", encoding="utf-8")
        reclaim_processes[1].start()
        first = reclaim_queue.get(timeout=30)
        if first.get("agent_id") != "agent-b":
            raise RuntimeError(f"reclaimer did not finish first: {first!r}")
        assert release_a is not None
        release_a.set()
        second = reclaim_queue.get(timeout=30)
        reclaim_results = [first, second]
        for process in reclaim_processes:
            process.join(timeout=10)
            if process.exitcode != 0:
                raise RuntimeError(f"reclaim child exited {process.exitcode}")
        if any("error" in result for result in reclaim_results):
            raise RuntimeError(f"reclaim worker failed: {reclaim_results!r}")
        by_agent = {result["agent_id"]: result["payload"] for result in reclaim_results}
        if by_agent["agent-b"].get("status") != "committed":
            raise RuntimeError(f"reclaimer did not commit: {by_agent!r}")
        if by_agent["agent-a"].get("result_kind") != "writeback_failed":
            raise RuntimeError(f"stale holder was not fenced: {by_agent!r}")
        stale_receipt = by_agent["agent-a"]["authority_checkpoint_guard"][
            "checkpoints"
        ]["durable_writeback"]
        if stale_receipt.get("reason_code") != "stale_lease_fence":
            raise RuntimeError(f"stale fence was not typed: {stale_receipt!r}")
        reclaim_events = _read_events(reclaim_events_path)
        a_effects = [
            event["stage"] for event in reclaim_events if event["agent_id"] == "agent-a"
        ]
        if a_effects != ["host"]:
            raise RuntimeError(f"stale holder emitted a later effect: {a_effects!r}")
        reclaim_commands = _receipt_commands(reclaim_store)

        crash_store = base / "crash-store"
        crash_clock = base / "crash-clock"
        crash_events_path = base / "crash-events.jsonl"
        crash_runtime = base / "runtime-crash-resume-agent-a"
        crash_clock.write_text("3000", encoding="utf-8")
        _bootstrap(crash_store)
        crash_queue = context.Queue()
        crash_start = context.Event()
        crashing = context.Process(
            target=_worker,
            args=(
                crash_store,
                crash_clock,
                base,
                crash_events_path,
                "crash-resume",
                "agent-a",
                crash_start,
                None,
                None,
                crash_queue,
                True,
            ),
        )
        crashing.start()
        crash_start.set()
        crashing.join(timeout=30)
        if crashing.is_alive():
            crashing.terminate()
            crashing.join(timeout=5)
            raise RuntimeError("crash-injection child did not exit")
        if crashing.exitcode != CRASH_EXIT_CODE:
            raise RuntimeError(
                f"crash injection exited {crashing.exitcode}, expected {CRASH_EXIT_CODE}"
            )
        crash_journals = list(crash_runtime.rglob("*.json"))
        if len(crash_journals) != 1:
            raise RuntimeError(
                f"crash scenario journal count drifted: {crash_journals!r}"
            )
        before_resume = json.loads(crash_journals[0].read_text(encoding="utf-8"))
        if before_resume.get("completed_phases") != ["host_execute", "typed_result"]:
            raise RuntimeError(
                f"crash did not occur before the first durable effect: {before_resume!r}"
            )
        original_binding = before_resume["authority_checkpoint_guard"]["binding"]

        resume_queue = context.Queue()
        resume_start = context.Event()
        resuming = context.Process(
            target=_worker,
            args=(
                crash_store,
                crash_clock,
                base,
                crash_events_path,
                "crash-resume",
                "agent-a",
                resume_start,
                None,
                None,
                resume_queue,
            ),
        )
        resuming.start()
        resume_start.set()
        resumed_result = _collect(resume_queue, [resuming])[0]
        resumed_payload = resumed_result["payload"]
        if resumed_payload.get("status") != "committed":
            raise RuntimeError(f"same-agent Turn recovery failed: {resumed_payload!r}")
        resumed_binding = resumed_payload["authority_checkpoint_guard"]["binding"]
        crash_events = _read_events(crash_events_path)
        crash_event_counts = {
            stage: sum(event["stage"] == stage for event in crash_events)
            for stage in ("host", "writeback", "quota_spend", "scheduler")
        }
        crash_commands = _receipt_commands(crash_store)

        unavailable_clock = base / "unavailable-clock"
        unavailable_events = base / "unavailable-events.jsonl"
        unavailable_parent = base / "provider-unavailable"
        unavailable_clock.write_text("4000", encoding="utf-8")
        unavailable_parent.write_text("not a directory", encoding="utf-8")
        unavailable_queue = context.Queue()
        unavailable_start = context.Event()
        unavailable = context.Process(
            target=_worker,
            args=(
                unavailable_parent / "store",
                unavailable_clock,
                base,
                unavailable_events,
                "provider-unavailable",
                "agent-a",
                unavailable_start,
                None,
                None,
                unavailable_queue,
            ),
        )
        unavailable.start()
        unavailable_start.set()
        unavailable_result = _collect(unavailable_queue, [unavailable])[0]["payload"]
        unavailable_receipt = unavailable_result["authority_checkpoint_guard"][
            "checkpoints"
        ]["host_admission"]
        if (
            unavailable_result.get("result_kind") != "authority_rejected"
            or unavailable_receipt.get("reason_code") != "authority_guard_unavailable"
            or _read_events(unavailable_events)
        ):
            raise RuntimeError(
                f"provider outage did not fail closed before Host: {unavailable_result!r}"
            )

        if "claim_work" not in race_commands:
            raise RuntimeError(
                "race did not use CoordinationAuthorityExecutor claim_work"
            )
        if "renew_work" not in race_commands:
            raise RuntimeError(
                "race did not use CoordinationAuthorityExecutor renew_work"
            )
        if "reclaim_work" not in reclaim_commands:
            raise RuntimeError(
                "failover did not use CoordinationAuthorityExecutor reclaim_work"
            )

        return {
            "ok": True,
            "schema_version": "loopx_authority_turn_canary_v0",
            "provider": "FileCoordinationProvider(TEST_ONLY)",
            "shared_state": "one CoordinationAuthorityExecutor head per scenario",
            "race": {
                "committed_agent": race_committed[0]["agent_id"],
                "host_count": 1,
                "rejected_before_host": True,
                "authority_commands": race_commands,
            },
            "expiry_reclaim": {
                "old_epoch": by_agent["agent-a"]["authority_checkpoint_guard"][
                    "binding"
                ]["lease_epoch"],
                "new_epoch": by_agent["agent-b"]["authority_checkpoint_guard"][
                    "binding"
                ]["lease_epoch"],
                "reclaim_grace_seconds": RECLAIM_GRACE_SECONDS,
                "blocked_before_expiry_plus_grace": True,
                "early_reclaimer_host_count": early_reclaimer_host_count,
                "stale_holder_later_effects": 0,
                "authority_commands": reclaim_commands,
            },
            "crash_resume": {
                "crash_exit_code": CRASH_EXIT_CODE,
                "same_agent": resumed_result["agent_id"] == "agent-a",
                "same_turn_journal": len(list(crash_runtime.rglob("*.json"))) == 1,
                "original_binding_reused": resumed_binding == original_binding,
                "host_count": crash_event_counts["host"],
                "writeback_count": crash_event_counts["writeback"],
                "quota_spend_count": crash_event_counts["quota_spend"],
                "scheduler_count": crash_event_counts["scheduler"],
                "recovery_host_invoked": resumed_payload["recovery"]["actual"][
                    "host_invoked"
                ],
                "claim_work_count": crash_commands.count("claim_work"),
            },
            "provider_unavailable": {
                "failed_closed_at_admission": True,
                "reason_code": unavailable_receipt["reason_code"],
                "host_count": 0,
            },
            "boundary": (
                "Protocol/effect checkpoints only; Host workspaces are isolated and "
                "this does not claim arbitrary workspace-effect exactly-once."
            ),
        }


def main() -> int:
    try:
        payload = run()
    except Exception as exc:  # noqa: BLE001 - canary emits compact failure
        payload = {
            "ok": False,
            "schema_version": "loopx_authority_turn_canary_v0",
            "error": type(exc).__name__,
            "message": str(exc),
        }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

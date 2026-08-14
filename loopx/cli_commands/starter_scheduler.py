from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..codex_cli_probe import (
    DEFAULT_CODEX_BIN,
    DEFAULT_EXECUTOR_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    load_codex_cli_visible_session_proof_fixture,
    render_codex_cli_local_scheduler_dispatch_markdown,
    render_codex_cli_local_scheduler_executor_markdown,
    render_codex_cli_local_scheduler_tick_markdown,
    run_codex_cli_session_probe,
)
from ..bootstrap import default_goal_id
from ..codex_cli_scheduler import (
    build_codex_cli_local_scheduler_executor,
    build_codex_cli_local_scheduler_tick,
)
from ..control_plane.scheduler.event_driven_dispatch import (
    EVENT_DRIVEN_DISPATCH_ENV,
    build_event_driven_dispatch,
    event_driven_dispatch_enabled,
)
from ..control_plane.scheduler.merge import merge_event_driven_and_heartbeat
from ..control_plane.scheduler.resident import (
    _loaded_items as _resident_loaded_items,
    run_resident_scheduler_bounded,
)
from ..paths import DEFAULT_RUNTIME_ROOT
from ..rollout_event_log import rollout_event_log_path
from .starter_runtime_idle import (
    _add_runtime_idle_observation_arguments,
    _load_codex_cli_runtime_idle_payload,
)


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]


def _add_scheduler_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default=".", help="Project directory to start from.")
    parser.add_argument("--goal-id", help="Goal id. Defaults to <project-name>-goal.")
    parser.add_argument(
        "--agent-id",
        help="Registered LoopX agent id to include in quota/claim instructions.",
    )
    parser.add_argument(
        "--cli-bin",
        default="loopx",
        help="LoopX CLI binary name embedded in generated commands.",
    )
    parser.add_argument(
        "--codex-bin",
        default=DEFAULT_CODEX_BIN,
        help="Codex CLI executable to probe for visible-session capabilities.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-command timeout for help-only Codex CLI probes.",
    )
    parser.add_argument(
        "--fixture",
        help="Public-safe JSON fixture with command_outputs, used instead of invoking Codex CLI.",
    )
    parser.add_argument(
        "--quota-fixture",
        help="Optional public-safe quota should-run JSON fixture with scheduler_hint.",
    )
    parser.add_argument(
        "--proof-fixture",
        help="Optional public-safe visible-session proof fixture. Without it, same-session automation remains blocked.",
    )
    _add_runtime_idle_observation_arguments(parser)
    parser.add_argument(
        "--allow-headless-fallback",
        action="store_true",
        help="Deprecated and ignored; headless codex exec is disabled for this default /goal path.",
    )


def register_starter_scheduler_commands(subparsers: argparse._SubParsersAction) -> None:
    codex_cli_local_scheduler_tick_parser = subparsers.add_parser(
        "codex-cli-local-scheduler-tick",
        help="Build a no-execution local scheduler tick around codex-cli-visible-driver-run.",
    )
    _add_scheduler_common_arguments(codex_cli_local_scheduler_tick_parser)

    codex_cli_local_scheduler_exec_parser = subparsers.add_parser(
        "codex-cli-local-scheduler-exec",
        help="Explicit opt-in executor wrapper for codex-cli-local-scheduler-tick results.",
    )
    _add_scheduler_common_arguments(codex_cli_local_scheduler_exec_parser)
    codex_cli_local_scheduler_exec_parser.add_argument(
        "--executor-timeout-seconds",
        type=float,
        default=DEFAULT_EXECUTOR_TIMEOUT_SECONDS,
        help="Timeout for the explicitly executed scheduler result command.",
    )
    codex_cli_local_scheduler_exec_parser.add_argument(
        "--guard-checked",
        action="store_true",
        help="Confirm a fresh quota/user-gate guard was checked before executing a candidate or blocker writeback.",
    )
    codex_cli_local_scheduler_exec_parser.add_argument(
        "--execute-candidate",
        action="store_true",
        help="Execute the scheduler candidate command after guard and prefix checks.",
    )
    codex_cli_local_scheduler_exec_parser.add_argument(
        "--execute-blocker-writeback",
        action="store_true",
        help="Execute the precise LoopX blocker writeback command after a fresh guard check.",
    )
    codex_cli_local_scheduler_exec_parser.add_argument(
        "--candidate-command-prefix",
        action="append",
        default=[],
        help="Allowed command prefix for --execute-candidate. Repeatable; required before candidate execution.",
    )

    codex_cli_local_scheduler_dispatch_parser = subparsers.add_parser(
        "codex-cli-local-scheduler-dispatch",
        help=(
            "RFC Phase 6 event-driven scheduling pilot: recompute READY successors "
            "from handoff gates, enqueue them, and optionally claim for a worker. "
            "Opt-in via --event-driven or LOOPX_EVENT_DRIVEN_DISPATCH=1; disabled by default."
        ),
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--project",
        default=".",
        help="Project directory to start from; used for the default goal id.",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--goal-id",
        help="Goal id. Defaults to <project-name>-goal.",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime root that contains goals/<goal-id>/events.jsonl. Defaults to the global runtime root.",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--completed-todo-id",
        help="Optional completed todo id that triggered this dispatch tick.",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--worker-id",
        help="Optional worker id to claim the next queued task (Worker Pool acquire).",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--agent-id",
        help=(
            "Optional registered LoopX agent id to record on the task_dispatched "
            "audit event (falls back to --worker-id when omitted)."
        ),
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--event-log-path",
        help="Override rollout event log path (default: goals/<goal-id>/rollout-event-log.jsonl).",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--event-driven",
        action="store_true",
        default=None,
        help="Enable event-driven dispatch for this tick (overrides env).",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--no-reconcile",
        action="store_true",
        default=False,
        help="Disable lease-expiry (zombie recovery) + retry promotion before claiming.",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--lease-seconds",
        type=float,
        default=None,
        help="Claim lease TTL in seconds; expired/unleased claims are reclaimed by reconcile.",
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--acceptance-criteria",
        action="append",
        default=[],
        metavar="ID=DESCRIPTION",
        help=(
            "Goal Acceptance criterion (repeatable). When supplied, dispatch runs the "
            "Goal Acceptance / Evidence Verification layer and closes the loop (emits "
            "goal_closure_ready + goal_closed) in a single tick instead of requiring a "
            "separate manual goal-closure --verify --apply."
        ),
    )
    codex_cli_local_scheduler_dispatch_parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        metavar="CRITERION_ID=KIND=REF",
        help=(
            "Evidence for an acceptance criterion (repeatable), e.g. "
            "yellow_bg=grep=index.html. KIND is one of grep|manual|file|command."
        ),
    )

    codex_cli_local_scheduler_resident_parser = subparsers.add_parser(
        "codex-cli-local-scheduler-resident",
        help=(
            "RFC Phase 5 resident scheduler: run the Task Queue + Worker Pool "
            "for a bounded number of ticks. Opt-in via --event-driven or "
            "LOOPX_EVENT_DRIVEN_DISPATCH=1; disabled by default."
        ),
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--project",
        default=".",
        help="Project directory to start from; used for the default goal id.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--goal-id",
        help="Goal id. Defaults to <project-name>-goal.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime root that contains goals/<goal-id>/events.jsonl.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--worker-id",
        action="append",
        default=[],
        help="Worker id for the pool. Repeatable; each becomes a claimer.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--agent-id",
        help=(
            "Optional registered LoopX agent id to record on task_dispatched "
            "audit events (falls back to the claimer worker id when omitted)."
        ),
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--completed-todo-id",
        help="Optional completed todo id that triggered this dispatch tick.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of resident ticks to run (bounded; 0 runs zero).",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--interval-seconds",
        type=float,
        default=0.0,
        help="Sleep between ticks (bounded runs only).",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--event-driven",
        action="store_true",
        default=None,
        help="Enable event-driven dispatch for this resident run (overrides env).",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--execute-worker-command",
        default=None,
        help=(
            "Optional shell command the worker runs after claiming a task "
            "(opt-in; only runs when --guard-checked and an allowed prefix match)."
        ),
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--worker-command-prefix",
        action="append",
        default=[],
        help="Allow-list prefix for the worker exec command. Repeatable.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--guard-checked",
        action="store_true",
        default=False,
        help="Confirm a fresh quota guard before worker exec (mirrors the original scheduler).",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--no-reconcile",
        action="store_true",
        default=False,
        help="Disable lease-expiry (zombie recovery) + retry promotion each tick.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--lease-seconds",
        type=float,
        default=None,
        help="Claim lease TTL in seconds; expired claims are re-enqueued (zombie recovery).",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--worker-capabilities",
        action="append",
        default=[],
        help="worker_id=cap1,cap2 capability declarations for capability-matched claiming. Repeatable.",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--control-plane-status",
        action="store_true",
        default=False,
        help="Also emit the P2 control-plane observability snapshot (scheduler/worker/queue/task/decision/event history).",
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--acceptance-criteria",
        action="append",
        default=[],
        help=(
            "Declare an acceptance criterion as criterion_id=description "
            "(repeatable). Closes the full loop: after worker execution, the goal "
            "is closed only if every criterion has satisfying evidence."
        ),
    )
    codex_cli_local_scheduler_resident_parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help=(
            "Declare evidence as criterion_id=kind=ref (repeatable). "
            "kind in {grep,snapshot,test,file,manual}. Closes the full loop."
        ),
    )

    codex_cli_local_scheduler_merge_parser = subparsers.add_parser(
        "codex-cli-local-scheduler-merge",
        help=(
            "RFC Phase 5 merged path: heartbeat event-source fact + PolicyEngine "
            "decision + event-driven dispatch in one tick. Requires "
            "LOOPX_MERGE_EVENT_DRIVEN_AND_HEARTBEAT=1; disabled by default."
        ),
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--project",
        default=".",
        help="Project directory to start from; used for the default goal id.",
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--goal-id",
        help="Goal id. Defaults to <project-name>-goal.",
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--agent-id",
        help="Optional registered LoopX agent id for the heartbeat observation fact.",
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--runtime-root",
        default=None,
        help="Runtime root that contains goals/<goal-id>/events.jsonl.",
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--completed-todo-id",
        help="Optional completed todo id that triggered this dispatch tick.",
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--worker-id",
        help="Optional worker/agent id to claim the next queued task.",
    )
    codex_cli_local_scheduler_merge_parser.add_argument(
        "--merge",
        action="store_true",
        default=None,
        help="Enable the merged path for this invocation (overrides env).",
    )


def handle_codex_cli_local_scheduler_tick_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    probe_payload = run_codex_cli_session_probe(
        codex_bin=args.codex_bin,
        timeout_seconds=args.timeout_seconds,
        fixture=Path(args.fixture).expanduser() if args.fixture else None,
    )
    proof_payload = (
        load_codex_cli_visible_session_proof_fixture(Path(args.proof_fixture).expanduser())
        if args.proof_fixture
        else None
    )
    idle_payload = _load_codex_cli_runtime_idle_payload(args)
    quota_payload = (
        json.loads(Path(args.quota_fixture).expanduser().read_text(encoding="utf-8"))
        if args.quota_fixture
        else None
    )
    payload = build_codex_cli_local_scheduler_tick(
        project=Path(args.project),
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        cli_bin=args.cli_bin,
        codex_bin=args.codex_bin,
        probe_payload=probe_payload,
        quota_payload=quota_payload,
        proof_payload=proof_payload,
        idle_payload=idle_payload,
        allow_headless_fallback=bool(args.allow_headless_fallback),
    )
    print_payload(payload, args.format, render_codex_cli_local_scheduler_tick_markdown)
    return 0 if payload.get("ok") else 1


def handle_codex_cli_local_scheduler_exec_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    probe_payload = run_codex_cli_session_probe(
        codex_bin=args.codex_bin,
        timeout_seconds=args.timeout_seconds,
        fixture=Path(args.fixture).expanduser() if args.fixture else None,
    )
    proof_payload = (
        load_codex_cli_visible_session_proof_fixture(Path(args.proof_fixture).expanduser())
        if args.proof_fixture
        else None
    )
    idle_payload = _load_codex_cli_runtime_idle_payload(args)
    quota_payload = (
        json.loads(Path(args.quota_fixture).expanduser().read_text(encoding="utf-8"))
        if args.quota_fixture
        else None
    )
    payload = build_codex_cli_local_scheduler_executor(
        project=Path(args.project),
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        cli_bin=args.cli_bin,
        codex_bin=args.codex_bin,
        probe_payload=probe_payload,
        quota_payload=quota_payload,
        proof_payload=proof_payload,
        idle_payload=idle_payload,
        allow_headless_fallback=bool(args.allow_headless_fallback),
        execute_candidate=bool(args.execute_candidate),
        execute_blocker_writeback=bool(args.execute_blocker_writeback),
        guard_checked=bool(args.guard_checked),
        candidate_command_prefixes=list(args.candidate_command_prefix or []),
        executor_timeout_seconds=args.executor_timeout_seconds,
    )
    print_payload(payload, args.format, render_codex_cli_local_scheduler_executor_markdown)
    return 0 if payload.get("ok") else 1


def handle_codex_cli_local_scheduler_dispatch_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else Path(
        DEFAULT_RUNTIME_ROOT
    )
    goal_id = args.goal_id or default_goal_id(Path(args.project).expanduser().resolve())
    event_log_path = (
        Path(args.event_log_path).expanduser()
        if args.event_log_path
        else rollout_event_log_path(runtime_root, goal_id)
    )
    # Load projected todo items from the dedicated events.jsonl state store when
    # present; otherwise fall back to reconstructing them from the rollout event
    # log (todo_add / todo_complete), which is the common shape for real goals.
    items, _ = _resident_loaded_items(runtime_root, goal_id)
    # Optional acceptance criteria + evidence close the full loop
    # (task_completed -> acceptance -> goal_closed) in one dispatch tick.
    acceptance_criteria = None
    for spec in getattr(args, "acceptance_criteria", None) or []:
        if "=" in spec:
            cid, _, desc = spec.partition("=")
            if acceptance_criteria is None:
                acceptance_criteria = []
            acceptance_criteria.append({"criterion_id": cid.strip(), "description": desc.strip()})
    evidence = None
    for spec in getattr(args, "evidence", None) or []:
        parts = spec.split("=")
        if len(parts) < 3:
            continue
        if evidence is None:
            evidence = []
        # ID=KIND=REF[=REGEX]. When REGEX is supplied the framework independently
        # greps REF for REGEX (relative to --project) instead of trusting `ok`.
        # A trailing ``!`` on KIND (e.g. ``grep!``) marks an *absence* check: the
        # criterion passes when REGEX is NOT found in REF.
        kind = parts[1].strip()
        expect = "present"
        if kind.endswith("!"):
            expect = "absent"
            kind = kind[:-1].strip()
        item: dict[str, Any] = {
            "criterion_ids": [parts[0].strip()],
            "kind": kind,
            "ref": parts[2].strip(),
            "ok": True,
            "expect": expect,
        }
        if len(parts) >= 4:
            item["pattern"] = parts[3].strip()
        if kind == "grep":
            # A grep evidence with a real regex is verified by the framework; the
            # self-reported `ok` is only a fallback when no pattern is given.
            item["ok"] = bool(item.get("pattern"))
        evidence.append(item)
    payload = build_event_driven_dispatch(
        runtime_root=runtime_root,
        goal_id=goal_id,
        items=items,
        completed_todo_id=args.completed_todo_id,
        event_log_path=event_log_path,
        worker_id=args.worker_id,
        agent_id=args.agent_id,
        use_event_driven=args.event_driven,
        reconcile=not bool(getattr(args, "no_reconcile", False)),
        worker_capabilities=None,
        lease_seconds=getattr(args, "lease_seconds", None),
        acceptance_criteria=acceptance_criteria,
        evidence=evidence,
        acceptance_base_dir=Path(args.project).expanduser().resolve()
        if args.project
        else None,
    )
    # When this dispatch tick derived goal closure (acceptance-satisfied), keep
    # the registry goal entry's status in lockstep with the rollout log so
    # `status`/registry and start-goal's guided packet agree the goal is closed.
    closure = (payload.get("event_driven_dispatch") or {}).get("closure") or {}
    if payload.get("ok") and closure.get("ready") and getattr(args, "project", None):
        try:
            from ..registry import sync_registry_goal_closed

            sync_registry_goal_closed(
                Path(args.project).expanduser().resolve() / ".loopx" / "registry.json",
                goal_id,
            )
        except Exception:
            pass
    print_payload(payload, args.format, render_codex_cli_local_scheduler_dispatch_markdown)
    return 0 if payload.get("ok") else 1


def handle_codex_cli_local_scheduler_resident_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else Path(
        DEFAULT_RUNTIME_ROOT
    )
    goal_id = args.goal_id or default_goal_id(Path(args.project).expanduser().resolve())
    worker_capabilities: dict[str, list[str]] = {}
    for spec in getattr(args, "worker_capabilities", None) or []:
        if "=" in spec:
            worker, _, caps = spec.partition("=")
            worker_capabilities[worker.strip()] = [
                c.strip() for c in caps.split(",") if c.strip()
            ]
    # Optional acceptance criteria + evidence close the full loop
    # (task_completed -> acceptance -> goal_closed).
    acceptance_criteria = None
    for spec in getattr(args, "acceptance_criteria", None) or []:
        if "=" in spec:
            cid, _, desc = spec.partition("=")
            if acceptance_criteria is None:
                acceptance_criteria = []
            acceptance_criteria.append({"criterion_id": cid.strip(), "description": desc.strip()})
    evidence = None
    for spec in getattr(args, "evidence", None) or []:
        parts = spec.split("=", 2)
        if len(parts) >= 3:
            if evidence is None:
                evidence = []
            evidence.append(
                {
                    "criterion_ids": [parts[0].strip()],
                    "kind": parts[1].strip(),
                    "ref": parts[2].strip(),
                    "ok": True,
                }
            )
    payload = run_resident_scheduler_bounded(
        runtime_root=runtime_root,
        goal_id=goal_id,
        worker_ids=list(args.worker_id or []),
        agent_id=args.agent_id,
        max_iterations=int(getattr(args, "iterations", 1)),
        interval_seconds=float(getattr(args, "interval_seconds", 0.0)),
        completed_todo_id=args.completed_todo_id,
        use_event_driven=args.event_driven,
        worker_exec_command=getattr(args, "execute_worker_command", None),
        worker_exec_command_prefixes=list(getattr(args, "worker_command_prefix", None) or []),
        guard_checked=bool(getattr(args, "guard_checked", False)),
        reconcile=not bool(getattr(args, "no_reconcile", False)),
        worker_capabilities=worker_capabilities or None,
        lease_seconds=getattr(args, "lease_seconds", None),
        acceptance_criteria=acceptance_criteria,
        evidence=evidence,
    )
    # P2 observability snapshot (read-only control-plane status).
    if getattr(args, "control_plane_status", False):
        from ..control_plane.status.control_plane_observability import (
            build_control_plane_status,
        )

        payload["control_plane_status"] = build_control_plane_status(
            runtime_root=runtime_root,
            goal_id=goal_id,
            worker_ids=list(args.worker_id or []),
            scheduler_tick_count=payload.get("tick_count"),
        )
    if args.format == "json":
        print_payload(payload, args.format, None)
        return 0 if payload.get("ok") else 1
    # Markdown: render the per-tick dispatch payload (the shared renderer reads a
    # flat ``event_driven_dispatch`` key), then append the resident summary.
    ticks = payload.get("ticks") or []
    if ticks:
        last = ticks[-1]
        if isinstance(last, dict) and isinstance(last.get("event_driven_dispatch"), dict):
            render_payload = {
                "ok": payload.get("ok"),
                "goal_id": goal_id,
                "event_driven_dispatch": last["event_driven_dispatch"],
            }
            print(render_codex_cli_local_scheduler_dispatch_markdown(render_payload))
    worker_executions = []
    if ticks and isinstance(ticks[-1].get("resident_scheduler"), dict):
        worker_executions = ticks[-1]["resident_scheduler"].get("worker_executions") or []
    print(
        "# Resident Scheduler\n\n"
        f"- ok: `{payload.get('ok')}`\n"
        f"- enabled: `{payload.get('enabled')}`\n"
        f"- goal_id: `{goal_id}`\n"
        f"- tick_count: `{payload.get('tick_count')}`"
    )
    if worker_executions:
        print("\n## Worker Executions")
        for entry in worker_executions:
            print(
                f"- `{entry.get('claimed_by') or '?'}` / {entry.get('todo_id') or '?'} "
                f"/ executed: `{entry.get('executed')}` / reason: `{entry.get('reason')}`"
            )
    if payload.get("control_plane_status"):
        status = payload["control_plane_status"]
        q = status.get("queue") or {}
        ex = q.get("extended") or {}
        print(
            "\n## Control-Plane Status (P2 observability)\n"
            f"- queue: pending `{q.get('pending_count', 0)}`, claimed "
            f"`{q.get('claimed_count', 0)}`, done `{q.get('done_count', 0)}`, "
            f"in-flight `{q.get('in_flight_count', 0)}`, exceptions "
            f"`{q.get('exception_count', 0)}`\n"
            f"- lifecycle: retry_wait `{ex.get('retry_wait_count', 0)}`, failed "
            f"`{ex.get('failed_count', 0)}`, dead_letter `{ex.get('dead_letter_count', 0)}`, "
            f"cancelled `{ex.get('cancelled_count', 0)}`\n"
            f"- workers: `{status.get('workers', {}).get('worker_count', 0)}` active\n"
            f"- events: `{status.get('event_history', {}).get('event_count', 0)}` recorded\n"
            f"- decisions: `{status.get('decision_history', {}).get('decision_count', 0)}` recorded"
        )
    if payload.get("finalize"):
        fin = payload["finalize"]
        acc = fin.get("acceptance") or {}
        gaps = acc.get("acceptance_gaps") or []
        print(
            "\n## Closed Loop (task_completed -> acceptance -> closure)\n"
            f"- tasks completed: `{len(fin.get('task_results') or [])}`\n"
            f"- acceptance satisfied: `{acc.get('satisfied')}`"
        )
        if gaps:
            print(
                "- acceptance gaps: `"
                + "`, `".join(str(g.get("criterion_id")) for g in gaps)
                + "`"
            )
        print(f"- goal closed: `{fin.get('closed')}`")
    return 0 if payload.get("ok") else 1


def handle_codex_cli_local_scheduler_merge_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else Path(
        DEFAULT_RUNTIME_ROOT
    )
    goal_id = args.goal_id or default_goal_id(Path(args.project).expanduser().resolve())
    payload = merge_event_driven_and_heartbeat(
        runtime_root=runtime_root,
        goal_id=goal_id,
        agent_id=args.agent_id,
        completed_todo_id=args.completed_todo_id,
        worker_id=args.worker_id,
        items=None,
        use_event_driven=None,
        use_event_source=None,
        use_merge=args.merge,
    )
    print_payload(payload, args.format, render_codex_cli_local_scheduler_dispatch_markdown)
    return 0 if payload.get("ok") else 1


_SCHEDULER_HANDLERS: dict[str, Callable[[argparse.Namespace, PrintPayload], int]] = {
    "codex-cli-local-scheduler-tick": handle_codex_cli_local_scheduler_tick_command,
    "codex-cli-local-scheduler-exec": handle_codex_cli_local_scheduler_exec_command,
    "codex-cli-local-scheduler-dispatch": handle_codex_cli_local_scheduler_dispatch_command,
    "codex-cli-local-scheduler-resident": handle_codex_cli_local_scheduler_resident_command,
    "codex-cli-local-scheduler-merge": handle_codex_cli_local_scheduler_merge_command,
}


def handle_starter_scheduler_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int | None:
    handler = _SCHEDULER_HANDLERS.get(str(getattr(args, "command", "")))
    if handler is None:
        return None
    return handler(args, print_payload)

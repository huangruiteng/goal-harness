from __future__ import annotations

import argparse
import shlex
from collections.abc import Callable
from pathlib import Path

from ..control_plane.runtime.agent_scoped_evidence_log import (
    build_agent_scoped_evidence_log,
    build_agent_scoped_evidence_log_command,
    evidence_log_read_receipt,
    goal_history_runs,
)
from ..history import collect_history, load_registry
from ..paths import resolve_runtime_root
from ..rollout_event_log import load_rollout_events, rollout_event_log_path


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
RolloutEventAppender = Callable[..., dict[str, object]]


def _evidence_log_receipt_command(args: argparse.Namespace) -> str:
    parts = shlex.split(
        build_agent_scoped_evidence_log_command(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=args.todo_id,
            limit=max(0, int(args.limit)),
            required_read_id=args.required_read_id,
        )
    )
    if int(args.history_limit) != 80:
        parts.extend(["--history-limit", str(max(0, int(args.history_limit)))])
    if int(args.rollout_limit) != 400:
        parts.extend(["--rollout-limit", str(max(0, int(args.rollout_limit)))])
    if args.since:
        parts.extend(["--since", str(args.since)])
    for event_kind in args.event_kind:
        parts.extend(["--event-kind", str(event_kind)])
    return " ".join(shlex.quote(part) for part in parts)


def _evidence_log_receipt_details(
    args: argparse.Namespace,
    *,
    command: str,
) -> dict[str, object]:
    return {
        "command": command,
        "mode": "thin",
        "limit": max(0, int(args.limit)),
        "history_limit": max(0, int(args.history_limit)),
        "rollout_limit": max(0, int(args.rollout_limit)),
        "since": str(args.since or ""),
        "event_kinds": ",".join(
            str(kind).strip().lower().replace("-", "_")
            for kind in args.event_kind
            if str(kind).strip()
        ),
        "required_read_id": str(args.required_read_id or ""),
    }


def register_evidence_log_command(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "evidence-log",
        help="Read a public-safe, agent-scoped evidence ledger for replan and handoff.",
    )
    add_subcommand_format(parser)
    parser.add_argument("--goal-id", required=True, help="Goal id whose evidence should be read.")
    parser.add_argument(
        "--agent-id",
        required=True,
        help="Registered agent id. The ledger expands only this agent's event stream.",
    )
    parser.add_argument("--todo-id", help="Optional todo id filter for the current replan/work slice.")
    parser.add_argument("--since", help="Optional ISO timestamp lower bound.")
    parser.add_argument(
        "--required-read-id",
        help="Opaque projected required-read identity recorded on the durable receipt.",
    )
    parser.add_argument(
        "--event-kind",
        action="append",
        default=[],
        help="Optional rollout event kind filter. Repeatable.",
    )
    parser.add_argument("--limit", type=int, default=24, help="Maximum merged ledger rows to return.")
    parser.add_argument(
        "--history-limit",
        type=int,
        default=80,
        help="Maximum compact run-history rows to scan before agent/todo filtering.",
    )
    parser.add_argument(
        "--rollout-limit",
        type=int,
        default=400,
        help="Maximum rollout-event rows to scan from the tail before filtering.",
    )
    parser.add_argument(
        "--thin",
        action="store_true",
        help="Return the thin public-safe shape. This is the only current mode and is accepted for clarity.",
    )


def render_evidence_log_markdown(payload: dict[str, object]) -> str:
    if not payload.get("ok"):
        return "\n".join(
            [
                "# LoopX Evidence Log",
                "",
                f"- ok: `{payload.get('ok')}`",
                f"- error: `{payload.get('error')}`",
                "",
            ]
        )
    lines = [
        "# LoopX Evidence Log",
        "",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- agent_id: `{payload.get('agent_id')}`",
        f"- todo_id: `{payload.get('todo_id') or ''}`",
        f"- mode: `{payload.get('mode')}`",
        f"- rollout_events: `{payload.get('rollout_event_count')}`",
        f"- run_history_refs: `{payload.get('run_history_ref_count')}`",
        f"- ledger_count: `{payload.get('ledger_count')}`",
        f"- matched_count: `{payload.get('matched_count')}`",
        f"- truncated: `{payload.get('truncated')}`",
        "",
        "## Ledger",
        "",
    ]
    ledger = payload.get("ledger") if isinstance(payload.get("ledger"), list) else []
    if not ledger:
        lines.append("- No matching public-safe evidence rows.")
    for row in ledger:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "unknown")
        when = str(row.get("recorded_at") or "")
        if source == "rollout_event_log":
            title = str(row.get("event_kind") or "event")
            suffix = str(row.get("status") or row.get("classification") or "")
        else:
            title = str(row.get("classification") or "run")
            suffix = str(row.get("delivery_outcome") or row.get("progress_scope") or "")
        summary = str(row.get("summary") or row.get("recommended_action") or row.get("health_check") or "")
        line = f"- `{when}` `{source}` {title}"
        if suffix:
            line += f" ({suffix})"
        if summary:
            line += f": {summary}"
        lines.append(line)
    frontier = payload.get("other_agent_frontier") if isinstance(payload.get("other_agent_frontier"), dict) else {}
    items = frontier.get("items") if isinstance(frontier.get("items"), list) else []
    if items:
        lines.extend(["", "## Other Agent Frontier", ""])
        for item in items:
            if not isinstance(item, dict):
                continue
            agent = str(item.get("agent_id") or "")
            classification = str(item.get("classification") or "latest run")
            lines.append(f"- `{agent}`: {classification}")
    lines.append("")
    return "\n".join(lines)


def handle_evidence_log_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
    append_cli_rollout_event: RolloutEventAppender,
) -> int | None:
    if args.command != "evidence-log":
        return None
    try:
        registry = load_registry(registry_path)
        runtime_root = resolve_runtime_root(registry, runtime_root_arg)
        rollout_events = load_rollout_events(
            rollout_event_log_path(runtime_root, args.goal_id),
            limit=max(0, int(args.rollout_limit)),
        )
        history_payload = collect_history(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=args.goal_id,
            limit=max(0, int(args.history_limit)),
        )
        payload = build_agent_scoped_evidence_log(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=args.todo_id,
            since=args.since,
            event_kinds=args.event_kind,
            limit=max(0, int(args.limit)),
            rollout_events=rollout_events,
            history_runs=goal_history_runs(history_payload, args.goal_id),
        )
        command = _evidence_log_receipt_command(args)
        receipt_details = _evidence_log_receipt_details(args, command=command)
        append_cli_rollout_event(
            payload,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            event_kind="evidence_log_read",
            agent_id=args.agent_id,
            todo_id=args.todo_id,
            status="completed",
            summary="read the bounded agent-scoped evidence ledger",
            details=receipt_details,
        )
        event_view = payload.get("rollout_event")
        if isinstance(event_view, dict):
            receipt = evidence_log_read_receipt(
                {
                    **event_view,
                    "goal_id": args.goal_id,
                    "agent_id": args.agent_id,
                    "todo_id": args.todo_id,
                    "details": receipt_details,
                }
            )
            if receipt:
                payload["read_receipt"] = receipt
                payload.pop("rollout_event", None)
        if "read_receipt" not in payload:
            payload["ok"] = False
            payload["error"] = (
                "evidence log was read but its durable read receipt could not be recorded"
            )
    except Exception as exc:
        try:
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(registry, runtime_root_arg)
            command = _evidence_log_receipt_command(args)
            details = _evidence_log_receipt_details(args, command=command)
            details["error"] = str(exc)
            append_cli_rollout_event(
                {"ok": False},
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                event_kind="evidence_log_read",
                agent_id=args.agent_id,
                todo_id=args.todo_id,
                status="failed",
                summary="evidence log read failed",
                details=details,
            )
        except Exception:
            # The failure receipt is a best-effort escape hatch; never mask the
            # original read error.
            pass
        payload = {
            "ok": False,
            "schema_version": "agent_scoped_evidence_log_v0",
            "goal_id": getattr(args, "goal_id", None),
            "agent_id": getattr(args, "agent_id", None),
            "error": str(exc),
        }
    selected_format = output_format(args)
    print_payload(payload, selected_format, render_evidence_log_markdown)
    return 0 if payload.get("ok") else 1

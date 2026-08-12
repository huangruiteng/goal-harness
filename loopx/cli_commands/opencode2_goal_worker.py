from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from collections.abc import Callable

from ..opencode2_goal_mode import worker_source

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]


def _materialized_worker_path() -> Path:
    cache_root = Path(tempfile.gettempdir()) / "loopx" / "opencode2-goal-worker"
    cache_root.mkdir(parents=True, exist_ok=True)
    target = cache_root / "opencode2-goal-worker.mjs"
    content = worker_source()
    try:
        if target.read_text(encoding="utf-8") == content:
            return target
    except OSError:
        pass
    temporary = cache_root / f"opencode2-goal-worker.mjs.{__import__('os').getpid()}.tmp"
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(target)
    return target


def register_opencode2_goal_worker_command(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "opencode2-goal-worker",
        help=(
            "Drive an OpenCode 2 session as a persistent LoopX goal loop: "
            "quota-gated continuation, backoff waits, and visible stop/pause notices."
        ),
    )
    parser.add_argument("--goal-id", required=True, help="LoopX goal id.")
    parser.add_argument(
        "--directory",
        required=True,
        help="Project directory for the OpenCode 2 session and quota probes.",
    )
    parser.add_argument("--agent-id", help="LoopX agent id to scope quota decisions.")
    parser.add_argument("--registry", help="LoopX registry path.")
    parser.add_argument(
        "--capability",
        action="append",
        default=[],
        help="Declared host capability (repeatable).",
    )
    parser.add_argument(
        "--session-id",
        help="Attach to an existing OpenCode 2 session instead of creating one.",
    )
    parser.add_argument(
        "--task-body",
        help="Initial task text; only used for the first prompt of a new session.",
    )
    parser.add_argument("--max-turns", type=int, help="Turn budget (default 10000).")
    parser.add_argument(
        "--max-duration-minutes",
        type=float,
        help="Duration budget in minutes (default 43200 = 30 days).",
    )
    parser.add_argument(
        "--force-resume",
        action="store_true",
        help="Restart the loop even when worker state is paused.",
    )
    parser.add_argument(
        "--state-dir",
        help="Override the worker state directory.",
    )
    return parser


def handle_opencode2_goal_worker_command(
    args: argparse.Namespace, print_payload: PrintPayload
) -> int:
    worker_path = _materialized_worker_path()
    node_args = [
        "node",
        str(worker_path),
        "--goal-id",
        args.goal_id,
        "--directory",
        args.directory,
    ]
    if args.agent_id:
        node_args += ["--agent-id", args.agent_id]
    if args.registry:
        node_args += ["--registry", args.registry]
    for capability in args.capability or []:
        node_args += ["--capability", capability]
    if args.session_id:
        node_args += ["--session-id", args.session_id]
    if args.task_body:
        node_args += ["--task-body", args.task_body]
    if args.max_turns:
        node_args += ["--max-turns", str(args.max_turns)]
    if args.max_duration_minutes:
        node_args += ["--max-duration-minutes", str(args.max_duration_minutes)]
    if args.force_resume:
        node_args.append("--force-resume")
    if args.state_dir:
        node_args += ["--state-dir", args.state_dir]

    try:
        completed = subprocess.run(
            node_args,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        payload = {
            "ok": False,
            "schema_version": "loopx_opencode2_worker_error_v0",
            "error_kind": "node_unavailable",
            "reason": "node is required to run the OpenCode 2 goal worker.",
        }
        print_payload(payload, args.format, _render_worker_markdown)
        return 1
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    payload: dict[str, object] = {
        "ok": completed.returncode == 0,
        "schema_version": "loopx_opencode2_worker_result_v0",
        "operation": "opencode2_goal_worker",
        "exit_code": completed.returncode,
    }
    try:
        parsed = json.loads(stdout) if stdout else None
        if isinstance(parsed, dict):
            payload.update(parsed)
    except json.JSONDecodeError:
        payload["raw_stdout"] = stdout[-800:]
    if stderr:
        payload["worker_log_tail"] = stderr[-1200:]
    print_payload(payload, args.format, _render_worker_markdown)
    return completed.returncode


def _render_worker_markdown(payload: dict[str, object]) -> str:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    kind = result.get("kind", "error")
    lines = [
        "# LoopX OpenCode 2 goal worker",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- exit_code: `{payload.get('exit_code')}`",
        f"- outcome: `{kind}`",
    ]
    if payload.get("worker_log_tail"):
        lines += ["", "## Worker log tail", "```", str(payload["worker_log_tail"]), "```"]
    return "\n".join(lines)

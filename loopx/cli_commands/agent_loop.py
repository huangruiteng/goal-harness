from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..control_plane.agent_loop import build_agent_loop_shadow_tick
from ..control_plane.quota.live_decision import build_live_quota_should_run_decision
from ..control_plane.quota.turn_envelope import build_turn_envelope
from ..control_plane.runtime.status_projection_cache import (
    resolve_status_projection_cache_runtime_root,
)
from ..status import AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK, collect_status


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _default_public_scan_root() -> str:
    return str(Path(__file__).resolve().parents[2])


def register_agent_loop_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "agent-loop",
        help="Preview host-neutral agent-loop routing from a live LoopX decision.",
    )
    command_sub = parser.add_subparsers(dest="agent_loop_command", required=True)
    shadow_tick = command_sub.add_parser(
        "shadow-tick",
        help="Build one typed read-only host decision without launching or writing.",
    )
    add_subcommand_format(shadow_tick)
    shadow_tick.add_argument("--goal-id", required=True)
    shadow_tick.add_argument("--agent-id", required=True)
    shadow_tick.add_argument(
        "--host",
        choices=["codex-cli", "claude-code", "generic-cli"],
        default="codex-cli",
    )
    shadow_tick.add_argument(
        "--execution-mode",
        choices=["interactive-visible", "isolated-headless"],
        default="interactive-visible",
    )
    shadow_tick.add_argument(
        "--available-capability",
        dest="available_capabilities",
        action="append",
    )
    shadow_tick.add_argument(
        "--scan-root",
        default=_default_public_scan_root(),
        help="Public files to scan for obvious private material.",
    )
    shadow_tick.add_argument(
        "--scan-path",
        action="append",
        default=[],
        help="Specific public file or directory to scan. Repeatable.",
    )
    shadow_tick.add_argument("--limit", type=int, default=5)


def _render_agent_loop_shadow_markdown(payload: dict[str, object]) -> str:
    if not payload.get("ok"):
        error = payload.get("error") or "invalid TurnEnvelope contract"
        return f"LoopX agent-loop shadow tick failed: {error}"
    host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    return "\n".join(
        [
            "# LoopX Agent-Loop Shadow Tick",
            f"- host: {host.get('kind')}",
            f"- execution_mode: {host.get('execution_mode')}",
            f"- route: {route.get('kind')}",
            f"- would_invoke_host: {route.get('would_invoke_host')}",
            "- side_effects: none",
        ]
    )


def handle_agent_loop_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "agent-loop":
        return None
    try:
        if args.agent_loop_command != "shadow-tick":
            raise ValueError("agent-loop requires the `shadow-tick` subcommand")
        scan_roots = [Path(item).expanduser() for item in args.scan_path]
        if not scan_roots:
            scan_roots = [Path(args.scan_root).expanduser()]
        runtime_root = resolve_status_projection_cache_runtime_root(
            registry_path=registry_path,
            runtime_root_override=runtime_root_arg,
        )
        status_payload = collect_status(
            registry_path=registry_path,
            runtime_root_override=runtime_root_arg,
            scan_roots=scan_roots,
            limit=max(max(0, args.limit), AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK),
        )
        decision = build_live_quota_should_run_decision(
            status_payload,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            available_capabilities=args.available_capabilities,
            include_scheduler_detail=False,
            codex_app_current_rrule=None,
            registry_path=registry_path,
            runtime_root=runtime_root,
            route_source="agent_loop_shadow_tick",
        )
        payload = build_agent_loop_shadow_tick(
            build_turn_envelope(decision),
            host=args.host,
            execution_mode=args.execution_mode,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "schema_version": "agent_loop_shadow_tick_v0",
            "mode": "shadow",
            "error": str(exc),
            "effects": {
                "host_invoked": False,
                "state_written": False,
                "scheduler_acknowledged": False,
                "quota_spent": False,
            },
        }
    print_payload(payload, output_format(args), _render_agent_loop_shadow_markdown)
    return 0 if payload.get("ok") else 1

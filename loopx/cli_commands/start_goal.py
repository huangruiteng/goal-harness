from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from pathlib import Path

from ..bootstrap_command_pack import (
    START_GOAL_CAPABILITY_ROUTES,
    START_GOAL_HOST_SURFACES,
    build_start_goal_guided_packet,
    build_start_goal_host_surface_selection_packet,
    render_start_goal_guided_markdown,
)
from ._host_thread import current_host_thread_id

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]

_CAPABILITY_ROUTE_SWITCH = "--capability-route"
_FINE_GRAINED_SWITCH = "--fine-grained"
_CAPABILITY_ROUTE_PREFIX = re.compile(
    r"\A--capability-route(?:=(?P<equals>\S+)|\s+(?P<spaced>\S+))"
    r"(?P<remainder>[\s\S]*)\Z"
)
_FINE_GRAINED_PREFIX = re.compile(r"\A--fine-grained(?P<remainder>(?:\s[\s\S]*)?)\Z")


def add_capability_route_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--capability-route",
        choices=START_GOAL_CAPABILITY_ROUTES,
        help=(
            "Explicit product capability route for this goal start. Goal text never "
            "selects a capability route."
        ),
    )


def register_start_goal_command(subparsers: argparse._SubParsersAction) -> None:
    start_goal_parser = subparsers.add_parser(
        "start-goal",
        help="Preview a guided /loopx <goal text> start transaction without mutating state.",
    )
    start_goal_parser.add_argument(
        "--guided",
        action="store_true",
        help="Required for now: render the guided dry-run transaction packet.",
    )
    start_goal_parser.add_argument("--project", default=".", help="Project directory to inspect.")
    start_goal_parser.add_argument("--goal-id", help="Goal id. Defaults to <project-name>-goal.")
    start_goal_parser.add_argument(
        "--agent-id",
        help=(
            "Explicit registered LoopX identity for an ongoing session or exact "
            "user-requested takeover. When omitted, a bound thread identity is reused "
            "when available; otherwise new onboarding defaults to fresh registration."
        ),
    )
    start_goal_parser.add_argument(
        "--thread-id",
        help=(
            "Stable opaque host thread id used to reuse the bound agent lane. "
            "Codex App defaults to the ambient CODEX_THREAD_ID when available."
        ),
    )
    start_goal_parser.add_argument(
        "--new-peer",
        action="store_true",
        help="Explicitly request a fresh agent identity for this host thread.",
    )
    start_goal_parser.add_argument(
        "--cli-bin",
        default="loopx",
        help="LoopX CLI binary name embedded in generated commands.",
    )
    start_goal_parser.add_argument(
        "--host-surface",
        choices=START_GOAL_HOST_SURFACES,
        help=(
            "Exact host surface that will own loop activation after todo writeback. "
            "When omitted, start-goal returns a read-only host selection gate."
        ),
    )
    start_goal_parser.add_argument(
        "--available-capability",
        dest="available_capabilities",
        action="append",
        help="Capability available in this host loop. Repeat for multiple capabilities.",
    )
    add_capability_route_argument(start_goal_parser)
    start_goal_parser.add_argument(
        "--fine-grained",
        action="store_true",
        help=(
            "Persist fine-grained planning for this goal: small verifiable checkpoint "
            "Todos executed in coherent evidence-driven turn slices."
        ),
    )
    goal_input_group = start_goal_parser.add_mutually_exclusive_group(required=True)
    goal_input_group.add_argument(
        "--goal-text",
        help="Exact goal text to plan before todo writeback.",
    )
    goal_input_group.add_argument(
        "--slash-command-arguments",
        help=(
            "Complete visible /loopx arguments. The CLI consumes only an optional "
            "leading --fine-grained and --capability-route switches and treats the "
            "remainder as goal text. "
            "Use --slash-command-arguments='<arguments>' when the value begins with --."
        ),
    )
    start_goal_parser.add_argument(
        "--include-command-pack-detail",
        action="store_true",
        help=(
            "Include the complete nested bootstrap command pack. The default guided "
            "projection keeps the actionable transaction and advertises this cold path."
        ),
    )


def _resolve_start_goal_input(args: argparse.Namespace) -> tuple[str, str | None, bool]:
    raw_arguments = getattr(args, "slash_command_arguments", None)
    capability_route = getattr(args, "capability_route", None)
    fine_grained = bool(getattr(args, "fine_grained", False))
    if raw_arguments is None:
        return str(args.goal_text), capability_route, fine_grained
    if capability_route is not None:
        raise ValueError(
            "--slash-command-arguments cannot be combined with --capability-route; "
            "the raw argument string already owns the optional route switch"
        )
    if fine_grained:
        raise ValueError(
            "--slash-command-arguments cannot be combined with --fine-grained; "
            "the raw argument string already owns leading switches"
        )

    normalized = str(raw_arguments).strip()
    if not normalized:
        raise ValueError("--slash-command-arguments must contain goal text")
    route = None
    parsed_fine_grained = False
    last_switch = None
    remainder = normalized
    while True:
        if remainder.startswith(_FINE_GRAINED_SWITCH):
            match = _FINE_GRAINED_PREFIX.fullmatch(remainder)
            if match is None:
                raise ValueError(
                    "malformed leading --fine-grained in --slash-command-arguments"
                )
            if parsed_fine_grained:
                raise ValueError("duplicate leading --fine-grained switch")
            parsed_fine_grained = True
            last_switch = _FINE_GRAINED_SWITCH
            remainder = str(match.group("remainder") or "").strip()
            continue
        if remainder.startswith(_CAPABILITY_ROUTE_SWITCH):
            match = _CAPABILITY_ROUTE_PREFIX.fullmatch(remainder)
            if match is None:
                raise ValueError(
                    "malformed leading --capability-route in --slash-command-arguments"
                )
            if route is not None:
                raise ValueError("duplicate leading --capability-route switch")
            route = str(match.group("equals") or match.group("spaced") or "")
            last_switch = _CAPABILITY_ROUTE_SWITCH
            if route not in START_GOAL_CAPABILITY_ROUTES:
                raise ValueError(
                    "unsupported --capability-route; expected one of: "
                    + ", ".join(START_GOAL_CAPABILITY_ROUTES)
                )
            remainder = str(match.group("remainder") or "").strip()
            continue
        break
    goal_text = remainder
    if not goal_text:
        if last_switch == _CAPABILITY_ROUTE_SWITCH:
            raise ValueError(
                "--slash-command-arguments must contain goal text after --capability-route"
            )
        raise ValueError(
            "--slash-command-arguments must contain goal text after --fine-grained"
        )
    return goal_text, route, parsed_fine_grained


def handle_start_goal_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    if not bool(getattr(args, "guided", False)):
        payload = {
            "ok": False,
            "schema_version": "loopx_start_goal_guided_v0",
            "error": "`loopx start-goal` currently requires --guided",
            "suggested_command": "loopx start-goal --guided --goal-text '<goal text>'",
        }
        print_payload(payload, args.format, render_start_goal_guided_markdown)
        return 2
    try:
        goal_text, capability_route, fine_grained = _resolve_start_goal_input(args)
    except ValueError as exc:
        payload = {
            "ok": False,
            "schema_version": "loopx_start_goal_guided_v0",
            "error": str(exc),
            "suggested_command": (
                "loopx start-goal --guided "
                "--slash-command-arguments='<exact /loopx arguments>'"
            ),
        }
        print_payload(payload, args.format, render_start_goal_guided_markdown)
        return 2
    if not args.host_surface:
        payload = build_start_goal_host_surface_selection_packet(
            project=Path(args.project),
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            thread_id=current_host_thread_id(args),
            new_peer=bool(getattr(args, "new_peer", False)),
            cli_bin=args.cli_bin,
            goal_text=goal_text,
            available_capabilities=args.available_capabilities,
            capability_route=capability_route,
            fine_grained=fine_grained,
            include_command_pack_detail=bool(args.include_command_pack_detail),
        )
        print_payload(payload, args.format, render_start_goal_guided_markdown)
        return 0
    payload = build_start_goal_guided_packet(
        project=Path(args.project),
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        thread_id=current_host_thread_id(args),
        new_peer=bool(getattr(args, "new_peer", False)),
        cli_bin=args.cli_bin,
        host_surface=args.host_surface,
        goal_text=goal_text,
        available_capabilities=args.available_capabilities,
        capability_route=capability_route,
        fine_grained=fine_grained,
        include_command_pack_detail=bool(args.include_command_pack_detail),
    )
    print_payload(payload, args.format, render_start_goal_guided_markdown)
    return 0

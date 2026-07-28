from __future__ import annotations

import argparse
from collections.abc import Callable

from ..presets import (
    PRESET_IDS,
    build_beginner_preset_packet,
    render_beginner_preset_markdown,
)


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _add_preset_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cli-bin",
        default="loopx",
        help="LoopX CLI binary name to show in rendered commands.",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="Project path to show in the start-goal fallback command.",
    )
    parser.add_argument(
        "--goal-id",
        default="<goal-id>",
        help="Goal id placeholder or concrete goal id to show in follow-up commands.",
    )
    parser.add_argument(
        "--agent-id",
        default="<agent-id>",
        help="Agent id placeholder or concrete registered agent id to show in follow-up commands.",
    )
    parser.add_argument(
        "--agent-scope",
        default="<agent-scope>",
        help="Agent scope placeholder or concrete scope text to show in heartbeat commands.",
    )


def register_preset_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddFormat,
) -> None:
    preset_parser = subparsers.add_parser(
        "preset",
        help="List beginner LoopX presets and render safe start packets.",
    )
    preset_sub = preset_parser.add_subparsers(dest="preset_command", required=True)

    list_parser = preset_sub.add_parser(
        "list",
        help="List beginner presets with copyable LoopX start and heartbeat commands.",
    )
    add_subcommand_format(list_parser)
    _add_preset_runtime_args(list_parser)

    show_parser = preset_sub.add_parser(
        "show",
        help="Show one beginner preset with its exact start packet.",
    )
    add_subcommand_format(show_parser)
    show_parser.add_argument(
        "preset_id",
        choices=PRESET_IDS,
        help="Beginner preset id to render.",
    )
    _add_preset_runtime_args(show_parser)


def handle_preset_command(
    args: argparse.Namespace,
    *,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "preset":
        return None
    payload = build_beginner_preset_packet(
        preset_id=getattr(args, "preset_id", None),
        cli_bin=args.cli_bin,
        project=args.project,
        goal_id=args.goal_id,
        agent_id=args.agent_id,
        agent_scope=args.agent_scope,
    )
    print_payload(payload, output_format(args), render_beginner_preset_markdown)
    return 0

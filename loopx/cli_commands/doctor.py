from __future__ import annotations

import argparse
from collections.abc import Callable

from ..doctor import collect_doctor, render_doctor_markdown
from ..host_loop_activation import SUPPORTED_AGENT_TYPES


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
AddFormat = Callable[[argparse.ArgumentParser], None]


def register_doctor_command(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddFormat,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "doctor",
        help="Diagnose local CLI installation, PATH, wrapper, and import health.",
    )
    add_subcommand_format(parser)
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Run slower representative release-candidate checks.",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--installation-only",
        action="store_true",
        help="Check the installed package and toolchain without inspecting user projects or integrations.",
    )
    scope.add_argument(
        "--agent-type",
        choices=SUPPORTED_AGENT_TYPES,
        help=(
            "Evaluate host-specific integration checks. For other-agent, custom-host "
            "skill delivery replaces the Codex skill-directory check."
        ),
    )
    return parser


def handle_doctor_command(args: argparse.Namespace, print_payload: PrintPayload) -> int:
    payload = collect_doctor(
        deep=bool(args.deep),
        agent_type=args.agent_type,
        installation_only=bool(getattr(args, "installation_only", False)),
    )
    output_format = getattr(args, "subcommand_format", None) or args.format
    print_payload(payload, output_format, render_doctor_markdown)
    return 0 if payload.get("ok") else 1

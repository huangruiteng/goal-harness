from __future__ import annotations

import argparse
from collections.abc import Callable

from .project_skill_delivery import (
    PROJECT_SKILL_SURFACES,
    install_project_skill,
    inspect_project_skill,
    uninstall_project_skill,
)

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _render(payload: dict[str, object]) -> str:
    lines = [
        "# LoopX Project Skill",
        "",
        f"- skill_id: `{payload.get('skill_id')}`",
        f"- status: `{payload.get('status')}`",
        f"- mode: `{payload.get('mode') or 'inspect'}`",
        f"- project_connected: `{payload.get('project_connected')}`",
        f"- changed: `{payload.get('changed')}`",
    ]
    surface_items = payload.get("surfaces")
    for item in surface_items if isinstance(surface_items, list) else []:
        if isinstance(item, dict):
            lines.append(
                f"- {item.get('surface')}: `{item.get('status')}` at `{item.get('target')}`"
            )
    if payload.get("error"):
        lines.append(f"- error: `{payload.get('error')}`")
    return "\n".join([*lines, ""])


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default=".")
    parser.add_argument("--skill", required=True)
    parser.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
        help="Repeat to install the same managed skill for multiple agent hosts.",
    )


def register_project_skill_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "project-skill",
        help="Manage release-owned skills in project-local agent host directories.",
    )
    commands = parser.add_subparsers(
        dest="project_skill_command",
        required=True,
    )
    status = commands.add_parser("status", help="Inspect managed project skill copies.")
    _add_common_arguments(status)
    add_subcommand_format(status)
    install = commands.add_parser(
        "install",
        help="Preview or install managed project skill copies.",
    )
    _add_common_arguments(install)
    install.add_argument("--execute", action="store_true")
    add_subcommand_format(install)
    uninstall = commands.add_parser(
        "uninstall",
        help="Preview or uninstall managed project skill copies.",
    )
    _add_common_arguments(uninstall)
    uninstall.add_argument("--execute", action="store_true")
    add_subcommand_format(uninstall)


def handle_project_skill_command(
    args: argparse.Namespace,
    *,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "project-skill":
        return None
    surfaces = tuple(args.surface or ("codex",))
    try:
        if args.project_skill_command == "status":
            payload = inspect_project_skill(
                args.project,
                args.skill,
                surfaces=surfaces,
            )
        elif args.project_skill_command == "install":
            payload = install_project_skill(
                args.project,
                args.skill,
                surfaces=surfaces,
                execute=args.execute,
            )
        else:
            payload = uninstall_project_skill(
                args.project,
                args.skill,
                surfaces=surfaces,
                execute=args.execute,
            )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "status": "blocked",
            "skill_id": args.skill,
            "error": str(exc),
            "surfaces": [],
        }
        print_payload(payload, output_format(args), _render)
        return 2
    print_payload(payload, output_format(args), _render)
    return 0

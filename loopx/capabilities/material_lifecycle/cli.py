from __future__ import annotations

import argparse
from collections.abc import Callable, Collection

from loopx.project_skill_delivery import PROJECT_SKILL_SURFACES

from .architecture import build_material_lifecycle_architecture_packet
from .project_skill import (
    install_project_material_skill,
    inspect_project_material_skill,
    uninstall_project_material_skill,
)

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _collection_size(value: object) -> int:
    if isinstance(value, Collection) and not isinstance(value, (str, bytes)):
        return len(value)
    return 0


def _render(payload: dict[str, object]) -> str:
    if payload.get("skill_id") == "loopx-material":
        lines = [
            "# LoopX Material Project Skill",
            "",
            f"- status: `{payload.get('status')}`",
            f"- mode: `{payload.get('mode') or 'inspect'}`",
            f"- project_connected: `{payload.get('project_connected')}`",
            f"- managed: `{payload.get('managed')}`",
            f"- changed: `{payload.get('changed')}`",
        ]
        surface_items = payload.get("surfaces")
        for item in surface_items if isinstance(surface_items, list) else []:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('surface')}: `{item.get('status')}` at "
                    f"`{item.get('target')}`"
                )
        if payload.get("error"):
            lines.append(f"- error: `{payload.get('error')}`")
        return "\n".join([*lines, ""])
    capability = payload.get("capability")
    capability_id = (
        capability.get("capability_id")
        if isinstance(capability, dict)
        else "material_lifecycle"
    )
    return "\n".join(
        [
            "# Material Lifecycle",
            "",
            f"- status: `{payload.get('status')}`",
            f"- capability_id: `{capability_id}`",
            f"- contract_schemas: `{_collection_size(payload.get('contract_schemas'))}`",
            "",
        ]
    )


def register_material_lifecycle_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "material-lifecycle",
        help="Inspect the backup-safe material inventory and rerank contract.",
    )
    commands = parser.add_subparsers(
        dest="material_lifecycle_command",
        required=True,
    )
    architecture = commands.add_parser(
        "architecture",
        help="Render the default-off Stage-0 Material Lifecycle contract.",
    )
    add_subcommand_format(architecture)
    skill_status = commands.add_parser(
        "skill-status",
        help="Inspect the project-local managed loopx-material skill.",
    )
    skill_status.add_argument("--project", default=".")
    skill_status.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
    )
    add_subcommand_format(skill_status)
    install_skill = commands.add_parser(
        "install-skill",
        help="Preview or install the managed loopx-material skill into one connected project.",
    )
    install_skill.add_argument("--project", default=".")
    install_skill.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
    )
    install_skill.add_argument("--execute", action="store_true")
    add_subcommand_format(install_skill)
    uninstall_skill = commands.add_parser(
        "uninstall-skill",
        help="Preview or uninstall the managed loopx-material skill from one project.",
    )
    uninstall_skill.add_argument("--project", default=".")
    uninstall_skill.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
    )
    uninstall_skill.add_argument("--execute", action="store_true")
    add_subcommand_format(uninstall_skill)


def handle_material_lifecycle_command(
    args: argparse.Namespace,
    *,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "material-lifecycle":
        return None
    try:
        if args.material_lifecycle_command == "architecture":
            payload = build_material_lifecycle_architecture_packet()
        elif args.material_lifecycle_command == "skill-status":
            payload = inspect_project_material_skill(
                args.project,
                surfaces=tuple(args.surface or ("codex",)),
            )
        elif args.material_lifecycle_command == "install-skill":
            payload = install_project_material_skill(
                args.project,
                surfaces=tuple(args.surface or ("codex",)),
                execute=args.execute,
            )
        else:
            payload = uninstall_project_material_skill(
                args.project,
                surfaces=tuple(args.surface or ("codex",)),
                execute=args.execute,
            )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "status": "blocked",
            "skill_id": "loopx-material",
            "error": str(exc),
            "surfaces": [],
        }
        print_payload(payload, output_format(args), _render)
        return 2
    print_payload(payload, output_format(args), _render)
    return 0

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..capabilities.periodic_report.machine_defaults import (
    materialize_goal_periodic_report_subscription,
)
from ..capabilities.machine_configuration.builtins import (
    build_builtin_machine_configuration_registry,
)
from ..capabilities.machine_configuration.store import read_machine_configuration
from ..control_plane.projects.registry import (
    PROJECT_KINDS,
    bind_session,
    register_project_goal,
    resolve_project,
    unbind_session,
)
from ..history import load_registry
from ..paths import DEFAULT_RUNTIME_ROOT

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]], None
]


def _new_goal_control_plane(
    *, registry_path: Path, runtime_root_arg: str | None, goal_id: str
) -> dict[str, object] | None:
    if runtime_root_arg:
        runtime_root = Path(runtime_root_arg).expanduser()
    elif registry_path.is_file():
        registry = load_registry(registry_path)
        runtime_root = Path(
            str(registry.get("common_runtime_root") or DEFAULT_RUNTIME_ROOT)
        ).expanduser()
    else:
        runtime_root = DEFAULT_RUNTIME_ROOT
    defaults = read_machine_configuration(
        runtime_root, registry=build_builtin_machine_configuration_registry()
    )
    if defaults is None:
        return None
    materialized = materialize_goal_periodic_report_subscription(
        {"id": goal_id}, defaults
    )
    control_plane = materialized.get("control_plane")
    return dict(control_plane) if isinstance(control_plane, dict) else None


def register_project_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    project_parser = subparsers.add_parser(
        "project",
        help="Register and deterministically resolve durable Projects and foreground Goals.",
    )
    project_sub = project_parser.add_subparsers(dest="project_command", required=True)
    register_parser = project_sub.add_parser(
        "register",
        help="Register one Project and its first active Goal in one registry mutation.",
    )
    add_subcommand_format(register_parser)
    register_parser.add_argument("--project-id", required=True)
    register_parser.add_argument("--project-kind", required=True, choices=PROJECT_KINDS)
    register_parser.add_argument("--knowledge-root", required=True)
    register_parser.add_argument("--goal-id", required=True)
    register_parser.add_argument("--objective", required=True)
    register_parser.add_argument("--non-goal", action="append", default=[])
    register_parser.add_argument(
        "--acceptance", action="append", default=[], required=True
    )
    register_parser.add_argument("--unknown", action="append", default=[])
    register_parser.add_argument("--next-effect", required=True)
    register_parser.add_argument("--stop-condition", required=True)
    register_parser.add_argument("--repository", action="append", default=[])
    register_parser.add_argument("--external-locator", action="append", default=[])

    bind_parser = project_sub.add_parser(
        "bind-session",
        help="Bind one host session to one active foreground Goal.",
    )
    add_subcommand_format(bind_parser)
    bind_parser.add_argument("--session-id", required=True)
    bind_parser.add_argument("--goal-id", required=True)

    unbind_parser = project_sub.add_parser(
        "unbind-session",
        help="Remove one exact host session binding from its expected foreground Goal.",
    )
    add_subcommand_format(unbind_parser)
    unbind_parser.add_argument("--session-id", required=True)
    unbind_parser.add_argument("--goal-id", required=True)

    resolve_parser = project_sub.add_parser(
        "resolve",
        help="Resolve Project identity from explicit, session, or exact locator evidence.",
    )
    add_subcommand_format(resolve_parser)
    resolve_parser.add_argument("--project-id")
    resolve_parser.add_argument("--session-id")
    resolve_parser.add_argument("--repository")
    resolve_parser.add_argument("--external-locator")


def render_project_command_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# LoopX Project",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- registry: `{payload.get('registry')}`",
    ]
    for field in (
        "changed",
        "resolution",
        "source",
        "project_id",
        "foreground_goal_id",
    ):
        if field in payload:
            lines.append(f"- {field}: `{payload.get(field)}`")
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
    return "\n".join(lines)


def handle_project_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: Callable[[argparse.Namespace], str],
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "project":
        return None
    try:
        if args.project_command == "register":
            goal_control_plane = _new_goal_control_plane(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                goal_id=args.goal_id,
            )
            payload = register_project_goal(
                registry_path=registry_path,
                runtime_root=Path(runtime_root_arg).expanduser()
                if runtime_root_arg
                else None,
                project_id=args.project_id,
                project_kind=args.project_kind,
                knowledge_root=Path(args.knowledge_root),
                goal_id=args.goal_id,
                objective=args.objective,
                non_goals=args.non_goal,
                acceptance=args.acceptance,
                unknowns=args.unknown,
                next_effect=args.next_effect,
                stop_condition=args.stop_condition,
                repository_bindings=args.repository,
                external_locator_bindings=args.external_locator,
                goal_control_plane=goal_control_plane,
            )
        elif args.project_command == "bind-session":
            payload = bind_session(
                registry_path=registry_path,
                session_id=args.session_id,
                goal_id=args.goal_id,
            )
        elif args.project_command == "unbind-session":
            payload = unbind_session(
                registry_path=registry_path,
                session_id=args.session_id,
                goal_id=args.goal_id,
            )
        else:
            payload = resolve_project(
                registry_path=registry_path,
                explicit_project_id=args.project_id,
                session_id=args.session_id,
                repository=args.repository,
                external_locator=args.external_locator,
            )
    except (OSError, TypeError, ValueError) as exc:
        payload = {
            "ok": False,
            "changed": False,
            "registry": str(registry_path),
            "error": str(exc),
        }
    payload.setdefault("registry", str(registry_path))
    print_payload(payload, output_format(args), render_project_command_markdown)
    return 0 if payload.get("ok") else 1

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..control_plane.runtime.goal_project_route import resolve_goal_project_route
from ..history import load_registry
from ..registry import registry_goals
from .benchmark_boundary import (
    handle_benchmark_boundary_command,
    register_benchmark_boundary_commands,
)
from .benchmark_experiment_board import (
    BENCHMARK_EXPERIMENT_BOARD_COMMANDS,
    handle_benchmark_experiment_board_command,
    register_benchmark_experiment_board_commands,
)

AddSubcommandFormat = Callable[[argparse.ArgumentParser], None]
OutputFormat = Callable[..., str]
PrintPayload = Callable[..., None]


def _registry_has_goal(registry_path: Path, goal_id: str) -> bool:
    registry = load_registry(registry_path.expanduser().resolve())
    return any(
        str(item.get("id") or "") == goal_id for item in registry_goals(registry)
    )


def _resolve_benchmark_project(
    args: argparse.Namespace,
    *,
    registry_path: Path,
) -> Path | None:
    if args.benchmark_command not in BENCHMARK_EXPERIMENT_BOARD_COMMANDS:
        return None
    goal_id = str(args.goal_id)
    project_override = getattr(args, "project", None)
    if project_override is None:
        _, project, _ = resolve_goal_project_route(
            registry_path=registry_path,
            goal_id=goal_id,
        )
        return project

    requested = Path(project_override).expanduser().resolve()
    requested_registry = requested / ".loopx" / "registry.json"
    route_registry = registry_path
    if not _registry_has_goal(route_registry, goal_id) and _registry_has_goal(
        requested_registry, goal_id
    ):
        route_registry = requested_registry
    if _registry_has_goal(route_registry, goal_id):
        _, project, _ = resolve_goal_project_route(
            registry_path=route_registry,
            goal_id=goal_id,
            project_override=requested,
        )
        return project
    return requested


def register_benchmark_command_group(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddSubcommandFormat,
) -> None:
    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="Provider-neutral benchmark integrity and evidence boundaries.",
    )
    benchmark_sub = benchmark_parser.add_subparsers(
        dest="benchmark_command",
        required=True,
    )
    register_benchmark_boundary_commands(benchmark_sub, add_subcommand_format)
    register_benchmark_experiment_board_commands(
        benchmark_sub,
        add_subcommand_format,
    )


def handle_benchmark_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    print_payload: PrintPayload,
    output_format: OutputFormat,
) -> int | None:
    if args.command != "benchmark":
        return None
    try:
        project = _resolve_benchmark_project(args, registry_path=registry_path)
    except (OSError, UnicodeError, ValueError) as exc:
        args.benchmark_experiment_board_parser.error(str(exc))
    handled = handle_benchmark_boundary_command(
        args,
        print_payload=print_payload,
        output_format=output_format,
    )
    if handled is not None:
        return handled
    return handle_benchmark_experiment_board_command(
        args,
        project=project,
        print_payload=print_payload,
        output_format=output_format,
    )

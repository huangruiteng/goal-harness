from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...capabilities.periodic_report.cli import render_periodic_report_markdown
from ...paths import resolve_runtime_root
from ...registry import read_json
from ..runtime import default_extension_state_file, resolve_extension_activation
from . import (
    LARK_EXTENSION_ID,
    LARK_GOAL_CHANNEL_PERMISSION,
    LARK_MIAODA_HTML_PERMISSION,
)
from .cli_resolution import (
    LarkCliUnavailableError,
    build_lark_command_runner,
    resolve_lark_cli,
)
from .miaoda_report import deliver_periodic_report_to_miaoda
from .periodic_report_delivery import deliver_periodic_report_to_goal_channel

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _load_json_object(path_text: str) -> dict[str, Any]:
    if path_text == "-":
        payload = json.loads(sys.stdin.read())
    else:
        payload = json.loads(Path(path_text).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path_text} must contain a JSON object")
    return payload


def register_lark_periodic_report_commands(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    miaoda = commands.add_parser(
        "publish-miaoda",
        help=(
            "Preview or execute one typed hosted Miaoda delivery intent with "
            "exact app and URL readback."
        ),
    )
    add_subcommand_format(miaoda)
    miaoda.add_argument(
        "--request-json",
        required=True,
        help="Path to periodic_report_miaoda_delivery_request_v0 JSON.",
    )
    miaoda.add_argument(
        "--lark-cli-bin",
        help="Optional explicit lark-cli executable; credentials remain in lark-cli.",
    )
    miaoda.add_argument(
        "--lark-profile",
        help="Optional lark-cli auth profile name; never an inline credential.",
    )
    miaoda.add_argument("--execute", action="store_true")
    goal_channel = commands.add_parser(
        "deliver-goal-channel",
        help=(
            "Preview or execute one report delivery through the current Goal "
            "Channel project Bot with exact sender and chat readback."
        ),
    )
    add_subcommand_format(goal_channel)
    goal_channel.add_argument("--goal-id", required=True)
    goal_channel.add_argument(
        "--request-json",
        required=True,
        help="Path to periodic_report_goal_channel_delivery_request_v0 JSON.",
    )
    goal_channel.add_argument("--execute", action="store_true")


def _resolved_goal_channel_runtime_root(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
) -> tuple[Path, Path]:
    resolved_registry = registry_path.expanduser().resolve()
    runtime_root = resolve_runtime_root(
        read_json(resolved_registry),
        runtime_root_arg,
        registry_path=resolved_registry,
    )
    return resolved_registry, runtime_root


def _goal_channel_payload(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root: Path,
    extension_activation: dict[str, Any],
) -> dict[str, Any]:
    call_args: dict[str, Any] = {
        "registry_path": registry_path,
        "runtime_root": runtime_root,
        "goal_id": args.goal_id,
        "extension_activation": extension_activation,
        "execute": bool(args.execute),
    }
    if args.execute:
        resolution = resolve_lark_cli()
        if not resolution.available or not resolution.command:
            raise LarkCliUnavailableError(
                resolution.error_code or "lark_cli_not_installed"
            )
        call_args["runner"] = build_lark_command_runner(resolution)
    return deliver_periodic_report_to_goal_channel(
        _load_json_object(args.request_json),
        **call_args,
    )


def _miaoda_payload(
    args: argparse.Namespace,
    *,
    extension_activation: dict[str, Any],
) -> dict[str, Any]:
    cli_bin = args.lark_cli_bin or "lark-cli"
    call_args: dict[str, Any] = {
        "extension_activation": extension_activation,
        "execute": bool(args.execute),
        "cli_bin": cli_bin,
        "lark_profile": args.lark_profile,
    }
    if args.execute:
        resolution = resolve_lark_cli(explicit=args.lark_cli_bin)
        if not resolution.available or not resolution.command:
            raise LarkCliUnavailableError(
                resolution.error_code or "lark_cli_not_installed"
            )
        call_args["cli_bin"] = resolution.command
        call_args["runner"] = build_lark_command_runner(resolution)
    return deliver_periodic_report_to_miaoda(
        _load_json_object(args.request_json),
        **call_args,
    )


def handle_lark_periodic_report_command(
    args: argparse.Namespace,
    *,
    runtime_root_arg: str | None,
    registry_path: Path,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if not (
        args.command == "periodic-report"
        and args.periodic_report_command in {"publish-miaoda", "deliver-goal-channel"}
    ):
        return None
    try:
        goal_channel_command = args.periodic_report_command == "deliver-goal-channel"
        resolved_runtime_root: Path | None = None
        if goal_channel_command:
            registry_path, resolved_runtime_root = _resolved_goal_channel_runtime_root(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
            )
        required_permission = LARK_GOAL_CHANNEL_PERMISSION
        if not goal_channel_command:
            required_permission = LARK_MIAODA_HTML_PERMISSION
        extension_activation = resolve_extension_activation(
            LARK_EXTENSION_ID,
            state_file=default_extension_state_file(
                resolved_runtime_root or runtime_root_arg
            ),
            required_permissions=(required_permission,),
        )
        if goal_channel_command:
            if resolved_runtime_root is None:
                raise ValueError("Goal Channel runtime root could not be resolved")
            payload = _goal_channel_payload(
                args,
                registry_path=registry_path,
                runtime_root=resolved_runtime_root,
                extension_activation=extension_activation,
            )
            print_payload(payload, output_format(args), render_periodic_report_markdown)
            return 0 if payload.get("ok") else 1
        payload = _miaoda_payload(
            args,
            extension_activation=extension_activation,
        )
    except Exception as exc:
        payload = {
            "ok": False,
            "schema_version": "periodic_report_error_v0",
            "command": args.periodic_report_command,
            "error": str(exc),
        }
    print_payload(payload, output_format(args), render_periodic_report_markdown)
    return 0 if payload.get("ok") else 1


__all__ = [
    "handle_lark_periodic_report_command",
    "register_lark_periodic_report_commands",
]

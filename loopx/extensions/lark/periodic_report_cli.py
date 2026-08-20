from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...capabilities.periodic_report.cli import render_periodic_report_markdown
from ..runtime import default_extension_state_file, resolve_extension_activation
from . import LARK_EXTENSION_ID, LARK_MIAODA_HTML_PERMISSION
from .cli_resolution import (
    LarkCliUnavailableError,
    build_lark_command_runner,
    resolve_lark_cli,
)
from .miaoda_report import deliver_periodic_report_to_miaoda

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


def handle_lark_periodic_report_command(
    args: argparse.Namespace,
    *,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if not (
        args.command == "periodic-report"
        and args.periodic_report_command == "publish-miaoda"
    ):
        return None
    try:
        extension_activation = resolve_extension_activation(
            LARK_EXTENSION_ID,
            state_file=default_extension_state_file(runtime_root_arg),
            required_permissions=(LARK_MIAODA_HTML_PERMISSION,),
        )
        cli_bin = args.lark_cli_bin or "lark-cli"
        runner = None
        if args.execute:
            resolution = resolve_lark_cli(explicit=args.lark_cli_bin)
            if not resolution.available or not resolution.command:
                raise LarkCliUnavailableError(
                    resolution.error_code or "lark_cli_not_installed"
                )
            cli_bin = resolution.command
            runner = build_lark_command_runner(resolution)
        call_args: dict[str, Any] = {
            "extension_activation": extension_activation,
            "execute": bool(args.execute),
            "cli_bin": cli_bin,
            "lark_profile": args.lark_profile,
        }
        if runner is not None:
            call_args["runner"] = runner
        payload = deliver_periodic_report_to_miaoda(
            _load_json_object(args.request_json),
            **call_args,
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

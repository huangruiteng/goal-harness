from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...paths import resolve_runtime_root
from ...registry import read_json
from .builtins import build_builtin_machine_configuration_registry
from .contract import remove_machine_configuration_namespace
from .store import (
    configure_machine_configuration,
    inspect_machine_configuration,
    read_machine_configuration,
    rollback_machine_configuration,
)


def _load_json_object(path_text: str) -> dict[str, Any]:
    if path_text == "-":
        payload = json.loads(sys.stdin.read())
    else:
        payload = json.loads(Path(path_text).expanduser().read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path_text} must contain a JSON object")
    return payload


def _render(payload: dict[str, object]) -> str:
    lines = ["# Machine Configuration", ""]
    for key in (
        "status",
        "action",
        "revision",
        "current_revision",
        "desired_revision",
        "plan_revision",
        "transaction_id",
        "rollback_id",
        "error",
    ):
        if key in payload:
            lines.append(f"- {key}: `{payload.get(key)}`")
    namespaces = payload.get("changed_namespaces")
    if isinstance(namespaces, list):
        lines.append(
            f"- changed_namespaces: `{', '.join(map(str, namespaces)) or 'none'}`"
        )
    return "\n".join(lines) + "\n"


def register_machine_configuration_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "machine-config",
        help="Inspect, preview, apply, or roll back typed machine configuration.",
    )
    commands = parser.add_subparsers(dest="machine_config_command", required=True)
    preview = commands.add_parser(
        "preview",
        help="Preview an exact change and return the plan revision required by apply.",
    )
    add_subcommand_format(preview)
    preview.add_argument("--config-json", required=True)
    apply = commands.add_parser(
        "apply",
        help="Apply an exact preview using its returned plan revision.",
    )
    add_subcommand_format(apply)
    apply.add_argument("--config-json", required=True)
    apply.add_argument(
        "--expected-plan-revision",
        required=True,
        help="Exact plan_revision returned by machine-config preview.",
    )
    apply.add_argument("--execute", action="store_true", required=True)
    inspect = commands.add_parser("inspect")
    add_subcommand_format(inspect)
    remove = commands.add_parser(
        "remove", help="Preview or remove one machine-configuration namespace."
    )
    add_subcommand_format(remove)
    remove.add_argument("--namespace", required=True)
    remove.add_argument(
        "--expected-plan-revision",
        help="Exact plan_revision returned by the preceding removal preview.",
    )
    remove.add_argument("--execute", action="store_true")
    rollback = commands.add_parser(
        "rollback",
        help="Preview a rollback, then apply it with the returned plan revision.",
    )
    add_subcommand_format(rollback)
    rollback.add_argument("--transaction-id", required=True)
    rollback.add_argument(
        "--expected-plan-revision",
        help="Exact plan_revision returned by the preceding rollback preview.",
    )
    rollback.add_argument("--execute", action="store_true")


def handle_machine_configuration_command(
    args: argparse.Namespace,
    *,
    runtime_root_arg: str | None,
    registry_path: Path,
    output_format: Callable[..., str],
    print_payload: Callable[
        [dict[str, object], str, Callable[[dict[str, object]], str]], None
    ],
) -> int | None:
    if args.command != "machine-config":
        return None
    registry = build_builtin_machine_configuration_registry()
    runtime_root = resolve_runtime_root(
        read_json(registry_path),
        runtime_root_arg,
        registry_path=registry_path,
    )
    try:
        if args.machine_config_command == "preview":
            payload = configure_machine_configuration(
                runtime_root=runtime_root,
                configuration=_load_json_object(args.config_json),
                registry=registry,
            )
        elif args.machine_config_command == "apply":
            payload = configure_machine_configuration(
                runtime_root=runtime_root,
                configuration=_load_json_object(args.config_json),
                registry=registry,
                execute=args.execute,
                expected_plan_revision=args.expected_plan_revision,
            )
        elif args.machine_config_command == "inspect":
            payload = inspect_machine_configuration(runtime_root, registry=registry)
        elif args.machine_config_command == "remove":
            payload = configure_machine_configuration(
                runtime_root=runtime_root,
                configuration=remove_machine_configuration_namespace(
                    read_machine_configuration(runtime_root, registry=registry),
                    namespace=args.namespace,
                    registry=registry,
                ),
                registry=registry,
                execute=args.execute,
                expected_plan_revision=args.expected_plan_revision,
            )
        else:
            payload = rollback_machine_configuration(
                runtime_root=runtime_root,
                transaction_id=args.transaction_id,
                registry=registry,
                execute=args.execute,
                expected_plan_revision=args.expected_plan_revision,
            )
    except (OSError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        payload = {
            "ok": False,
            "schema_version": "machine_configuration_error_v0",
            "status": "invalid_request",
            "error": str(exc),
        }
        print_payload(payload, output_format(args), _render)
        return 2
    print_payload(payload, output_format(args), _render)
    return 0


__all__ = [
    "handle_machine_configuration_command",
    "register_machine_configuration_commands",
]

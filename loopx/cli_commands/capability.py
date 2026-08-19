from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from ..capabilities.catalog import (
    build_capability_catalog_packet,
    build_capability_detail_packet,
    render_capability_catalog_markdown,
    render_capability_detail_markdown,
)
from ..extensions.capability_admission import invoke_external_capability
from ..extensions.runtime import (
    MAX_EXTENSION_REQUEST_BYTES,
    default_extension_state_file,
)

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _add_extension_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--extension-manifest",
        action="append",
        default=[],
        help=(
            "Declare one extension manifest for this catalog read without "
            "installing or enabling it. Repeat for multiple manifests."
        ),
    )
    parser.set_defaults(capability_operation_parser=parser)


def _load_json_object(path_text: str, *, label: str) -> dict[str, object]:
    try:
        if path_text == "-":
            binary_stdin = getattr(sys.stdin, "buffer", None)
            if binary_stdin is not None:
                raw = binary_stdin.read(MAX_EXTENSION_REQUEST_BYTES + 1)
            else:
                raw = sys.stdin.read(MAX_EXTENSION_REQUEST_BYTES + 1).encode("utf-8")
        else:
            with Path(path_text).expanduser().open("rb") as input_file:
                raw = input_file.read(MAX_EXTENSION_REQUEST_BYTES + 1)
        if len(raw) > MAX_EXTENSION_REQUEST_BYTES:
            raise ValueError(f"{label} exceeds the 1000000-byte limit")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be a readable JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _render_external_invocation(payload: dict[str, object]) -> str:
    lines = ["# LoopX External Capability Invocation", ""]
    for key in (
        "status",
        "capability_id",
        "operation",
        "effect_class",
        "invocation_id",
        "dry_run",
        "executed",
        "request_digest",
        "provider_result_digest",
        "error",
    ):
        if key in payload:
            lines.append(f"- {key}: `{payload.get(key)}`")
    return "\n".join(lines) + "\n"


def register_capability_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddFormat,
) -> None:
    capability_parser = subparsers.add_parser(
        "capability",
        help="Inspect real LoopX product capability paths.",
    )
    capability_sub = capability_parser.add_subparsers(
        dest="capability_command",
        required=True,
    )
    list_parser = capability_sub.add_parser(
        "list",
        help="List implemented product capability paths.",
    )
    add_subcommand_format(list_parser)
    _add_extension_manifest_argument(list_parser)
    show_parser = capability_sub.add_parser(
        "show",
        help="Show CLI, protocol, smoke, and boundary details for a capability.",
    )
    add_subcommand_format(show_parser)
    show_parser.add_argument(
        "capability_id",
        help="Capability id to inspect.",
    )
    _add_extension_manifest_argument(show_parser)
    invoke_parser = capability_sub.add_parser(
        "invoke",
        help="Preview or run one external capability enabled for a Goal.",
    )
    add_subcommand_format(invoke_parser)
    invoke_parser.add_argument("capability_id")
    invoke_parser.add_argument("--operation", required=True)
    invoke_parser.add_argument(
        "--goal-binding-json",
        required=True,
        help="Path to one loopx_goal_external_capability_binding_v0 object.",
    )
    invoke_parser.add_argument(
        "--input-json",
        required=True,
        help="Path to one object containing context_refs and input.",
    )
    invoke_parser.add_argument(
        "--state-file",
        dest="capability_state_file",
        help="Override the local extension activation state file.",
    )
    invoke_parser.add_argument("--execute", action="store_true")
    invoke_parser.set_defaults(capability_operation_parser=invoke_parser)


def handle_capability_command(
    args: argparse.Namespace,
    *,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "capability":
        return None
    manifest_paths = tuple(getattr(args, "extension_manifest", ()))
    state_file = Path(
        getattr(args, "capability_state_file", None)
        or default_extension_state_file(runtime_root_arg)
    ).expanduser()
    try:
        if args.capability_command == "list":
            payload = build_capability_catalog_packet(
                manifest_paths,
                extension_state_file=state_file,
            )
            renderer = render_capability_catalog_markdown
        elif args.capability_command == "show":
            payload = build_capability_detail_packet(
                args.capability_id,
                manifest_paths,
                extension_state_file=state_file,
            )
            renderer = render_capability_detail_markdown
        elif args.capability_command == "invoke":
            if args.goal_binding_json == "-" and args.input_json == "-":
                raise ValueError(
                    "Goal binding and provider input cannot both read from stdin"
                )
            payload = invoke_external_capability(
                state_file=state_file,
                capability_id=args.capability_id,
                operation=args.operation,
                goal_binding=_load_json_object(
                    args.goal_binding_json,
                    label="external capability Goal binding",
                ),
                provider_input=_load_json_object(
                    args.input_json,
                    label="external capability provider input",
                ),
                execute=args.execute,
            )
            renderer = _render_external_invocation
        else:
            raise ValueError("capability requires `list`, `show`, or `invoke`")
    except (RuntimeError, ValueError) as exc:
        if args.capability_command == "invoke":
            payload = {
                "ok": False,
                "schema_version": "loopx_external_domain_capability_error_v0",
                "status": "invalid_request",
                "error": str(exc),
            }
            print_payload(payload, output_format(args), _render_external_invocation)
            return 2
        args.capability_operation_parser.error(str(exc))
    print_payload(payload, output_format(args), renderer)
    return 0

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..extensions.lark import (
    LARK_EXTENSION_ID,
    LARK_GOAL_CHANNEL_PERMISSION,
)
from ..extensions.lark.goal_channel import (
    default_goal_channel_binding_path,
    doctor_lark_goal_channel,
    notify_lark_goal_channel_gate,
    setup_lark_goal_channel,
    sync_lark_goal_channel,
)
from ..extensions.runtime import (
    default_extension_state_file,
    resolve_extension_activation,
)
from ..control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)
from ..history import load_registry
from ..paths import registry_project_root, resolve_runtime_root
from ..quota import build_quota_should_run
from ..status import collect_status


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
OutputFormat = Callable[[argparse.Namespace], str]


def register_goal_channel_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "goal-channel",
        help="Project one LoopX goal into a provider-backed collaboration channel.",
    )
    sub = parser.add_subparsers(dest="goal_channel_command", required=True)

    setup = sub.add_parser(
        "setup",
        help="Create or reuse one provider channel for a goal. Dry-run unless --execute.",
    )
    add_subcommand_format(setup)
    _add_common_args(setup)
    setup.add_argument("--provider", default="lark", choices=["lark"])
    setup.add_argument("--chat-id", help="Reuse an existing Lark group chat.")
    setup.add_argument("--chat-name")
    setup.add_argument("--base-url", help="Reuse an existing Lark Base URL.")
    setup.add_argument("--base-token", help=argparse.SUPPRESS)
    setup.add_argument("--table-id", help=argparse.SUPPRESS)
    setup.add_argument(
        "--identity-mode",
        choices=["local_user", "project_bot"],
    )
    setup.add_argument("--sender-profile")
    setup.add_argument("--sender-identity", choices=["bot"])
    setup.add_argument(
        "--bot-app-id",
        help="Explicit Lark app id for the bot that will join and send messages.",
    )
    setup.add_argument("--bot-display-name")
    setup.add_argument("--cli-bin")
    setup.add_argument("--execute", action="store_true")

    doctor = sub.add_parser(
        "doctor",
        help="Verify extension, identity, channel, Kanban, and readback readiness.",
    )
    add_subcommand_format(doctor)
    _add_common_args(doctor)

    sync = sub.add_parser(
        "sync",
        help="Sync accepted LoopX todos into the configured channel Kanban.",
    )
    add_subcommand_format(sync)
    _add_common_args(sync)
    sync.add_argument("--agent-id")
    sync.add_argument("--execute", action="store_true")

    notify = sub.add_parser(
        "notify-gate",
        help="Send a bounded notification for a LoopX-selected human gate.",
    )
    add_subcommand_format(notify)
    _add_common_args(notify)
    notify.add_argument("--agent-id")
    notify.add_argument("--cooldown-seconds", type=int, default=3600)
    notify.add_argument("--execute", action="store_true")


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goal-id", required=True)
    parser.add_argument(
        "--binding-path",
        help="Local-private Goal Channel binding path beside the project registry.",
    )


def _error_packet(
    *,
    goal_id: str,
    operation: str,
    execute: bool,
    blocker: str,
    summary: str,
) -> dict[str, object]:
    return {
        "schema_version": "loopx_goal_channel_operation_v0",
        "ok": False,
        "goal_id": goal_id,
        "provider": "lark",
        "operation": operation,
        "execute": execute,
        "status": "blocked",
        "external_write_performed": False,
        "readback_verified": False,
        "idempotency_key": None,
        "receipt_id": None,
        "public_summary": summary,
        "private_provider_payload_captured": False,
        "blocker": blocker,
    }


def _quota_packet(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    agent_id: str | None,
) -> dict[str, Any]:
    project_root = registry_project_root(registry_path)
    status = collect_status(
        registry_path=registry_path,
        runtime_root_override=runtime_root_arg,
        scan_roots=[project_root],
        limit=20,
        goal_id=goal_id,
    )
    return build_quota_should_run(
        status,
        goal_id=goal_id,
        agent_id=agent_id,
    )


def handle_goal_channel_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    print_payload: PrintPayload,
    output_format: OutputFormat,
) -> int | None:
    if args.command != "goal-channel":
        return None
    command = str(args.goal_channel_command)
    execute = bool(getattr(args, "execute", False))
    goal_id = str(args.goal_id)
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(
        registry,
        runtime_root_arg,
        registry_path=registry_path,
    )
    source_route = resolve_goal_source_runtime_route(
        registry_path=registry_path,
        goal_id=goal_id,
        registry=registry,
    )
    source_registry_path = Path(str(source_route["source_registry"]))
    source_registry = (
        registry
        if source_registry_path.expanduser().resolve()
        == registry_path.expanduser().resolve()
        else load_registry(source_registry_path)
    )
    binding_path = (
        Path(args.binding_path).expanduser()
        if args.binding_path
        else default_goal_channel_binding_path(source_registry_path)
    )
    try:
        activation = resolve_extension_activation(
            LARK_EXTENSION_ID,
            state_file=default_extension_state_file(runtime_root),
            required_permissions=(LARK_GOAL_CHANNEL_PERMISSION,),
        )
    except Exception:
        payload = _error_packet(
            goal_id=goal_id,
            operation=command.replace("-", "_"),
            execute=execute,
            blocker="extension_unavailable",
            summary="install, enable, and doctor the bundled LoopX Lark extension",
        )
    else:
        try:
            if command == "setup":
                payload = setup_lark_goal_channel(
                    registry=source_registry,
                    registry_path=source_registry_path,
                    goal_id=goal_id,
                    binding_path=binding_path,
                    chat_id=args.chat_id,
                    chat_name=args.chat_name,
                    base_url=args.base_url,
                    base_token=args.base_token,
                    table_id=args.table_id,
                    identity_mode=args.identity_mode,
                    sender_profile=args.sender_profile,
                    sender_identity=args.sender_identity,
                    bot_app_id=getattr(args, "bot_app_id", None),
                    bot_display_name=args.bot_display_name,
                    cli_bin=args.cli_bin,
                    execute=execute,
                )
            elif command == "doctor":
                payload = doctor_lark_goal_channel(
                    registry=source_registry,
                    registry_path=source_registry_path,
                    goal_id=goal_id,
                    binding_path=binding_path,
                )
            elif command == "sync":
                payload = sync_lark_goal_channel(
                    registry=source_registry,
                    registry_path=source_registry_path,
                    goal_id=goal_id,
                    binding_path=binding_path,
                    agent_id=args.agent_id,
                    execute=execute,
                )
            elif command == "notify-gate":
                payload = notify_lark_goal_channel_gate(
                    registry=source_registry,
                    goal_id=goal_id,
                    binding_path=binding_path,
                    quota_packet=_quota_packet(
                        registry_path=registry_path,
                        runtime_root_arg=runtime_root_arg,
                        goal_id=goal_id,
                        agent_id=args.agent_id,
                    ),
                    cooldown_seconds=max(0, args.cooldown_seconds),
                    execute=execute,
                )
            else:
                raise ValueError(f"unknown goal-channel command: {command}")
            if payload.get("ok"):
                payload["extension_activation"] = activation
        except Exception:
            payload = _error_packet(
                goal_id=goal_id,
                operation=command.replace("-", "_"),
                execute=execute,
                blocker="provider_api_failed",
                summary="the Goal Channel operation failed before a verified provider receipt",
            )
    print_payload(payload, output_format(args), render_goal_channel_markdown)
    return 0 if payload.get("ok") else 1


def render_goal_channel_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# LoopX Goal Channel",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- provider: `{payload.get('provider')}`",
        f"- operation: `{payload.get('operation')}`",
        f"- status: `{payload.get('status')}`",
        f"- execute: `{payload.get('execute')}`",
        f"- external_write_performed: `{payload.get('external_write_performed')}`",
        f"- readback_verified: `{payload.get('readback_verified')}`",
    ]
    if payload.get("blocker"):
        lines.append(f"- blocker: `{payload.get('blocker')}`")
    lines.extend(["", str(payload.get("public_summary") or "")])
    details = payload.get("details")
    if isinstance(details, dict) and details:
        lines.extend(["", "## Details"])
        lines.extend(f"- {key}: `{value}`" for key, value in details.items())
    return "\n".join(lines)

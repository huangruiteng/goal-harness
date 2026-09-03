from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..control_plane.coordination.runtime_shadow import (
    build_todo_runtime_shadow_projection,
    dispatch_coordination_runtime_shadow,
    load_task_lease_runtime_shadow_records,
    resolve_coordination_runtime_shadow_config,
)
from ..control_plane.work_items.task_lease import (
    TaskLeaseError,
    inspect_task_lease,
    release_task_lease,
    renew_task_lease,
    runtime_root_from_registry,
    transfer_task_lease,
)
from ..control_plane.work_items.task_lease_acquire_adapter import (
    execute_native_task_lease_acquire,
)
from ..file_lock import LockAcquireTimeoutError
from ..history import load_registry
from ..presentation.markdown import append_operator_action_markdown
from ..registry import find_registry_goal
from ..todos import list_goal_todos


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]


def _mirror_committed_task_lease_runtime_shadow(
    payload: dict[str, object],
    *,
    args: argparse.Namespace,
    registry_path: Path,
    runtime_root_arg: str | None,
    runtime_root: Path,
) -> dict[str, object] | None:
    if not payload.get("ok") or args.task_lease_command == "inspect":
        return None
    try:
        registry = load_registry(registry_path)
        goal = find_registry_goal(registry, args.goal_id)
        shadow_enabled = resolve_coordination_runtime_shadow_config(goal).enabled
    except Exception:
        return None
    if not shadow_enabled:
        return None

    lease = payload.get("lease")
    source_version = (
        str(lease.get("updated_at") or "").strip()
        if isinstance(lease, dict)
        else ""
    )
    idempotency_key = str(args.idempotency_key or "").strip()
    if not source_version or not idempotency_key:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_dispatch_v0",
            "status": "failed",
            "reason_code": "canonical_mutation_identity_missing",
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    try:
        todo_projection = list_goal_todos(
            registry_path=registry_path,
            goal_id=args.goal_id,
            runtime_root_arg=runtime_root_arg,
        )
        projection = build_todo_runtime_shadow_projection(
            goal_id=args.goal_id,
            todos=todo_projection.get("todos"),
            leases=load_task_lease_runtime_shadow_records(
                runtime_root=runtime_root,
                goal_id=args.goal_id,
            ),
        )
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_dispatch_v0",
            "status": "failed",
            "reason_code": "shadow_projection_unavailable",
            "reason": str(exc),
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    return dispatch_coordination_runtime_shadow(
        goal=goal,
        runtime_root=runtime_root,
        goal_id=args.goal_id,
        operation_id=(
            f"task-lease-shadow:{args.task_lease_command}:{args.goal_id}:"
            f"{args.todo_id}:{idempotency_key}"
        ),
        event_kind=f"task_lease_{args.task_lease_command}",
        source_version=source_version,
        projection=projection,
    )


def render_task_lease_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# LoopX Task Lease",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- action: `{payload.get('action')}`",
    ]
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
    if payload.get("error_code"):
        lines.append(f"- error_code: `{payload.get('error_code')}`")
    lease = payload.get("lease")
    if isinstance(lease, dict):
        lines.extend(
            [
                f"- goal_id: `{lease.get('goal_id')}`",
                f"- todo_id: `{lease.get('todo_id')}`",
                f"- owner: `{lease.get('owner')}`",
                f"- version: `{lease.get('version')}`",
                f"- lease_epoch: `{lease.get('lease_epoch')}`",
                f"- status: `{lease.get('status')}`",
                f"- expires_at: `{lease.get('expires_at')}`",
                f"- write_scopes: `{', '.join(lease.get('write_scopes') or [])}`",
            ]
        )
    if payload.get("lease_path"):
        lines.append(f"- lease_path: `{payload.get('lease_path')}`")
    conflicts = payload.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        lines.append("- conflicts:")
        for conflict in conflicts:
            if not isinstance(conflict, dict):
                continue
            lines.append(
                f"  - `{conflict.get('todo_id')}` owner=`{conflict.get('owner')}` "
                f"expires_at=`{conflict.get('expires_at')}` "
                f"write_scopes=`{', '.join(conflict.get('write_scopes') or [])}`"
            )
    append_operator_action_markdown(lines, payload)
    return "\n".join(lines)


def register_task_lease_command(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "task-lease",
        help="Acquire, renew, transfer, release, or inspect a per-(goal_id,todo_id) hard task lease.",
    )
    add_subcommand_format(parser)
    parser.add_argument(
        "task_lease_command",
        choices=["acquire", "renew", "transfer", "release", "inspect"],
        help="Lease lifecycle action.",
    )
    parser.add_argument("--goal-id", required=True, help="Goal id that owns the todo.")
    parser.add_argument("--todo-id", required=True, help="Structured todo id such as todo_ab12cd34ef56.")
    parser.add_argument("--owner", help="Registered public-safe agent id that owns the lease.")
    parser.add_argument("--idempotency-key", help="Public-safe token used for idempotent retries and CAS.")
    parser.add_argument("--new-owner", help="For transfer, target registered public-safe agent id.")
    parser.add_argument("--new-idempotency-key", help="For transfer, target idempotency key.")
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        help="Lease TTL in seconds. Defaults to 45 minutes and is capped at 24 hours.",
    )
    parser.add_argument(
        "--write-scope",
        dest="write_scopes",
        action="append",
        help="Relative write scope protected by this lease, such as loopx/**. Repeatable.",
    )
    parser.add_argument(
        "--expected-version",
        type=int,
        help=(
            "CAS version that must match the current lease. Required for "
            "renew, transfer, and release; optional for acquire."
        ),
    )


def _requires_owner(args: argparse.Namespace) -> bool:
    return args.task_lease_command in {"acquire", "renew", "transfer", "release"}


def handle_task_lease_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: Callable[..., str],
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "task-lease":
        return None
    try:
        if _requires_owner(args) and not args.owner:
            raise ValueError("task-lease action requires --owner")
        if _requires_owner(args) and not args.idempotency_key:
            raise ValueError("task-lease action requires --idempotency-key")
        runtime_root = runtime_root_from_registry(registry_path, runtime_root_arg)
        if args.task_lease_command == "acquire":
            payload = execute_native_task_lease_acquire(
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                owner=args.owner,
                todo_id=args.todo_id,
                idempotency_key=args.idempotency_key,
                write_scopes=args.write_scopes,
                ttl_seconds=args.ttl_seconds,
                expected_version=args.expected_version,
            )
        elif args.task_lease_command == "renew":
            if args.write_scopes:
                raise ValueError("task-lease renew does not accept --write-scope")
            payload = renew_task_lease(
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                owner=args.owner,
                idempotency_key=args.idempotency_key,
                ttl_seconds=args.ttl_seconds,
                expected_version=args.expected_version,
            )
        elif args.task_lease_command == "transfer":
            if args.write_scopes:
                raise ValueError("task-lease transfer does not accept --write-scope")
            if not args.new_owner or not args.new_idempotency_key:
                raise ValueError("task-lease transfer requires --new-owner and --new-idempotency-key")
            payload = transfer_task_lease(
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                owner=args.owner,
                idempotency_key=args.idempotency_key,
                new_owner=args.new_owner,
                new_idempotency_key=args.new_idempotency_key,
                ttl_seconds=args.ttl_seconds,
                expected_version=args.expected_version,
            )
        elif args.task_lease_command == "release":
            if args.write_scopes:
                raise ValueError("task-lease release does not accept --write-scope")
            if args.ttl_seconds is not None:
                raise ValueError("task-lease release does not accept --ttl-seconds")
            payload = release_task_lease(
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                owner=args.owner,
                idempotency_key=args.idempotency_key,
                expected_version=args.expected_version,
                registry_path=registry_path,
            )
        else:
            unsupported = [
                flag
                for flag, value in (
                    ("--owner", args.owner),
                    ("--idempotency-key", args.idempotency_key),
                    ("--new-owner", args.new_owner),
                    ("--new-idempotency-key", args.new_idempotency_key),
                    ("--ttl-seconds", args.ttl_seconds),
                    ("--write-scope", args.write_scopes),
                    ("--expected-version", args.expected_version),
                )
                if value
            ]
            if unsupported:
                raise ValueError("task-lease inspect only accepts --goal-id and --todo-id; unsupported: " + ", ".join(unsupported))
            payload = inspect_task_lease(
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
            )
    except TaskLeaseError as exc:
        payload = {
            "ok": False,
            "schema_version": "task_lease_v0",
            "action": getattr(args, "task_lease_command", None),
            "error": str(exc),
            "error_code": exc.code,
            **exc.payload,
        }
    except LockAcquireTimeoutError as exc:
        payload = {
            "ok": False,
            "schema_version": "task_lease_v0",
            "action": getattr(args, "task_lease_command", None),
            "error": str(exc),
            **exc.to_payload(),
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "schema_version": "task_lease_v0",
            "action": getattr(args, "task_lease_command", None),
            "error": str(exc),
            "error_code": exc.__class__.__name__,
        }
    if payload.get("ok") and args.task_lease_command != "inspect":
        runtime_shadow = _mirror_committed_task_lease_runtime_shadow(
            payload,
            args=args,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            runtime_root=runtime_root,
        )
        if runtime_shadow is not None:
            payload["coordination_runtime_shadow"] = runtime_shadow
    print_payload(payload, output_format(args), render_task_lease_markdown)
    return 0 if payload.get("ok") else 1

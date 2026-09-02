from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from .core import (
    ALLOWED_CAPABILITIES,
    LOCAL_SYNTHETIC_SCOPE,
    PRODUCT_WRITE_SCOPE_ZERO,
    doctor_local_synthetic_providers,
    issue_local_synthetic_overlay_receipt,
    validate_local_synthetic_overlay_receipt,
    verify_compose_cleanup,
)

AddFormat = Callable[[argparse.ArgumentParser], None]
FormatSelector = Callable[..., str]
PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]], None
]


def _binding_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--todo-id", required=True)
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--candidate-head", required=True)
    parser.add_argument("--candidate-tree", required=True)
    parser.add_argument(
        "--capability",
        action="append",
        required=True,
        help=(
            "Requested overlay capability. Repeat exactly for local_container and "
            "synthetic_database; subsets and additions are rejected."
        ),
    )
    parser.add_argument("--synthetic-database-image", required=True)
    parser.add_argument("--scope", default=LOCAL_SYNTHETIC_SCOPE)
    parser.add_argument(
        "--product-write-scope", default=PRODUCT_WRITE_SCOPE_ZERO
    )
    parser.add_argument("--lifetime", default="task_bound")


def register_local_synthetic_overlay_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "local-synthetic-overlay",
        help="Issue and verify task-bound local synthetic validation authority.",
    )
    commands = parser.add_subparsers(
        dest="local_synthetic_overlay_command", required=True
    )

    doctor = commands.add_parser(
        "doctor",
        help="Inspect local providers without pulling or creating resources.",
    )
    add_subcommand_format(doctor)
    doctor.add_argument("--synthetic-database-image", required=True)

    issue = commands.add_parser(
        "issue",
        help="Preview or issue one system-managed exact task-bound receipt.",
    )
    add_subcommand_format(issue)
    _binding_arguments(issue)
    issue.add_argument("--ttl-seconds", type=int, default=4 * 60 * 60)
    issue.add_argument(
        "--reusable-across-tasks",
        choices=("NO", "YES"),
        default="NO",
    )
    issue.add_argument("--real-customer-data", choices=("NO", "YES"), default="NO")
    issue.add_argument("--real-child-data", choices=("NO", "YES"), default="NO")
    issue.add_argument("--real-audio", choices=("NO", "YES"), default="NO")
    issue.add_argument("--real-provider", choices=("NO", "YES"), default="NO")
    issue.add_argument("--production", choices=("NO", "YES"), default="NO")
    issue.add_argument(
        "--execute",
        action="store_true",
        help="Persist the receipt in LoopX-managed runtime state; preview is default.",
    )

    validate = commands.add_parser(
        "validate",
        help="Validate a stored receipt against the live Goal, Todo, and candidate.",
    )
    add_subcommand_format(validate)
    validate.add_argument("--receipt-id", required=True)
    _binding_arguments(validate)

    cleanup = commands.add_parser(
        "cleanup-check",
        help="Verify no task-labelled Compose container, volume, or network remains.",
    )
    add_subcommand_format(cleanup)
    cleanup.add_argument("--receipt-id", required=True)
    cleanup.add_argument("--compose-project", required=True)
    _binding_arguments(cleanup)


def render_local_synthetic_overlay_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# LoopX Local Synthetic Overlay",
        "",
        f"- ok: `{str(payload.get('ok')).lower()}`",
        f"- status: `{payload.get('status')}`",
    ]
    for key in (
        "receipt_id",
        "receipt_digest",
        "system_managed",
        "goal_id",
        "todo_id",
        "candidate_head",
        "candidate_tree",
        "scope",
        "product_write_scope",
        "error",
    ):
        if key in payload:
            lines.append(f"- {key}: `{payload.get(key)}`")
    return "\n".join(lines) + "\n"


def handle_local_synthetic_overlay_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "local-synthetic-overlay":
        return None
    command = args.local_synthetic_overlay_command
    try:
        if command == "doctor":
            payload = doctor_local_synthetic_providers(
                synthetic_database_image=args.synthetic_database_image
            )
            exit_code = 0 if payload.get("ok") is True else 2
        elif command == "issue":
            payload = issue_local_synthetic_overlay_receipt(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                repository=args.repo_path,
                candidate_head=args.candidate_head,
                candidate_tree=args.candidate_tree,
                capabilities=args.capability,
                synthetic_database_image=args.synthetic_database_image,
                scope=args.scope,
                product_write_scope=args.product_write_scope,
                lifetime=args.lifetime,
                reusable_across_tasks=args.reusable_across_tasks == "YES",
                real_customer_data=args.real_customer_data == "YES",
                real_child_data=args.real_child_data == "YES",
                real_audio=args.real_audio == "YES",
                real_provider=args.real_provider == "YES",
                production=args.production == "YES",
                ttl_seconds=args.ttl_seconds,
                execute=args.execute,
            )
            exit_code = 0
        elif command == "validate":
            payload = validate_local_synthetic_overlay_receipt(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                receipt_id=args.receipt_id,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                repository=args.repo_path,
                candidate_head=args.candidate_head,
                candidate_tree=args.candidate_tree,
                capabilities=args.capability,
                synthetic_database_image=args.synthetic_database_image,
                scope=args.scope,
                product_write_scope=args.product_write_scope,
                lifetime=args.lifetime,
            )
            exit_code = 0
        elif command == "cleanup-check":
            validation = validate_local_synthetic_overlay_receipt(
                registry_path=registry_path,
                runtime_root_arg=runtime_root_arg,
                receipt_id=args.receipt_id,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                repository=args.repo_path,
                candidate_head=args.candidate_head,
                candidate_tree=args.candidate_tree,
                capabilities=args.capability,
                synthetic_database_image=args.synthetic_database_image,
                scope=args.scope,
                product_write_scope=args.product_write_scope,
                lifetime=args.lifetime,
            )
            payload = verify_compose_cleanup(
                validation=validation,
                compose_project=args.compose_project,
            )
            exit_code = 0 if payload.get("ok") is True else 2
        else:  # pragma: no cover - argparse owns command selection
            raise ValueError("unknown local synthetic overlay command")
    except (OSError, RuntimeError, ValueError) as exc:
        payload = {
            "ok": False,
            "schema_version": "loopx_local_synthetic_overlay_error_v0",
            "status": "rejected",
            "error": str(exc),
            "allowed_capabilities": list(ALLOWED_CAPABILITIES),
            "legacy_dispatcher_used": False,
        }
        exit_code = 2
    print_payload(
        payload,
        output_format(args),
        render_local_synthetic_overlay_markdown,
    )
    return exit_code

from __future__ import annotations

import argparse
from collections.abc import Callable

from .core import (
    IntegrationBranchError,
    configure_integration_branch,
    integration_branch_status,
    sync_integration_branch,
)


def _render(payload: dict[str, object]) -> str:
    lines = ["# Integration Branch Reconcile", ""]
    for key in ("status", "sync_required", "changed", "updated", "plan_file"):
        if key in payload:
            lines.append(f"- {key}: `{payload.get(key)}`")
    reasons = payload.get("drift_reasons")
    if isinstance(reasons, list):
        lines.append(f"- drift_reason_count: `{len(reasons)}`")
        for reason in reasons:
            if isinstance(reason, dict):
                lines.append(f"  - `{reason.get('kind')}`")
    remote_refresh = payload.get("remote_refresh")
    if isinstance(remote_refresh, dict) and remote_refresh.get("requested"):
        remotes = remote_refresh.get("remotes")
        lines.append(f"- refreshed_remotes: `{remotes}`")
    return "\n".join(lines) + "\n"


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--plan-file")


def register_integration_branch_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "integration-branch",
        help="Detect source-branch drift and safely rebuild one local integration branch.",
    )
    commands = parser.add_subparsers(
        dest="integration_branch_command",
        required=True,
    )

    configure = commands.add_parser(
        "configure",
        help="Preview or write the ordered local integration-branch plan.",
    )
    add_subcommand_format(configure)
    _add_common_arguments(configure)
    configure.add_argument("--base-ref", required=True)
    configure.add_argument("--integration-branch", required=True)
    configure.add_argument(
        "--source-branch", action="append", default=[], required=True
    )
    configure.add_argument("--replace", action="store_true")
    configure.add_argument("--execute", action="store_true")

    status = commands.add_parser(
        "status",
        help="Compare current base, source, and integration heads with the last sync receipt.",
    )
    add_subcommand_format(status)
    _add_common_arguments(status)
    status.add_argument(
        "--refresh-remotes",
        action="store_true",
        help=(
            "Fetch only configured remote-tracking refs before resolving base "
            "and source refs; never pushes or changes source branches."
        ),
    )

    sync = commands.add_parser(
        "sync",
        help="Merge exact current source heads in order through a temporary worktree.",
    )
    add_subcommand_format(sync)
    _add_common_arguments(sync)
    sync.add_argument(
        "--candidate-ref",
        help=(
            "Use a manually resolved candidate commit after verifying it contains "
            "the configured base and every exact source head."
        ),
    )
    sync.add_argument(
        "--refresh-remotes",
        action="store_true",
        help=(
            "Fetch only configured remote-tracking refs before building or "
            "verifying the candidate; never pushes or changes source branches."
        ),
    )
    sync.add_argument("--execute", action="store_true")


def handle_integration_branch_command(
    args: argparse.Namespace,
    *,
    output_format: Callable[..., str],
    print_payload: Callable[[dict[str, object], str, Callable], None],
) -> int | None:
    if args.command != "integration-branch":
        return None
    try:
        if args.integration_branch_command == "configure":
            payload = configure_integration_branch(
                repo_path=args.repo_path,
                base_ref=args.base_ref,
                integration_branch=args.integration_branch,
                source_refs=args.source_branch,
                plan_file=args.plan_file,
                replace=args.replace,
                execute=args.execute,
            )
        elif args.integration_branch_command == "status":
            payload = integration_branch_status(
                repo_path=args.repo_path,
                plan_file=args.plan_file,
                refresh_remotes=args.refresh_remotes,
            )
        else:
            payload = sync_integration_branch(
                repo_path=args.repo_path,
                plan_file=args.plan_file,
                candidate_ref=args.candidate_ref,
                refresh_remotes=args.refresh_remotes,
                execute=args.execute,
            )
    except IntegrationBranchError as exc:
        payload = {
            "ok": False,
            "schema_version": "loopx_integration_branch_error_v0",
            "status": "invalid_state",
            "error": str(exc),
        }
        print_payload(payload, output_format(args), _render)
        return 2
    print_payload(payload, output_format(args), _render)
    return 0 if payload.get("ok") else 1

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import (
    DEFAULT_DOMAIN,
    DEFAULT_OBJECTIVE,
    bootstrap_project,
    render_bootstrap_markdown,
)
from .contract import check_contract, render_contract_markdown
from .history import collect_history, load_registry, render_history_markdown
from .paths import default_registry_path, resolve_runtime_root
from .registry import inspect_registry, render_registry_markdown
from .status import collect_status, render_status_markdown


def print_payload(payload: dict[str, object], fmt: str, markdown_renderer) -> None:
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(markdown_renderer(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Goal Harness control-plane helper.")
    parser.add_argument("--registry", default=str(default_registry_path()), help="Path to a project-local registry.")
    parser.add_argument("--runtime-root", help="Override registry common_runtime_root.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = sub.add_parser(
        "bootstrap",
        aliases=["connect"],
        help="Create or connect a project-local registry and active goal state.",
    )
    bootstrap_parser.add_argument("--project", default=".", help="Project directory to connect.")
    bootstrap_parser.add_argument("--goal-id", help="Stable goal id. Defaults to <project-name>-goal.")
    bootstrap_parser.add_argument("--objective", default=DEFAULT_OBJECTIVE, help="Initial goal objective.")
    bootstrap_parser.add_argument("--domain", default=DEFAULT_DOMAIN, help="Goal domain label.")
    bootstrap_parser.add_argument("--role", choices=["controller", "subagent"], default="controller")
    bootstrap_parser.add_argument("--parent-goal-id", help="Parent goal id when --role subagent.")
    bootstrap_parser.add_argument("--state-file", help="Active goal state path, relative to project unless absolute.")
    bootstrap_parser.add_argument("--adapter-kind", default="generic_project_goal_v0")
    bootstrap_parser.add_argument("--adapter-status", default="connected")
    bootstrap_parser.add_argument("--next-probe", help="Optional project-specific pre-tick command.")
    bootstrap_parser.add_argument("--spawn-allowed", action="store_true", help="Declare that this controller may spawn child agents.")
    bootstrap_parser.add_argument("--max-children", type=int, default=3)
    bootstrap_parser.add_argument("--allowed-domain", action="append", default=[], help="Allowed child work domain. Repeatable.")
    bootstrap_parser.add_argument("--write-scope", action="append", default=[], help="Allowed write scope such as docs/**. Repeatable.")
    bootstrap_parser.add_argument("--claim-ttl-minutes", type=int, default=30)
    bootstrap_parser.add_argument("--force", action="store_true", help="Replace existing goal entry or state file.")
    bootstrap_parser.add_argument("--dry-run", action="store_true", help="Show planned writes without changing files.")

    sub.add_parser("registry", help="Inspect registry goals and adapter declarations.")

    history_parser = sub.add_parser("history", help="Read compact run history from the shared runtime root.")
    history_parser.add_argument("--goal-id", help="Only show one goal.")
    history_parser.add_argument("--limit", type=int, default=10)

    check_parser = sub.add_parser("check", help="Run a read-only contract and public/private boundary check.")
    check_parser.add_argument("--scan-root", default=".", help="Public files to scan for obvious private material.")
    check_parser.add_argument(
        "--scan-path",
        action="append",
        default=[],
        help="Specific public file or directory to scan. Repeatable. Overrides --scan-root when set.",
    )
    check_parser.add_argument("--limit", type=int, default=5)

    status_parser = sub.add_parser("status", help="Show a first-screen goal status and attention queue.")
    status_parser.add_argument("--scan-root", default=".", help="Public files to scan for obvious private material.")
    status_parser.add_argument(
        "--scan-path",
        action="append",
        default=[],
        help="Specific public file or directory to scan. Repeatable. Overrides --scan-root when set.",
    )
    status_parser.add_argument("--limit", type=int, default=5)

    args = parser.parse_args(argv)
    registry_path = Path(args.registry).expanduser()

    if args.command in {"bootstrap", "connect"}:
        try:
            runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else None
            state_file = Path(args.state_file).expanduser() if args.state_file else None
            payload = bootstrap_project(
                project=Path(args.project),
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                objective=args.objective,
                domain=args.domain,
                role=args.role,
                parent_goal_id=args.parent_goal_id,
                state_file=state_file,
                adapter_kind=args.adapter_kind,
                adapter_status=args.adapter_status,
                next_probe=args.next_probe,
                spawn_allowed=args.spawn_allowed,
                max_children=args.max_children,
                allowed_domains=args.allowed_domain,
                write_scope=args.write_scope,
                claim_ttl_minutes=args.claim_ttl_minutes,
                force=args.force,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "error": str(exc),
            }
        print_payload(payload, args.format, render_bootstrap_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "registry":
        payload = inspect_registry(registry_path)
        print_payload(payload, args.format, render_registry_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "history":
        try:
            registry = load_registry(registry_path)
            runtime_root = resolve_runtime_root(registry, args.runtime_root)
            payload = collect_history(
                registry_path=registry_path,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                limit=max(0, args.limit),
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "error": str(exc),
            }
        print_payload(payload, args.format, render_history_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "check":
        try:
            scan_roots = [Path(item).expanduser() for item in args.scan_path]
            if not scan_roots:
                scan_roots = [Path(args.scan_root).expanduser()]
            payload = check_contract(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                scan_roots=scan_roots,
                limit=max(0, args.limit),
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "scan_roots": args.scan_path or [args.scan_root],
                "summary": {"errors": 1, "warnings": 0, "checks": 0},
                "errors": [str(exc)],
                "warnings": [],
                "checks": [],
            }
        print_payload(payload, args.format, render_contract_markdown)
        return 0 if payload.get("ok") else 1

    if args.command == "status":
        try:
            scan_roots = [Path(item).expanduser() for item in args.scan_path]
            if not scan_roots:
                scan_roots = [Path(args.scan_root).expanduser()]
            payload = collect_status(
                registry_path=registry_path,
                runtime_root_override=args.runtime_root,
                scan_roots=scan_roots,
                limit=max(0, args.limit),
            )
        except Exception as exc:
            payload = {
                "ok": False,
                "registry": str(registry_path),
                "runtime_root": args.runtime_root,
                "error": str(exc),
                "attention_queue": {
                    "available": False,
                    "item_count": 1,
                    "needs_user_or_controller": 0,
                    "needs_codex": 1,
                    "watching_external_evidence": 0,
                    "items": [
                        {
                            "goal_id": "goal-harness-status",
                            "status": "status_collection_failed",
                            "waiting_on": "codex",
                            "severity": "high",
                            "recommended_action": str(exc),
                            "source": "status",
                        }
                    ],
                },
            }
        print_payload(payload, args.format, render_status_markdown)
        return 0 if payload.get("ok") else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

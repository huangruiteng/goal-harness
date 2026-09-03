from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from ..control_plane.coordination.runtime_shadow import (
    bootstrap_coordination_runtime_shadow,
    build_todo_runtime_shadow_projection,
    inspect_coordination_runtime_shadow,
    load_task_lease_runtime_shadow_records,
    qualify_coordination_runtime_shadow,
    read_coordination_runtime_shadow_todo_candidate,
    resolve_coordination_runtime_shadow_config,
    rollback_coordination_runtime_shadow,
)
from ..history import load_registry
from ..paths import resolve_runtime_root
from ..registry import find_registry_goal
from ..todos import list_goal_todos


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]], None
]


def register_coordination_shadow_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = subparsers.add_parser(
        "coordination-shadow",
        help="Inspect or bootstrap the default-off Stage 2C file shadow.",
    )
    add_subcommand_format(parser)
    actions = parser.add_subparsers(
        dest="coordination_shadow_command",
        required=True,
    )
    for name, help_text in (
        ("inspect", "Compare the current legacy projection with the file shadow."),
        (
            "qualify",
            "Qualify sustained parity coverage across the file shadow lineage.",
        ),
        (
            "read-candidate",
            "Read one parity-matched file Todo as pre-promotion evidence.",
        ),
        (
            "bootstrap",
            "Import the current legacy projection into an empty file shadow.",
        ),
        ("rollback", "Quarantine one exact pre-promotion file shadow lineage."),
    ):
        action = actions.add_parser(name, help=help_text)
        action.add_argument("--goal-id", required=True)
        action.add_argument("--project", type=Path)
        action.add_argument("--state-file", type=Path)
        if name in {"bootstrap", "rollback"}:
            action.add_argument(
                "--execute",
                action="store_true",
                help="Execute the administrative effect; otherwise preview only.",
            )
        if name == "rollback":
            action.add_argument(
                "--provider-revision",
                required=True,
                help="Exact file shadow revision observed by inspect.",
            )
        if name == "qualify":
            action.add_argument(
                "--minimum-operations",
                type=int,
                default=3,
                help="Minimum distinct mirrored operations required (default: 3).",
            )
            action.add_argument(
                "--require-event-kind",
                action="append",
                default=[],
                help="Required mirrored mutation kind; repeat for multiple kinds.",
            )
        if name == "read-candidate":
            action.add_argument(
                "--todo-id",
                required=True,
                help="Exact Todo identity to read from the parity-matched file head.",
            )


def _projection_version(projection: dict[str, object]) -> str:
    payload = json.dumps(
        projection,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _render(payload: dict[str, object]) -> str:
    lines = [
        "# Coordination Shadow",
        "",
        f"- ok: `{str(bool(payload.get('ok'))).lower()}`",
        f"- action: `{payload.get('action')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- executed: `{str(bool(payload.get('executed'))).lower()}`",
    ]
    configuration = payload.get("configuration")
    if isinstance(configuration, dict):
        lines.append(f"- configuration: `{configuration.get('reason_code')}`")
    inspection = payload.get("inspection")
    if isinstance(inspection, dict):
        lines.extend(
            [
                f"- parity: `{inspection.get('status')}`",
                f"- decision_read_from_shadow: `{inspection.get('decision_read_from_shadow')}`",
            ]
        )
    bootstrap = payload.get("bootstrap")
    if isinstance(bootstrap, dict):
        lines.append(f"- bootstrap: `{bootstrap.get('status')}`")
    rollback = payload.get("rollback")
    if isinstance(rollback, dict):
        lines.append(f"- rollback: `{rollback.get('status')}`")
    qualification = payload.get("qualification")
    if isinstance(qualification, dict):
        lines.append(f"- qualification: `{qualification.get('status')}`")
    read_candidate = payload.get("read_candidate")
    if isinstance(read_candidate, dict):
        lines.extend(
            [
                f"- read_candidate: `{read_candidate.get('status')}`",
                f"- read_candidate_qualified: `{read_candidate.get('read_candidate_qualified')}`",
            ]
        )
    error = payload.get("error")
    if error:
        lines.append(f"- error: `{error}`")
    return "\n".join(lines)


def handle_coordination_shadow_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: Callable[..., str],
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "coordination-shadow":
        return None
    try:
        registry = load_registry(registry_path)
        goal = find_registry_goal(registry, args.goal_id)
        if goal is None:
            raise ValueError(f"goal {args.goal_id!r} is not present in the registry")
        config = resolve_coordination_runtime_shadow_config(goal)
        if not config.enabled:
            payload = {
                "ok": False,
                "schema_version": "loopx_coordination_shadow_admin_v0",
                "action": args.coordination_shadow_command,
                "goal_id": args.goal_id,
                "executed": False,
                "configuration": {
                    "enabled": False,
                    "provider": config.provider,
                    "reason_code": config.reason_code,
                },
                "error": "coordination shadow is not explicitly enabled for this goal",
                "error_code": "coordination_shadow_not_enabled",
                "decision_read_from_shadow": False,
            }
            print_payload(payload, output_format(args), _render)
            return 1
        runtime_root = resolve_runtime_root(
            registry,
            runtime_root_arg,
            registry_path=registry_path,
        )
        todo_projection = list_goal_todos(
            registry_path=registry_path,
            goal_id=args.goal_id,
            project=args.project,
            state_file=args.state_file,
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
        projection_version = _projection_version(projection)
        projected_todos = projection.get("todos")
        projected_leases = projection.get("leases")
        inspection = inspect_coordination_runtime_shadow(
            goal=goal,
            runtime_root=runtime_root,
            goal_id=args.goal_id,
            projection=projection,
        )
        payload: dict[str, object] = {
            "ok": inspection.get("status") != "failed",
            "schema_version": "loopx_coordination_shadow_admin_v0",
            "action": args.coordination_shadow_command,
            "goal_id": args.goal_id,
            "executed": False,
            "configuration": {
                "enabled": config.enabled,
                "provider": config.provider,
                "reason_code": config.reason_code,
            },
            "source_version": f"legacy-projection:{projection_version}",
            "projection_summary": {
                "todo_count": len(projected_todos)
                if isinstance(projected_todos, list)
                else 0,
                "lease_count": len(projected_leases)
                if isinstance(projected_leases, list)
                else 0,
            },
            "inspection": inspection,
            "decision_read_from_shadow": False,
        }
        if args.coordination_shadow_command == "bootstrap" and args.execute:
            bootstrap = bootstrap_coordination_runtime_shadow(
                goal=goal,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                operation_id=f"shadow-bootstrap:{args.goal_id}:{projection_version}",
                source_version=str(payload["source_version"]),
                projection=projection,
            )
            payload["executed"] = True
            payload["bootstrap"] = bootstrap
            if bootstrap.get("status") in {"applied", "replayed", "recovered"}:
                payload["inspection"] = inspect_coordination_runtime_shadow(
                    goal=goal,
                    runtime_root=runtime_root,
                    goal_id=args.goal_id,
                    projection=projection,
                )
            final_inspection = payload["inspection"]
            payload["ok"] = bool(
                bootstrap.get("status") in {"applied", "replayed", "recovered"}
                and isinstance(final_inspection, dict)
                and final_inspection.get("status") == "matched"
            )
        if args.coordination_shadow_command == "qualify":
            qualification = qualify_coordination_runtime_shadow(
                goal=goal,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                projection=projection,
                minimum_operations=args.minimum_operations,
                required_event_kinds=args.require_event_kind,
            )
            payload["qualification"] = qualification
            payload["ok"] = qualification.get("status") == "qualified"
        if args.coordination_shadow_command == "read-candidate":
            read_candidate = read_coordination_runtime_shadow_todo_candidate(
                goal=goal,
                runtime_root=runtime_root,
                goal_id=args.goal_id,
                todo_id=args.todo_id,
                projection=projection,
            )
            payload["read_candidate"] = read_candidate
            payload["ok"] = bool(
                read_candidate.get("status") == "matched"
                and read_candidate.get("read_candidate_qualified") is True
                and read_candidate.get("decision_read_from_shadow") is False
            )
        if args.coordination_shadow_command == "rollback":
            provider_revision = str(args.provider_revision).strip()
            payload["expected_provider_revision"] = provider_revision
            observed_revision = inspection.get("provider_revision")
            if observed_revision is not None and observed_revision != provider_revision:
                payload["ok"] = False
                payload["error"] = "provider revision does not match active shadow"
                payload["error_code"] = "shadow_provider_revision_mismatch"
            elif args.execute:
                rollback = rollback_coordination_runtime_shadow(
                    goal=goal,
                    runtime_root=runtime_root,
                    goal_id=args.goal_id,
                    operation_id=(
                        f"shadow-rollback:{args.goal_id}:{provider_revision}"
                    ),
                    expected_provider_revision=provider_revision,
                )
                payload["executed"] = True
                payload["rollback"] = rollback
                if rollback.get("status") in {"applied", "replayed"}:
                    payload["inspection"] = inspect_coordination_runtime_shadow(
                        goal=goal,
                        runtime_root=runtime_root,
                        goal_id=args.goal_id,
                        projection=projection,
                    )
                final_inspection = payload["inspection"]
                payload["ok"] = bool(
                    rollback.get("status") in {"applied", "replayed"}
                    and isinstance(final_inspection, dict)
                    and final_inspection.get("status") == "missing"
                )
    except Exception as exc:
        payload = {
            "ok": False,
            "schema_version": "loopx_coordination_shadow_admin_v0",
            "action": getattr(args, "coordination_shadow_command", None),
            "goal_id": getattr(args, "goal_id", None),
            "executed": False,
            "error": str(exc),
            "error_code": exc.__class__.__name__,
            "decision_read_from_shadow": False,
        }
    print_payload(payload, output_format(args), _render)
    return 0 if payload.get("ok") else 1

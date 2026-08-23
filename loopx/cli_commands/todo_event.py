from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..control_plane.todos.contract import decision_scope_metadata_value


RolloutEventAppender = Callable[..., dict[str, object]]

TODO_EVENT_KINDS = {
    "add": "todo_add",
    "claim": "todo_claim",
    "update": "todo_update",
    "complete": "todo_complete",
    "supersede": "todo_supersede",
    "archive-completed": "todo_archive_completed",
    "capture-followups": "todo_capture_followups",
}


def _append_todo_side_event(
    target: dict[str, object],
    *,
    args: argparse.Namespace,
    registry_path: Path,
    runtime_root_arg: str | None,
    append_cli_rollout_event: RolloutEventAppender,
    event_kind: str,
    todo_id: str | None,
    summary: str,
    details: dict[str, object],
    status: str | None = None,
) -> None:
    append_cli_rollout_event(
        target,
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        event_kind=event_kind,
        agent_id=args.agent_id or args.claimed_by,
        todo_id=todo_id,
        status=status,
        summary=summary,
        details={
            "command": "todo",
            "todo_command": args.todo_command,
            **details,
        },
    )


def _append_dependency_resume_events(
    payload: dict[str, object],
    *,
    args: argparse.Namespace,
    registry_path: Path,
    runtime_root_arg: str | None,
    append_cli_rollout_event: RolloutEventAppender,
) -> None:
    resumed_dependents = [
        item
        for item in (payload.get("dependency_resumes") or [])
        if isinstance(item, dict) and item.get("state") == "resumed"
    ]
    if not resumed_dependents:
        return
    primary_event = payload.get("rollout_event")
    resume_events: list[dict[str, object]] = []
    source_todo_id = payload.get("todo_id") or args.todo_id
    for resume in resumed_dependents:
        target_todo_id = str(resume.get("target_todo_id") or "").strip() or None
        _append_todo_side_event(
            payload,
            args=args,
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            append_cli_rollout_event=append_cli_rollout_event,
            event_kind="todo_dependency_resume",
            todo_id=target_todo_id,
            summary=(
                "todo dependency resume opened "
                f"{target_todo_id or 'dependent todo'} after "
                f"{source_todo_id}"
            ),
            details={
                "schema_version": resume.get("schema_version"),
                "source_todo_id": resume.get("source_todo_id"),
                "target_todo_id": resume.get("target_todo_id"),
                "target_role": resume.get("target_role"),
                "previous_status": resume.get("previous_status"),
                "status": resume.get("status"),
                "state": resume.get("state"),
                "changed": bool(resume.get("changed")),
            },
        )
        resume_event = payload.get("rollout_event")
        if isinstance(resume_event, dict):
            resume_events.append(resume_event)
    if primary_event is not None:
        payload["rollout_event"] = primary_event
    if resume_events:
        payload["dependency_resume_events"] = resume_events


def append_todo_rollout_event(
    payload: dict[str, object],
    *,
    args: argparse.Namespace,
    registry_path: Path,
    runtime_root_arg: str | None,
    append_cli_rollout_event: RolloutEventAppender,
) -> None:
    turn_instance_id = getattr(args, "turn_instance_id", None)
    terminal_closeout = bool(
        turn_instance_id
        and args.todo_command == "complete"
        and getattr(args, "no_follow_up", False)
    )
    if (
        not payload.get("ok")
        or payload.get("dry_run")
        or (payload.get("idempotent_replay") and not turn_instance_id)
    ):
        return
    append_cli_rollout_event(
        payload,
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        event_kind=TODO_EVENT_KINDS.get(args.todo_command, "todo_update"),
        agent_id=args.agent_id or args.claimed_by,
        todo_id=args.todo_id or str(payload.get("todo_id") or "").strip() or None,
        run_id=turn_instance_id,
        status=(
            "terminal_no_followup"
            if terminal_closeout
            else str(payload.get("status") or args.todo_command or "").strip()
        ),
        summary=(
            f"todo {args.todo_command} recorded for "
            f"{payload.get('todo_id') or args.todo_id or 'unstructured todo'}"
        ),
        details={
            "command": "todo",
            "todo_command": args.todo_command,
            "role": payload.get("role") or args.role or "",
            "task_class": (
                payload.get("task_class")
                or getattr(args, "task_class", None)
                or ""
            ),
            "decision_scope": decision_scope_metadata_value(
                payload.get("decision_scope")
            ),
            "decision_outcome": payload.get("decision_outcome"),
            "changed": bool(payload.get("changed")),
            "added": bool(payload.get("added")),
            "already_exists": bool(payload.get("already_exists")),
            "no_followup": bool(getattr(args, "no_follow_up", False)),
            "completion_continuation": payload.get("completion_continuation"),
            "completion_recovery": payload.get("completion_recovery"),
            "mutation_authority": payload.get("mutation_authority"),
            "replan_transition": payload.get("replan_transition"),
            "dependency_resumes": payload.get("dependency_resumes"),
            "settlement_effect_id": (
                payload.get("settlement_identity", {}).get("effect_id")
                if isinstance(payload.get("settlement_identity"), dict)
                else None
            ),
        },
        idempotency_fields=(
            [
                "goal_id",
                "event_kind",
                "agent_id",
                "todo_id",
                "run_id",
                *(["status"] if terminal_closeout else []),
            ]
            if turn_instance_id
            else None
        ),
    )
    _append_dependency_resume_events(
        payload,
        args=args,
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        append_cli_rollout_event=append_cli_rollout_event,
    )
    capability_gap_status = str(
        getattr(args, "capability_gap_status", None) or ""
    ).strip()
    if not capability_gap_status:
        return
    gap_payload: dict[str, object] = {
        "ok": True,
        "goal_id": payload.get("goal_id"),
    }
    _append_todo_side_event(
        gap_payload,
        args=args,
        registry_path=registry_path,
        runtime_root_arg=runtime_root_arg,
        append_cli_rollout_event=append_cli_rollout_event,
        event_kind="capability_gap",
        todo_id=args.todo_id or str(payload.get("todo_id") or "").strip() or None,
        status=capability_gap_status,
        summary=(
            f"capability gap {capability_gap_status} for "
            f"{payload.get('todo_id') or args.todo_id}"
        ),
        details={
            "target_capabilities": ",".join(args.target_capabilities or []),
            "evidence": args.evidence or "not_required_for_found",
        },
    )
    if gap_payload.get("rollout_event"):
        payload["capability_gap_event"] = gap_payload["rollout_event"]
    elif gap_payload.get("rollout_event_log_error"):
        payload["capability_gap_event_error"] = gap_payload[
            "rollout_event_log_error"
        ]

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..control_plane.capability_hooks import PostWritebackHookRegistration
from ..control_plane.quota.effect_program import SettlementIdentity
from ..control_plane.quota.settlement import (
    QuotaSettlementReadback,
    read_heartbeat_settlement,
    settlement_result_payload,
)
from ..control_plane.todos.contract import (
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_continuation_policy,
    normalize_todo_task_class,
)
from ..history import load_registry
from ..paths import resolve_runtime_root
from ..todos import complete_goal_todo, list_goal_todos
from .post_writeback import (
    PostWritebackProjectionBuilder,
    dispatch_committed_cli_post_writeback_hooks,
)
from .todo_argument_validation import validate_todo_complete_options


@dataclass(frozen=True, slots=True)
class TodoCompletionOutcome:
    """`loopx todo complete` result plus the settlement facts its closeout needs."""

    payload: dict[str, object]
    settlement_identity: SettlementIdentity | None
    completion_requires_settlement: bool


def completion_settlement_requirement(
    todo: dict[str, object],
    *,
    no_follow_up: bool,
) -> str | None:
    if no_follow_up:
        return "terminal no-follow-up closeout"
    task_class = normalize_todo_task_class(
        todo.get("task_class"),
        text=str(todo.get("text") or ""),
        action_kind=todo.get("action_kind"),
    )
    continuation_policy = normalize_todo_continuation_policy(
        todo.get("continuation_policy")
    )
    if (
        str(todo.get("role") or "") == "agent"
        and task_class == TODO_TASK_CLASS_ADVANCEMENT
        and continuation_policy != "same_agent_non_delivery"
    ):
        return "turn-scoped advancement completion"
    return None


def completion_settlement_error(
    todo: dict[str, object],
    settlement_readback: QuotaSettlementReadback,
    *,
    no_follow_up: bool,
) -> str | None:
    requirement = completion_settlement_requirement(
        todo,
        no_follow_up=no_follow_up,
    )
    if requirement is None or settlement_readback.settlement.failure is None:
        return None
    return (
        f"{requirement} requires matching writeback and quota spend receipts: "
        + settlement_readback.settlement.failure.reason
    )


def run_todo_complete(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    path_args: Mapping[str, Path | None],
) -> TodoCompletionOutcome:
    """Validate, settlement-gate, and write one `loopx todo complete` request."""

    validate_todo_complete_options(args)
    settlement_result = None
    settlement_identity = None
    settlement_readback = None
    completion_requires_settlement = False
    completion_error = None
    completion_turn_key = None
    completion_identity_source = None
    if getattr(args, "turn_instance_id", None):
        runtime_root = resolve_runtime_root(
            load_registry(registry_path),
            runtime_root_arg,
        )
        settlement_readback = read_heartbeat_settlement(
            runtime_root,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=args.todo_id,
            turn_instance_id=getattr(args, "turn_instance_id", None),
        )
        if settlement_readback is None:
            raise RuntimeError(
                "exact settlement readback unexpectedly returned not-found"
            )
        settlement_result = settlement_readback.identity
        if settlement_result.failure is not None:
            raise ValueError(settlement_result.failure.reason)
        if settlement_result.value is None:
            raise ValueError("turn-scoped Todo completion has no identity")
        identity = settlement_result.value
        settlement_identity = identity
        todo_payload = list_goal_todos(
            registry_path=registry_path,
            goal_id=args.goal_id,
            todo_id=args.todo_id,
            **path_args,
            runtime_root_arg=runtime_root_arg,
        )
        todo = (
            todo_payload.get("todo")
            if isinstance(todo_payload.get("todo"), dict)
            else None
        )
        if todo is None:
            raise ValueError(
                "turn-scoped Todo completion requires one durable Todo"
            )
        completion_requirement = completion_settlement_requirement(
            todo,
            no_follow_up=bool(args.no_follow_up),
        )
        completion_requires_settlement = completion_requirement is not None
        completion_error = completion_settlement_error(
            todo,
            settlement_readback=settlement_readback,
            no_follow_up=bool(args.no_follow_up),
        )
        if completion_error is not None:
            settlement_result = settlement_readback.settlement
            payload = {
                "ok": False,
                "dry_run": bool(args.dry_run),
                "completed": False,
                "changed": False,
                "goal_id": args.goal_id,
                "todo_id": args.todo_id,
                "settlement_blocked_completion": True,
                "settlement_identity": identity.as_dict(),
                "settlement_result": settlement_result_payload(
                    settlement_result
                ),
                "error": completion_error,
            }
        completion_turn_key = identity.effect_id
        completion_identity_source = "turn_settlement"
    elif getattr(args, "completion_identity_key", None):
        completion_turn_key = str(args.completion_identity_key)
        completion_identity_source = "lifecycle_reentry"
    if completion_error is None:
        payload = complete_goal_todo(
            registry_path=registry_path,
            runtime_root_arg=runtime_root_arg,
            goal_id=args.goal_id,
            todo_id=args.todo_id,
            role=args.role,
            decision_outcome=args.decision_outcome,
            evidence=args.evidence,
            completion_turn_key=completion_turn_key,
            completion_identity_source=completion_identity_source,
            task_lease_idempotency_key=args.task_lease_idempotency_key,
            task_lease_expected_version=args.task_lease_expected_version,
            note=args.note,
            no_followup=bool(args.no_follow_up),
            successor_todo_ids=args.successor_todo_ids,
            claimed_by=args.claimed_by,
            clear_claim=bool(args.clear_claim),
            next_agent_todo=args.next_agent_todo,
            next_user_todo=args.next_user_todo,
            next_user_task_class=args.next_user_task_class,
            next_claimed_by=args.next_claimed_by,
            next_task_class=args.next_task_class,
            next_action_kind=args.next_action_kind,
            next_task_repository=args.next_task_repository,
            next_required_capabilities=args.next_required_capabilities,
            next_continuation_policy=args.next_continuation_policy,
            next_excluded_agents=args.next_excluded_agents,
            self_merged=bool(args.self_merged),
            agent_id=args.agent_id,
            authority_reason=args.authority_reason,
            **path_args,
            dry_run=bool(args.dry_run),
        )
        if settlement_identity is not None:
            payload["settlement_identity"] = settlement_identity.as_dict()
            payload["settlement_result"] = settlement_result_payload(
                settlement_result
            )
    return TodoCompletionOutcome(
        payload=payload,
        settlement_identity=settlement_identity,
        completion_requires_settlement=completion_requires_settlement,
    )


def finalize_committed_todo_completion(
    outcome: TodoCompletionOutcome,
    *,
    args: argparse.Namespace,
    registry_path: Path,
    runtime_root_arg: str | None,
    post_writeback_hooks: Sequence[PostWritebackHookRegistration] | None,
    post_writeback_projection_builder: PostWritebackProjectionBuilder | None,
) -> None:
    """Re-read settlement receipts and dispatch hooks after a committed completion.

    Runs after the rollout event and runtime-shadow observers so their payload
    fields are already present; mutates ``outcome.payload`` in place.
    """

    payload = outcome.payload
    settlement_identity = outcome.settlement_identity
    if (
        getattr(args, "turn_instance_id", None)
        and payload.get("ok")
        and not payload.get("dry_run")
    ):
        runtime_root = resolve_runtime_root(
            load_registry(registry_path),
            runtime_root_arg,
        )
        settlement_readback = read_heartbeat_settlement(
            runtime_root,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=args.todo_id,
            turn_instance_id=getattr(args, "turn_instance_id", None),
        )
        if settlement_readback is None:
            raise RuntimeError("exact settlement readback unexpectedly returned not-found")
        settlement_result = (
            settlement_readback.terminal_settlement
            if args.no_follow_up and settlement_identity is not None
            else settlement_readback.settlement
            if outcome.completion_requires_settlement
            else settlement_readback.identity
        )
        payload["settlement_result"] = settlement_result_payload(
            settlement_result
        )
        if settlement_result.failure is not None:
            payload["ok"] = False
            payload["receipt_repair_required"] = True
            payload["error"] = settlement_result.failure.reason
    if (
        payload.get("ok")
        and payload.get("completed")
        and not payload.get("dry_run")
        and post_writeback_hooks
        and settlement_identity is not None
    ):
        identity = settlement_identity.as_dict()
        committed_at = str(payload.get("updated_at") or "").strip()
        if committed_at:
            payload["post_writeback_hooks"] = (
                dispatch_committed_cli_post_writeback_hooks(
                    payload=payload,
                    registry_path=registry_path,
                    runtime_root_arg=runtime_root_arg,
                    goal_id=args.goal_id,
                    event_kind="todo_complete",
                    identity=identity,
                    state_version=committed_at,
                    committed_at=committed_at,
                    hooks=post_writeback_hooks,
                    projection_builder=post_writeback_projection_builder,
                )
            )

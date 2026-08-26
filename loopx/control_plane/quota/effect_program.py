from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from ..effect_program import (
    SETTLEMENT_IDENTITY_SCHEMA_VERSION,
    SETTLEMENT_PLAN_SCHEMA_VERSION,
    SETTLEMENT_RECEIPT_SCHEMA_VERSION,
    ReceiptBoundMonitorPhase,
    ReceiptBoundReplayPhase,
    ReceiptBoundTerminalPhase,
    SettlementBindingKind,
    SettlementFailure,
    SettlementFailureKind,
    SettlementIdentity,
    SettlementPlan,
    SettlementReceipt,
    SettlementResult,
    SettlementStep,
    SettlementStepKind,
    receipt_bound_monitor_phase,
    receipt_bound_replay_phase,
    receipt_bound_terminal_phase,
    settlement_result_payload,
)

__all__ = [
    "SETTLEMENT_IDENTITY_SCHEMA_VERSION",
    "SETTLEMENT_PLAN_SCHEMA_VERSION",
    "SETTLEMENT_RECEIPT_SCHEMA_VERSION",
    "ReceiptBoundMonitorPhase",
    "ReceiptBoundReplayPhase",
    "ReceiptBoundTerminalPhase",
    "SettlementBindingKind",
    "SettlementFailure",
    "SettlementFailureKind",
    "SettlementIdentity",
    "SettlementPlan",
    "SettlementReceipt",
    "SettlementResult",
    "SettlementStep",
    "SettlementStepKind",
    "build_codex_app_settlement_plan",
    "build_turn_scoped_cli_settlement_plan",
    "receipt_bound_monitor_phase",
    "receipt_bound_replay_phase",
    "receipt_bound_terminal_phase",
    "settlement_binding_args",
    "settlement_result_payload",
    "settlement_step_command",
]


def _quoted_turn_ref(turn_instance_id_ref: str) -> str:
    if turn_instance_id_ref == "${LOOPX_TURN:?}":
        return '"${LOOPX_TURN:?}"'
    return shlex.quote(turn_instance_id_ref)


def build_codex_app_settlement_plan(
    *,
    goal_id: str,
    agent_id: str,
    todo_id: str | None = None,
    replan_obligation_id: str | None = None,
    scoped_cli_args: str,
    lifecycle_actor_args: str,
    turn_instance_id_ref: str | None = None,
    delivery_boundary: str | None = None,
    quota_spend_source: str = "heartbeat",
) -> SettlementPlan:
    return build_turn_scoped_cli_settlement_plan(
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        replan_obligation_id=replan_obligation_id,
        scoped_cli_args=scoped_cli_args,
        lifecycle_actor_args=lifecycle_actor_args,
        turn_instance_id=turn_instance_id_ref or "${LOOPX_TURN:?}",
        delivery_boundary=delivery_boundary,
        quota_spend_source=quota_spend_source,
    )


def build_turn_scoped_cli_settlement_plan(
    *,
    goal_id: str,
    agent_id: str,
    todo_id: str | None = None,
    replan_obligation_id: str | None = None,
    scoped_cli_args: str,
    lifecycle_actor_args: str,
    turn_instance_id: str,
    delivery_boundary: str | None = None,
    quota_spend_source: str = "heartbeat",
) -> SettlementPlan:
    if bool(todo_id) == bool(replan_obligation_id):
        raise ValueError(
            "turn-scoped CLI settlement requires exactly one Todo or autonomous "
            "replan obligation binding"
        )
    if quota_spend_source not in {"heartbeat", "visible-goal"}:
        raise ValueError(
            "turn-scoped CLI settlement requires quota_spend_source heartbeat "
            "or visible-goal"
        )
    identity = SettlementIdentity(
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id,
        replan_obligation_id=replan_obligation_id,
    )
    quoted_turn = _quoted_turn_ref(turn_instance_id)
    binding_arg = (
        f" --todo-id {shlex.quote(todo_id)}"
        if todo_id
        else f" --replan-obligation-id {shlex.quote(str(replan_obligation_id))}"
    )
    turn_arg = f" --turn-instance-id {quoted_turn}"
    boundary_arg = (
        " --delivery-boundary in_flight_continuation"
        if delivery_boundary == "in_flight_continuation"
        else ""
    )
    terminal_closeout = (
        f"loopx todo complete --goal-id {shlex.quote(goal_id)}{binding_arg}"
        f"{lifecycle_actor_args}{turn_arg} --evidence '<validated evidence>'"
        " --no-follow-up"
    )
    writeback = (
        f"loopx refresh-state --goal-id {shlex.quote(goal_id)} "
        "--classification <validated_progress> --delivery-batch-scale <scale> "
        f"--delivery-outcome <outcome>{boundary_arg}{binding_arg}{turn_arg}"
        f"{scoped_cli_args}"
    )
    spend = (
        f"loopx quota spend-slot --goal-id {shlex.quote(goal_id)} --slots 1 "
        f"--source {quota_spend_source} --execute{binding_arg}{turn_arg}"
        f"{scoped_cli_args}"
    )
    effect_ref = "$.identity.effect_id"
    return SettlementPlan(
        identity=identity,
        steps=(
            SettlementStep(
                kind=SettlementStepKind.VALIDATION,
                owner="agent",
                precondition="delivery result is independently validated",
                idempotency_key_ref=effect_ref,
                expected_receipt="validation_receipt",
            ),
            SettlementStep(
                kind=SettlementStepKind.DURABLE_WRITEBACK,
                owner="agent",
                precondition="validation succeeded",
                idempotency_key_ref=effect_ref,
                expected_receipt="durable_writeback_receipt",
                command_template=writeback,
            ),
            SettlementStep(
                kind=SettlementStepKind.QUOTA_SPEND,
                owner="agent",
                precondition="matching durable writeback receipt exists",
                idempotency_key_ref=effect_ref,
                expected_receipt="quota_spend_receipt",
                command_template=spend,
            ),
            *(
                (
                    SettlementStep(
                        kind=SettlementStepKind.TERMINAL_CLOSEOUT,
                        owner="agent",
                        precondition=(
                            "the selected Todo is final with no runnable successor "
                            "and matching writeback and quota spend receipts exist"
                        ),
                        idempotency_key_ref=effect_ref,
                        expected_receipt="terminal_closeout_receipt",
                        command_template=terminal_closeout,
                        conditional=True,
                    ),
                )
                if todo_id
                else ()
            ),
        ),
    )


def settlement_step_command(
    plan: Mapping[str, Any] | None,
    kind: SettlementStepKind,
) -> str | None:
    if not isinstance(plan, Mapping):
        return None
    steps = plan.get("ordered_steps")
    if not isinstance(steps, list):
        return None
    for step in steps:
        if not isinstance(step, Mapping) or step.get("kind") != kind.value:
            continue
        command = str(step.get("command_template") or "").strip()
        return command or None
    return None


def settlement_binding_args(plan: Mapping[str, Any] | None) -> str:
    if not isinstance(plan, Mapping):
        return ""
    identity = plan.get("identity")
    if not isinstance(identity, Mapping):
        return ""
    todo_id = str(identity.get("todo_id") or "").strip()
    replan_obligation_id = str(identity.get("replan_obligation_id") or "").strip()
    turn_instance_id = str(identity.get("turn_instance_id") or "").strip()
    if bool(todo_id) == bool(replan_obligation_id) or not turn_instance_id:
        return ""
    binding_arg = (
        f" --todo-id {shlex.quote(todo_id)}"
        if todo_id
        else f" --replan-obligation-id {shlex.quote(replan_obligation_id)}"
    )
    return binding_arg + (f" --turn-instance-id {_quoted_turn_ref(turn_instance_id)}")

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Generic, TypeVar, cast

SETTLEMENT_IDENTITY_SCHEMA_VERSION = "quota_settlement_identity_v0"
SETTLEMENT_PLAN_SCHEMA_VERSION = "quota_settlement_plan_v0"
SETTLEMENT_RECEIPT_SCHEMA_VERSION = "quota_settlement_receipt_v0"


class SettlementStepKind(StrEnum):
    VALIDATION = "validation"
    TODO_COMPLETION = "todo_completion"
    DURABLE_WRITEBACK = "durable_writeback"
    QUOTA_SPEND = "quota_spend"


class SettlementFailureKind(StrEnum):
    INVALID_IDENTITY = "invalid_identity"
    RECEIPT_MISSING = "receipt_missing"
    IDENTITY_MISMATCH = "identity_mismatch"
    WRITEBACK_MISSING = "writeback_missing"
    CANCELLED = "cancelled"
    PERMISSION_DENIED = "permission_denied"
    BUDGET_REJECTED = "budget_rejected"


@dataclass(frozen=True, slots=True)
class SettlementIdentity:
    goal_id: str
    agent_id: str
    todo_id: str
    turn_instance_id: str

    @property
    def effect_id(self) -> str:
        return f"{self.goal_id}:{self.agent_id}:{self.todo_id}:{self.turn_instance_id}"

    def as_dict(self) -> dict[str, str]:
        return {
            "schema_version": SETTLEMENT_IDENTITY_SCHEMA_VERSION,
            "effect_id": self.effect_id,
            "goal_id": self.goal_id,
            "agent_id": self.agent_id,
            "todo_id": self.todo_id,
            "turn_instance_id": self.turn_instance_id,
        }


@dataclass(frozen=True, slots=True)
class SettlementReceipt:
    step_kind: SettlementStepKind
    status: str
    effect_id: str
    source_ref: str | None = None

    def as_dict(self) -> dict[str, str]:
        receipt = {
            "schema_version": SETTLEMENT_RECEIPT_SCHEMA_VERSION,
            "step_kind": self.step_kind.value,
            "status": self.status,
            "effect_id": self.effect_id,
        }
        if self.source_ref:
            receipt["source_ref"] = self.source_ref
        return receipt


@dataclass(frozen=True, slots=True)
class SettlementFailure:
    kind: SettlementFailureKind
    step_kind: SettlementStepKind
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "step_kind": self.step_kind.value,
            "reason": self.reason,
        }


T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True, slots=True)
class SettlementResult(Generic[T]):
    value: T | None
    receipts: tuple[SettlementReceipt, ...] = ()
    failure: SettlementFailure | None = None

    @classmethod
    def pure(
        cls,
        value: T,
        *,
        receipts: tuple[SettlementReceipt, ...] = (),
    ) -> SettlementResult[T]:
        return cls(value=value, receipts=receipts)

    @classmethod
    def failed(
        cls,
        *,
        kind: SettlementFailureKind,
        step_kind: SettlementStepKind,
        reason: str,
        receipts: tuple[SettlementReceipt, ...] = (),
    ) -> SettlementResult[T]:
        return cls(
            value=None,
            receipts=receipts,
            failure=SettlementFailure(
                kind=kind,
                step_kind=step_kind,
                reason=reason,
            ),
        )

    def bind(self, step: Callable[[T], SettlementResult[U]]) -> SettlementResult[U]:
        if self.failure is not None:
            return SettlementResult(
                value=None,
                receipts=self.receipts,
                failure=self.failure,
            )
        next_result = step(cast(T, self.value))
        return SettlementResult(
            value=next_result.value,
            receipts=(*self.receipts, *next_result.receipts),
            failure=next_result.failure,
        )


@dataclass(frozen=True, slots=True)
class SettlementStep:
    kind: SettlementStepKind
    owner: str
    precondition: str
    idempotency_key_ref: str
    expected_receipt: str
    command_template: str | None = None
    conditional: bool = False

    def as_dict(self) -> dict[str, Any]:
        step: dict[str, Any] = {
            "kind": self.kind.value,
            "owner": self.owner,
            "precondition": self.precondition,
            "idempotency_key_ref": self.idempotency_key_ref,
            "expected_receipt": self.expected_receipt,
        }
        if self.command_template:
            step["command_template"] = self.command_template
        if self.conditional:
            step["conditional"] = True
        return step


@dataclass(frozen=True, slots=True)
class SettlementPlan:
    identity: SettlementIdentity
    steps: tuple[SettlementStep, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SETTLEMENT_PLAN_SCHEMA_VERSION,
            "identity": self.identity.as_dict(),
            "ordered_steps": [step.as_dict() for step in self.steps],
            "host_handoff": {
                "owner": "host",
                "kind": "scheduler_handoff",
                "inside_agent_settlement": False,
            },
        }


def _quoted_turn_ref(turn_instance_id_ref: str) -> str:
    if turn_instance_id_ref == "${LOOPX_TURN:?}":
        return '"${LOOPX_TURN:?}"'
    return shlex.quote(turn_instance_id_ref)


def build_codex_app_settlement_plan(
    *,
    goal_id: str,
    agent_id: str,
    todo_id: str,
    scoped_cli_args: str,
    lifecycle_actor_args: str,
    turn_instance_id_ref: str = "${LOOPX_TURN:?}",
) -> SettlementPlan:
    identity = SettlementIdentity(
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id_ref,
    )
    quoted_turn = _quoted_turn_ref(turn_instance_id_ref)
    todo_arg = f" --todo-id {shlex.quote(todo_id)}"
    turn_arg = f" --turn-instance-id {quoted_turn}"
    completion = (
        f"loopx todo complete --goal-id {shlex.quote(goal_id)}{todo_arg}"
        f"{lifecycle_actor_args}{turn_arg} --evidence '<validated evidence>'"
        " [--successor-todo-id <todo_id> | --no-follow-up]"
    )
    writeback = (
        f"loopx refresh-state --goal-id {shlex.quote(goal_id)} "
        "--classification <validated_progress> --delivery-batch-scale <scale> "
        f"--delivery-outcome <outcome>{todo_arg}{turn_arg}{scoped_cli_args}"
    )
    spend = (
        f"loopx quota spend-slot --goal-id {shlex.quote(goal_id)} --slots 1 "
        f"--source heartbeat --execute{todo_arg}{turn_arg}{scoped_cli_args}"
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
                kind=SettlementStepKind.TODO_COMPLETION,
                owner="agent",
                precondition="validated result closes the selected Todo",
                idempotency_key_ref=effect_ref,
                expected_receipt="todo_completion_receipt",
                command_template=completion,
                conditional=True,
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
    turn_instance_id = str(identity.get("turn_instance_id") or "").strip()
    if not todo_id or not turn_instance_id:
        return ""
    return (
        f" --todo-id {shlex.quote(todo_id)}"
        f" --turn-instance-id {_quoted_turn_ref(turn_instance_id)}"
    )

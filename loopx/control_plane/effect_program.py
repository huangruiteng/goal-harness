from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar, cast


# Identity remains stable while the plan and receipt versions advance with the
# typed terminal-closeout step shared by quota and Turn adapters.
SETTLEMENT_IDENTITY_SCHEMA_VERSION = "quota_settlement_identity_v0"
SETTLEMENT_PLAN_SCHEMA_VERSION = "quota_settlement_plan_v1"
SETTLEMENT_RECEIPT_SCHEMA_VERSION = "quota_settlement_receipt_v1"


@dataclass(frozen=True)
class EffectRequest:
    kind: str
    source: str
    goal_id: str | None = None
    agent_id: str | None = None
    capabilities: tuple[str, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectInterpretation:
    route: str
    obligation: str
    interaction_mode: str
    capability_action: str | None = None
    cadence_class: str | None = None


@dataclass(frozen=True)
class EffectObservation:
    decision: str
    should_run: bool
    effective_action: str
    recommended_action: str
    protocol_summary: str | None = None


@dataclass(frozen=True)
class EffectNext:
    cli_actions: tuple[str, ...] = ()
    execution_mode: str | None = None
    scheduler_action: str | None = None
    cadence_class: str | None = None
    ack_cli_args: tuple[str, ...] = ()
    failure_cli_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectTurn:
    request: EffectRequest
    interpretation: EffectInterpretation
    observation: EffectObservation
    next_effect: EffectNext


@dataclass(frozen=True)
class EffectStep:
    step_id: str | None = None
    kind: str | None = None
    command: str | None = None
    purpose: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectProgram:
    steps: tuple[EffectStep, ...] = ()
    execution_mode: str | None = None


class TurnTransactionPhase(StrEnum):
    HOST_EXECUTE = "host_execute"
    TYPED_RESULT = "typed_result"
    VALIDATION = "validation"
    DURABLE_WRITEBACK = "durable_writeback"
    QUOTA_SPEND = "quota_spend"
    SCHEDULER_APPLY = "scheduler_apply"
    SCHEDULER_ACK = "scheduler_ack"


TURN_TRANSACTION_PHASES = tuple(phase.value for phase in TurnTransactionPhase)


class TurnJournalViolation(StrEnum):
    GOAL_IDENTITY_MISSING = "goal_identity_missing"
    GOAL_MISMATCH = "goal_mismatch"
    OWNER_IDENTITY_MISSING = "owner_identity_missing"
    OWNER_MISMATCH = "owner_mismatch"
    TURN_KEY_IDENTITY_MISSING = "turn_key_identity_missing"
    TURN_KEY_MISMATCH = "turn_key_mismatch"
    COMPLETED_PHASES_INVALID = "completed_phases_invalid"
    COMPLETED_PHASES_NOT_ORDERED_PREFIX = "completed_phases_not_ordered_prefix"
    JOURNAL_NOT_TERMINAL = "journal_not_terminal"
    JOURNAL_STATUS_UNSUPPORTED = "journal_status_unsupported"


class SettlementStepKind(StrEnum):
    VALIDATION = "validation"
    DURABLE_WRITEBACK = "durable_writeback"
    QUOTA_SPEND = "quota_spend"
    TERMINAL_CLOSEOUT = "terminal_closeout"


class SettlementFailureKind(StrEnum):
    INVALID_IDENTITY = "invalid_identity"
    RECEIPT_MISSING = "receipt_missing"
    IDENTITY_MISMATCH = "identity_mismatch"
    WRITEBACK_MISSING = "writeback_missing"
    WRITEBACK_REJECTED = "writeback_rejected"
    QUOTA_SPEND_REJECTED = "quota_spend_rejected"
    TERMINAL_CLOSEOUT_REJECTED = "terminal_closeout_rejected"
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
    details: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind.value,
            "step_kind": self.step_kind.value,
            "reason": self.reason,
        }
        if self.details:
            result["details"] = dict(self.details)
        return result


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
        details: Mapping[str, Any] | None = None,
    ) -> SettlementResult[T]:
        return cls(
            value=None,
            receipts=receipts,
            failure=SettlementFailure(
                kind=kind,
                step_kind=step_kind,
                reason=reason,
                details=details,
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


def settlement_result_payload(result: SettlementResult[Any]) -> dict[str, Any]:
    return {
        "ok": result.failure is None,
        "receipts": [receipt.as_dict() for receipt in result.receipts],
        "failure": result.failure.as_dict() if result.failure else None,
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _valid_identity_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identity_state(
    required_values: Sequence[Any],
    *,
    optional_values: Sequence[tuple[bool, Any]] = (),
    expected: str | None = None,
) -> tuple[bool, bool]:
    required_complete = all(
        _valid_identity_value(value) for value in required_values
    )
    optional_complete = all(
        not present or _valid_identity_value(value)
        for present, value in optional_values
    )
    expected_complete = expected is None or _valid_identity_value(expected)
    complete = required_complete and optional_complete and expected_complete
    observed = [value for value in required_values if _valid_identity_value(value)]
    observed.extend(
        value
        for present, value in optional_values
        if present and _valid_identity_value(value)
    )
    if expected is not None and _valid_identity_value(expected):
        observed.append(expected)
    return complete, complete and len(set(observed)) == 1


def effect_program_from_ordered_steps(
    ordered_steps: Sequence[Mapping[str, Any]],
    *,
    execution_mode: str | None = None,
) -> EffectProgram:
    """Map existing `guided_transaction.ordered_steps` onto an effect program."""

    steps: list[EffectStep] = []
    for step in ordered_steps:
        if not isinstance(step, Mapping):
            continue
        steps.append(
            EffectStep(
                step_id=str(step.get("id") or "") or None,
                kind=str(step.get("kind") or "") or None,
                command=(
                    str(
                        step.get("command")
                        or step.get("command_template")
                        or step.get("prompt")
                        or ""
                    )
                    or None
                ),
                purpose=str(step.get("purpose") or "") or None,
                raw=dict(step),
            )
        )
    return EffectProgram(
        steps=tuple(steps),
        execution_mode=str(execution_mode or "") or None,
    )


def interpret_quota_should_run_packet(
    packet: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    """Map an existing `quota should-run` packet onto canonical effect slots."""

    interaction = _mapping(packet.get("interaction_contract"))
    lane = _mapping(packet.get("work_lane_contract"))
    scheduler = _mapping(packet.get("scheduler_hint"))
    codex_app = _mapping(scheduler.get("codex_app"))
    ack_hint = _mapping(codex_app.get("ack_hint"))
    failure_hint = _mapping(codex_app.get("failure_hint"))
    cli_channel = _mapping(interaction.get("cli_channel"))
    gate = packet.get("capability_gate")
    protocol = _mapping(packet.get("protocol_action_packet"))

    request = EffectRequest(
        kind="quota_should_run",
        source="agent_or_host",
        goal_id=goal_id,
        agent_id=agent_id,
        capabilities=tuple(capabilities),
    )
    interpretation = EffectInterpretation(
        route=str(lane.get("lane") or ""),
        obligation=str(lane.get("obligation") or ""),
        interaction_mode=str(interaction.get("mode") or ""),
        capability_action=(
            str(gate.get("action")) if isinstance(gate, Mapping) else None
        ),
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
    )
    observation = EffectObservation(
        decision=str(packet.get("decision") or ""),
        should_run=bool(packet.get("should_run")),
        effective_action=str(packet.get("effective_action") or ""),
        recommended_action=str(packet.get("recommended_action") or ""),
        protocol_summary=(
            str(protocol.get("summary")) if protocol.get("summary") else None
        ),
    )
    next_effect = EffectNext(
        cli_actions=tuple(
            str(action)
            for action in cli_channel.get("next_cli_actions", [])
            if str(action).strip()
        ),
        execution_mode=(
            str(
                packet.get("execution_mode")
                or codex_app.get("execution_mode")
                or scheduler.get("execution_mode")
                or None
            )
            or None
        ),
        scheduler_action=str(scheduler.get("action") or None) or None,
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
        ack_cli_args=tuple(
            str(arg)
            for arg in ack_hint.get("cli_args", [])
            if str(arg).strip()
        ),
        failure_cli_args=tuple(
            str(arg)
            for arg in failure_hint.get("cli_args", [])
            if str(arg).strip()
        ),
    )
    return EffectTurn(
        request=request,
        interpretation=interpretation,
        observation=observation,
        next_effect=next_effect,
    )


def interpret_turn_journal(
    journal: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    turn_key: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    """Read one fenced Turn journal through the canonical effect slots."""

    plan = _mapping(journal.get("plan"))
    envelope = _mapping(plan.get("turn_envelope"))
    transaction = _mapping(plan.get("transaction"))
    settlement = _mapping(transaction.get("settlement_plan"))
    identity = _mapping(settlement.get("identity"))
    host_result = _mapping(journal.get("host_result"))
    receipt = _mapping(journal.get("receipt"))

    goal_complete, goal_matches = _identity_state(
        (
            journal.get("goal_id"),
            envelope.get("goal_id"),
            identity.get("goal_id"),
        ),
        expected=goal_id,
    )
    owner_complete, owner_matches = _identity_state(
        (envelope.get("agent_id"), identity.get("agent_id")),
        expected=agent_id,
    )
    turn_key_complete, turn_key_matches = _identity_state(
        (journal.get("turn_key"), transaction.get("turn_key")),
        optional_values=(
            ("turn_key" in host_result, host_result.get("turn_key")),
            ("turn_key" in receipt, receipt.get("turn_key")),
        ),
        expected=turn_key,
    )

    violations: list[TurnJournalViolation] = []
    if not goal_complete:
        violations.append(TurnJournalViolation.GOAL_IDENTITY_MISSING)
    elif not goal_matches:
        violations.append(TurnJournalViolation.GOAL_MISMATCH)
    if not owner_complete:
        violations.append(TurnJournalViolation.OWNER_IDENTITY_MISSING)
    elif not owner_matches:
        violations.append(TurnJournalViolation.OWNER_MISMATCH)
    if not turn_key_complete:
        violations.append(TurnJournalViolation.TURN_KEY_IDENTITY_MISSING)
    elif not turn_key_matches:
        violations.append(TurnJournalViolation.TURN_KEY_MISMATCH)

    raw_completed_phases = journal.get("completed_phases")
    if isinstance(raw_completed_phases, list):
        completed_phases = tuple(str(phase) for phase in raw_completed_phases)
        phases_form_ordered_prefix = completed_phases == TURN_TRANSACTION_PHASES[
            : len(completed_phases)
        ]
        if not phases_form_ordered_prefix:
            violations.append(
                TurnJournalViolation.COMPLETED_PHASES_NOT_ORDERED_PREFIX
            )
    else:
        completed_phases = ()
        phases_form_ordered_prefix = False
        violations.append(TurnJournalViolation.COMPLETED_PHASES_INVALID)

    journal_status = str(journal.get("status") or "")
    tombstone_retained = journal_status in {"committed", "stopped", "failed"}
    if journal_status in {"in_progress", "scheduler_action_required"}:
        violations.append(TurnJournalViolation.JOURNAL_NOT_TERMINAL)
    elif not tombstone_retained:
        violations.append(TurnJournalViolation.JOURNAL_STATUS_UNSUPPORTED)

    replay_legal = not violations
    context = {
        "replay_legal": replay_legal,
        "goal_matches": goal_matches,
        "owner_matches": owner_matches,
        "turn_key_matches": turn_key_matches,
        "phases_form_ordered_prefix": phases_form_ordered_prefix,
        "journal_status": journal_status,
        "tombstone_retained": tombstone_retained,
        "completed_phases": completed_phases,
        "violations": tuple(violation.value for violation in violations),
    }
    return EffectTurn(
        request=EffectRequest(
            kind="turn_journal",
            source="turn_journal",
            goal_id=goal_id,
            agent_id=agent_id,
            capabilities=tuple(capabilities),
            context=context,
        ),
        interpretation=EffectInterpretation(
            route="turn_journal_replay",
            obligation="observe_fenced_replay",
            interaction_mode="read_only",
        ),
        observation=EffectObservation(
            decision="replay_legal" if replay_legal else "replay_blocked",
            should_run=False,
            effective_action=("observe_replay" if replay_legal else "block_replay"),
            recommended_action=(
                "Retain the terminal Turn journal tombstone."
                if replay_legal
                else "Inspect the structured Turn journal violations before replay."
            ),
            protocol_summary=(
                "Turn journal replay is legal and effect-free."
                if replay_legal
                else (
                    "Turn journal replay is blocked by "
                    f"{len(violations)} structured violation(s)."
                )
            ),
        ),
        next_effect=EffectNext(),
    )


def interpret_turn_result_packet(
    packet: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    """Map an existing `loopx_turn_result_v0` packet onto canonical slots."""

    scheduler = _mapping(packet.get("scheduler_hint"))
    codex_app = _mapping(scheduler.get("codex_app"))
    ack_hint = _mapping(codex_app.get("ack_hint"))
    failure_hint = _mapping(codex_app.get("failure_hint"))
    completed_phases = tuple(
        str(phase)
        for phase in packet.get("completed_phases", [])
        if str(phase).strip()
    )
    failed_phase = str(packet.get("failed_phase") or "") or None
    result_kind = str(packet.get("result_kind") or "")

    request = EffectRequest(
        kind="turn_result",
        source="host",
        goal_id=goal_id,
        agent_id=agent_id,
        capabilities=tuple(capabilities),
        context={
            "completed_phases": completed_phases,
            "failed_phase": failed_phase,
            "classification": packet.get("classification"),
            "delivery_outcome": packet.get("delivery_outcome"),
        },
    )
    interpretation = EffectInterpretation(
        route="turn_result_settlement",
        obligation="settle_turn_receipt",
        interaction_mode="host_result",
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
    )
    observation = EffectObservation(
        decision=result_kind,
        should_run=False,
        effective_action=str(packet.get("effective_action") or result_kind),
        recommended_action=(
            str(packet.get("recommended_action") or "")
            or "settle the turn receipt"
        ),
        protocol_summary=(
            str(packet.get("summary")) if packet.get("summary") else None
        ),
    )
    next_effect = EffectNext(
        cli_actions=tuple(
            str(action)
            for action in packet.get("next_cli_actions", [])
            if str(action).strip()
        ),
        execution_mode=(
            str(
                packet.get("execution_mode")
                or codex_app.get("execution_mode")
                or scheduler.get("execution_mode")
                or None
            )
            or None
        ),
        scheduler_action=str(scheduler.get("action") or None) or None,
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
        ack_cli_args=tuple(
            str(arg)
            for arg in ack_hint.get("cli_args", [])
            if str(arg).strip()
        ),
        failure_cli_args=tuple(
            str(arg)
            for arg in failure_hint.get("cli_args", [])
            if str(arg).strip()
        ),
    )
    return EffectTurn(
        request=request,
        interpretation=interpretation,
        observation=observation,
        next_effect=next_effect,
    )

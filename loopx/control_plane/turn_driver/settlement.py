"""Turn-driver adapter for the shared typed settlement receipt-chain driver."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..effect_program import (
    SettlementResult,
    SettlementStepKind,
)
from ..effect_runtime import effect_runtime_result
from ..settlement_driver import decode_settlement_result
from .driver import selected_turn_todo
from .transaction import (
    LoopXTurnResultKind,
    require_loopx_turn_completion_outcome,
)


TurnEffect = Callable[[], Mapping[str, Any]]
TurnSettlementCheckpoint = Callable[
    [SettlementStepKind, Mapping[str, Any], tuple[str, ...]],
    None,
]

TerminalCloseoutCheckpoint = Callable[[Mapping[str, Any]], None]
CompletionIntent = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class TurnSettlementState:
    completed_phases: tuple[str, ...]
    writeback: Mapping[str, Any] | None = None
    quota_spend: Mapping[str, Any] | None = None


TURN_SETTLEMENT_TRANSACTION_SCHEMA_VERSION = "loopx_turn_settlement_transaction_v0"
TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION = "loopx_turn_settlement_reduction_v0"


def completion_writeback_outcome(
    payload: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return the selected Todo's validated durable completion outcome."""

    completion = payload.get("completion")
    if not isinstance(completion, Mapping):
        return None
    envelope = plan.get("turn_envelope")
    selected = selected_turn_todo(envelope) if isinstance(envelope, Mapping) else {}
    try:
        return require_loopx_turn_completion_outcome(
            completion,
            expected_todo_id=str(selected.get("todo_id") or ""),
        )
    except ValueError:
        return None


def terminal_closeout_requirement(
    *,
    plan: Mapping[str, Any],
    result: Mapping[str, Any],
    journal: Mapping[str, Any],
    completion_intent: CompletionIntent,
) -> tuple[bool, str | None]:
    """Classify final no-followup without mutating the Todo frontier."""

    if result.get("result_kind") != LoopXTurnResultKind.VALIDATED_COMPLETION.value:
        return False, None
    stored_terminal = journal.get("terminal_closeout")
    stored_writeback = journal.get("writeback")
    terminal_payload = stored_terminal if isinstance(stored_terminal, Mapping) else {}
    writeback_payload = (
        stored_writeback if isinstance(stored_writeback, Mapping) else {}
    )
    observed_completion = terminal_payload.get("completion") or writeback_payload.get(
        "completion"
    )
    try:
        if not isinstance(observed_completion, Mapping):
            observed_completion = completion_intent(result)
        envelope = plan.get("turn_envelope")
        selected = selected_turn_todo(envelope) if isinstance(envelope, Mapping) else {}
        outcome = require_loopx_turn_completion_outcome(
            observed_completion,
            expected_todo_id=str(selected.get("todo_id") or ""),
        )
    except (TypeError, ValueError) as exc:
        return False, str(exc)
    return outcome["continuation"] == "no_followup", None


def execute_turn_driver_settlement(
    transaction_plan: Mapping[str, Any],
    *,
    transaction_phases: tuple[str, ...],
    completed_phases: Sequence[str],
    writeback_payload: Mapping[str, Any] | None,
    quota_spend_payload: Mapping[str, Any] | None,
    writeback: TurnEffect,
    spend: TurnEffect,
    checkpoint: TurnSettlementCheckpoint,
    committed_effect_id: str | None = None,
    terminal_closeout_required: bool = False,
    terminal_closeout_payload: Mapping[str, Any] | None = None,
    terminal_closeout: TurnEffect | None = None,
    terminal_checkpoint: TerminalCloseoutCheckpoint | None = None,
) -> SettlementResult[TurnSettlementState]:
    """Run external effect providers and reduce one complete Turn settlement.

    TypeScript first validates identity, replay, and the committed journal
    prefix, then authorizes the still-Python providers in order. Python invokes
    and checkpoints those opaque outcomes before a final TypeScript reduction
    owns failure classification, receipts, and the canonical result. A replay
    with no pending provider completes in the first reduction.
    """
    phases = tuple(str(phase) for phase in completed_phases)
    writeback_value = writeback_payload
    spend_value = quota_spend_payload
    terminal_value = terminal_closeout_payload
    failed_attempt: tuple[SettlementStepKind, Mapping[str, Any]] | None = None

    def committed(payload: Mapping[str, Any]) -> bool:
        # This transport guard only prevents a later provider from running
        # after an earlier provider rejected. TS remains authoritative for the
        # typed failure kind, receipt chain, and final settlement result.
        return payload.get("ok") is True and payload.get("appended") is True

    def reduce() -> Mapping[str, Any]:
        payload = effect_runtime_result(
            "turn.settlement.reduce",
            {
                "schema_version": TURN_SETTLEMENT_TRANSACTION_SCHEMA_VERSION,
                "transaction_plan": dict(transaction_plan),
                "transaction_phases": list(transaction_phases),
                "completed_phases": list(phases),
                "committed_effect_id": committed_effect_id,
                "writeback_payload": (
                    dict(writeback_value)
                    if isinstance(writeback_value, Mapping)
                    else None
                ),
                "quota_spend_payload": (
                    dict(spend_value) if isinstance(spend_value, Mapping) else None
                ),
                "terminal_closeout_required": terminal_closeout_required,
                "terminal_closeout_payload": (
                    dict(terminal_value)
                    if isinstance(terminal_value, Mapping)
                    else None
                ),
                "failed_provider_attempt": (
                    {
                        "step_kind": failed_attempt[0].value,
                        "payload": dict(failed_attempt[1]),
                    }
                    if failed_attempt is not None
                    else None
                ),
            },
        )
        if (
            not isinstance(payload, Mapping)
            or payload.get("schema_version") != TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION
        ):
            raise RuntimeError("TypeScript Turn settlement reduction shape mismatch")
        return payload

    reduction = reduce()
    decision = str(reduction.get("decision") or "")
    if decision == "execute":
        provider_effects = reduction.get("provider_effects")
        if not isinstance(provider_effects, list) or not provider_effects:
            raise RuntimeError("TypeScript Turn settlement provider plan is empty")
        providers = {
            SettlementStepKind.DURABLE_WRITEBACK: writeback,
            SettlementStepKind.QUOTA_SPEND: spend,
        }
        for raw_effect in provider_effects:
            if not isinstance(raw_effect, Mapping):
                raise RuntimeError("TypeScript Turn settlement provider shape mismatch")
            step_kind = SettlementStepKind(str(raw_effect.get("step_kind") or ""))
            raw_phases = raw_effect.get("completed_phases")
            if not isinstance(raw_phases, list):
                raise RuntimeError("TypeScript Turn settlement phases shape mismatch")
            authorized_phases = tuple(str(phase) for phase in raw_phases)
            if step_kind is SettlementStepKind.TERMINAL_CLOSEOUT:
                if terminal_closeout is None or terminal_checkpoint is None:
                    raise ValueError(
                        "terminal closeout requires an effect provider and checkpoint"
                    )
                observed = dict(terminal_closeout())
                if committed(observed):
                    terminal_value = observed
                    terminal_checkpoint(observed)
                else:
                    failed_attempt = (step_kind, observed)
                    break
                continue

            observed = dict(providers[step_kind]())
            if not committed(observed):
                failed_attempt = (step_kind, observed)
                break
            phases = authorized_phases
            checkpoint(step_kind, observed, phases)
            if step_kind is SettlementStepKind.DURABLE_WRITEBACK:
                writeback_value = observed
            else:
                spend_value = observed
        reduction = reduce()
        decision = str(reduction.get("decision") or "")

    if decision not in {"complete", "failed"}:
        raise RuntimeError("TypeScript Turn settlement did not reach an outcome")

    def decode_state(value: Any) -> TurnSettlementState:
        if not isinstance(value, Mapping):
            raise RuntimeError("TypeScript Turn settlement state shape mismatch")
        completed = value.get("completed_phases")
        if not isinstance(completed, list):
            raise RuntimeError("TypeScript Turn settlement phases shape mismatch")
        raw_writeback = value.get("writeback")
        raw_spend = value.get("quota_spend")
        return TurnSettlementState(
            completed_phases=tuple(str(phase) for phase in completed),
            writeback=(
                dict(raw_writeback) if isinstance(raw_writeback, Mapping) else None
            ),
            quota_spend=(dict(raw_spend) if isinstance(raw_spend, Mapping) else None),
        )

    projection = reduction.get("settlement_result")
    return decode_settlement_result(
        reduction.get("result"),
        value_decoder=decode_state,
        projection_payload=(projection if isinstance(projection, Mapping) else None),
    )

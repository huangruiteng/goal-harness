"""Turn-driver adapter for the shared typed settlement receipt-chain driver."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..effect_program import (
    SettlementResult,
    SettlementStepKind,
)
from ..settlement_driver import (
    commit_step_effect,
    require_matching_effect_id,
    seed_committed_steps,
    settlement_identity_from_plan,
)
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


SETTLEMENT_STEPS = (
    SettlementStepKind.VALIDATION,
    SettlementStepKind.DURABLE_WRITEBACK,
    SettlementStepKind.QUOTA_SPEND,
)

TERMINAL_SETTLEMENT_STEPS = (
    SettlementStepKind.VALIDATION.value,
    SettlementStepKind.DURABLE_WRITEBACK.value,
    SettlementStepKind.QUOTA_SPEND.value,
    SettlementStepKind.TERMINAL_CLOSEOUT.value,
)


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
    writeback_payload = stored_writeback if isinstance(stored_writeback, Mapping) else {}
    observed_completion = terminal_payload.get("completion") or writeback_payload.get(
        "completion"
    )
    try:
        if not isinstance(observed_completion, Mapping):
            observed_completion = completion_intent(result)
        envelope = plan.get("turn_envelope")
        selected = (
            selected_turn_todo(envelope) if isinstance(envelope, Mapping) else {}
        )
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
) -> SettlementResult[TurnSettlementState]:
    """Bind validation -> writeback -> spend for the isolated Turn adapter.

    ``committed_effect_id`` is the settlement effect id under which an
    existing journal committed its receipts. When a journal is present, a
    caller must prove that the committed receipts belong to the current plan's
    settlement identity; otherwise a key/owner-mismatched replay would
    re-attribute the committed validation/writeback/spend receipts to a
    different effect while skipping its effects. A ``None`` provenance
    keeps legacy plans and direct callers that have no journal readback
    unchanged.
    """

    identity_result = settlement_identity_from_plan(transaction_plan)
    if identity_result.failure is not None:
        return identity_result
    identity = identity_result.value
    assert identity is not None
    matched = require_matching_effect_id(committed_effect_id, identity.effect_id)
    if matched.failure is not None:
        return SettlementResult.failed(
            kind=matched.failure.kind,
            step_kind=matched.failure.step_kind,
            reason=matched.failure.reason,
        )
    phases = tuple(str(phase) for phase in completed_phases)
    committed_payloads: dict[SettlementStepKind, Mapping[str, Any] | None] = {
        SettlementStepKind.VALIDATION: {},
        SettlementStepKind.DURABLE_WRITEBACK: writeback_payload,
        SettlementStepKind.QUOTA_SPEND: quota_spend_payload,
    }
    seeded = seed_committed_steps(
        identity,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=committed_payloads,
        completed_phases=phases,
        transaction_phases=transaction_phases,
        require_validation=True,
        source_ref_prefix="turn_journal",
    )
    if seeded.failure is not None:
        return SettlementResult.failed(
            kind=seeded.failure.kind,
            step_kind=seeded.failure.step_kind,
            reason=seeded.failure.reason,
            receipts=seeded.receipts,
        )
    state = TurnSettlementState(
        completed_phases=phases,
        writeback=writeback_payload,
        quota_spend=quota_spend_payload,
    )
    receipts = list(seeded.receipts)
    if "durable_writeback" not in phases:
        step_result = commit_step_effect(
            identity,
            step_kind=SettlementStepKind.DURABLE_WRITEBACK,
            transaction_phases=transaction_phases,
            effect=writeback,
            checkpoint=checkpoint,
        )
        if step_result.failure is not None:
            return SettlementResult.failed(
                kind=step_result.failure.kind,
                step_kind=step_result.failure.step_kind,
                reason=step_result.failure.reason,
                receipts=tuple(receipts),
            )
        receipts.extend(step_result.receipts)
        phase_index = transaction_phases.index(
            SettlementStepKind.DURABLE_WRITEBACK.value
        )
        state = TurnSettlementState(
            completed_phases=tuple(transaction_phases[: phase_index + 1]),
            writeback=step_result.value,
            quota_spend=state.quota_spend,
        )
    if "quota_spend" not in phases:
        step_result = commit_step_effect(
            identity,
            step_kind=SettlementStepKind.QUOTA_SPEND,
            transaction_phases=transaction_phases,
            effect=spend,
            checkpoint=checkpoint,
        )
        if step_result.failure is not None:
            return SettlementResult.failed(
                kind=step_result.failure.kind,
                step_kind=step_result.failure.step_kind,
                reason=step_result.failure.reason,
                receipts=tuple(receipts),
            )
        receipts.extend(step_result.receipts)
        phase_index = transaction_phases.index(SettlementStepKind.QUOTA_SPEND.value)
        state = TurnSettlementState(
            completed_phases=tuple(transaction_phases[: phase_index + 1]),
            writeback=state.writeback,
            quota_spend=step_result.value,
        )
    return SettlementResult.pure(state, receipts=tuple(receipts))


def execute_turn_terminal_closeout(
    transaction_plan: Mapping[str, Any],
    *,
    committed_payload: Mapping[str, Any] | None,
    closeout: TurnEffect,
    checkpoint: TerminalCloseoutCheckpoint,
    committed_effect_id: str | None = None,
) -> SettlementResult[Mapping[str, Any]]:
    """Commit or replay the terminal closeout after durable spend.

    Terminal no-follow-up is intentionally outside the base writeback/spend
    driver because ordinary progress has no closeout effect.  The typed plan
    still owns its order and identity; this helper adds the matching receipt
    without weakening the Turn transaction's journal-prefix contract.
    """

    identity_result = settlement_identity_from_plan(transaction_plan)
    if identity_result.failure is not None:
        return identity_result
    identity = identity_result.value
    assert identity is not None
    matched = require_matching_effect_id(committed_effect_id, identity.effect_id)
    if matched.failure is not None:
        return SettlementResult.failed(
            kind=matched.failure.kind,
            step_kind=matched.failure.step_kind,
            reason=matched.failure.reason,
        )
    if committed_payload is not None:
        seeded = seed_committed_steps(
            identity,
            ordered_steps=(SettlementStepKind.TERMINAL_CLOSEOUT,),
            committed_payloads={
                SettlementStepKind.TERMINAL_CLOSEOUT: committed_payload,
            },
            completed_phases=(SettlementStepKind.TERMINAL_CLOSEOUT.value,),
            transaction_phases=(SettlementStepKind.TERMINAL_CLOSEOUT.value,),
            require_validation=False,
            source_ref_prefix="turn_journal",
        )
        if seeded.failure is not None:
            return SettlementResult.failed(
                kind=seeded.failure.kind,
                step_kind=seeded.failure.step_kind,
                reason=seeded.failure.reason,
                receipts=seeded.receipts,
            )
        return SettlementResult.pure(
            committed_payload,
            receipts=seeded.receipts,
        )

    result: SettlementResult[Mapping[str, Any]] = commit_step_effect(
        identity,
        step_kind=SettlementStepKind.TERMINAL_CLOSEOUT,
        transaction_phases=TERMINAL_SETTLEMENT_STEPS,
        effect=closeout,
        checkpoint=lambda _step, payload, _phases: checkpoint(payload),
    )
    return result


def execute_verified_turn_terminal_closeout(
    transaction_plan: Mapping[str, Any],
    *,
    plan: Mapping[str, Any],
    committed_payload: Mapping[str, Any] | None,
    closeout: TurnEffect,
    checkpoint: TerminalCloseoutCheckpoint,
    committed_effect_id: str | None = None,
) -> SettlementResult[Mapping[str, Any]]:
    """Commit a terminal effect only when it durably proves no-followup."""

    def verified_closeout() -> Mapping[str, Any]:
        callback_payload = closeout()
        outcome = completion_writeback_outcome(callback_payload, plan=plan)
        if outcome is None or outcome.get("continuation") != "no_followup":
            return {
                "ok": False,
                "appended": False,
                "reason": (
                    "terminal closeout adapter did not durably record the "
                    "selected Todo as no_followup"
                ),
            }
        return {**callback_payload, "completion": outcome}

    return execute_turn_terminal_closeout(
        transaction_plan,
        committed_payload=committed_payload,
        closeout=verified_closeout,
        checkpoint=checkpoint,
        committed_effect_id=committed_effect_id,
    )

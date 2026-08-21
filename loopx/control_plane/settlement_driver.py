"""Core-owned typed settlement receipt-chain driver.

Quota and Turn adapters both settle a typed plan under one identity: validation
first, then writeback, then spend, replaying committed receipts for the same
effect id with every failure typed by step.  This module owns that shared
receipt-chain semantics; adapters keep their provenance reads, effect bindings,
and domain policy (scheduler, Todo lifecycle, spend accounting, vision).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .effect_program import (
    SettlementEffectResolution,
    SettlementEffectResolutionKind,
    SettlementFailureKind,
    SettlementIdentity,
    SettlementReceipt,
    SettlementResult,
    SettlementStepKind,
)


SettlementPayload = Mapping[str, Any]
SettlementEffect = Callable[[str], Mapping[str, Any]]
SettlementEffectPrepare = Callable[[SettlementStepKind, str], None]
SettlementEffectAbort = Callable[[SettlementStepKind, str], None]
SettlementEffectResolver = Callable[[str], SettlementEffectResolution]
SettlementCheckpoint = Callable[
    [SettlementStepKind, Mapping[str, Any], tuple[str, ...]],
    None,
]

DEFAULT_MISSING_FAILURE_KINDS: Mapping[SettlementStepKind, SettlementFailureKind] = {
    SettlementStepKind.DURABLE_WRITEBACK: SettlementFailureKind.RECEIPT_MISSING,
}
MISSING_PAYLOAD_REASONS: Mapping[SettlementStepKind, str] = {
    SettlementStepKind.DURABLE_WRITEBACK: (
        "Turn journal is missing its committed writeback payload"
    ),
    SettlementStepKind.QUOTA_SPEND: (
        "Turn journal is missing its committed quota spend payload"
    ),
}


def effect_ids_match(
    committed_effect_id: str | None,
    expected_effect_id: str,
) -> bool:
    """Return whether committed receipts prove the expected effect id."""

    return not committed_effect_id or committed_effect_id == expected_effect_id


def settlement_receipt(
    identity: SettlementIdentity,
    *,
    step_kind: SettlementStepKind,
    source_ref: str | None = None,
) -> SettlementReceipt:
    """Build one committed receipt for a settlement identity and step."""

    return SettlementReceipt(
        step_kind=step_kind,
        status="committed",
        effect_id=identity.effect_id,
        source_ref=source_ref,
    )


def settlement_effect_ref(
    identity: SettlementIdentity,
    step_kind: SettlementStepKind,
) -> str:
    """Return the stable provider idempotency key for one settlement step."""

    return f"{identity.effect_id}#{step_kind.value}"


def settlement_identity_from_plan(
    transaction_plan: Mapping[str, Any],
) -> SettlementResult[SettlementIdentity]:
    """Resolve the complete typed settlement identity from a transaction plan."""

    settlement_plan = transaction_plan.get("settlement_plan")
    if not isinstance(settlement_plan, Mapping):
        return SettlementResult.failed(
            kind=SettlementFailureKind.RECEIPT_MISSING,
            step_kind=SettlementStepKind.VALIDATION,
            reason="Turn transaction has no typed settlement plan",
        )
    identity = settlement_plan.get("identity")
    if not isinstance(identity, Mapping):
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason="Turn settlement plan has no identity",
        )
    required = ("goal_id", "agent_id", "turn_instance_id")
    if any(not str(identity.get(field) or "").strip() for field in required):
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason="Turn settlement plan has an incomplete identity",
        )
    if bool(str(identity.get("todo_id") or "").strip()) == bool(
        str(identity.get("replan_obligation_id") or "").strip()
    ):
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=(
                "Turn settlement plan requires exactly one Todo or autonomous "
                "replan obligation binding"
            ),
        )
    try:
        built = SettlementIdentity(
            goal_id=str(identity["goal_id"]),
            agent_id=str(identity["agent_id"]),
            todo_id=str(identity.get("todo_id") or "") or None,
            turn_instance_id=str(identity["turn_instance_id"]),
            replan_obligation_id=(
                str(identity.get("replan_obligation_id") or "") or None
            ),
        )
    except ValueError as exc:
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
        )
    effect_id = str(identity.get("effect_id") or "").strip()
    if not effect_id:
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason="Turn settlement plan has no effect id",
        )
    if effect_id and effect_id != built.effect_id:
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason="Turn settlement plan effect id does not match its identity",
        )
    return SettlementResult.pure(
        built,
    )


def require_matching_effect_id(
    committed_effect_id: str | None,
    expected_effect_id: str,
) -> SettlementResult[str]:
    """Fail closed when committed receipts belong to another effect id."""

    if not effect_ids_match(committed_effect_id, expected_effect_id):
        return SettlementResult.failed(
            kind=SettlementFailureKind.IDENTITY_MISMATCH,
            step_kind=SettlementStepKind.VALIDATION,
            reason=(
                "Turn journal belongs to another settlement effect: journal "
                f"effect is {committed_effect_id} but plan effect is "
                f"{expected_effect_id}"
            ),
        )
    return SettlementResult.pure(expected_effect_id)


def is_committed_payload(value: Mapping[str, Any] | None) -> bool:
    """Return whether a step payload durably committed its effect."""

    return bool(
        isinstance(value, Mapping)
        and value.get("ok") is True
        and value.get("appended") is True
    )


def seed_committed_steps(
    identity: SettlementIdentity,
    *,
    ordered_steps: Sequence[SettlementStepKind],
    committed_payloads: Mapping[SettlementStepKind, Mapping[str, Any] | None],
    completed_phases: Sequence[str] | None = None,
    transaction_phases: Sequence[str] | None = None,
    require_validation: bool = True,
    missing_failure_kinds: Mapping[SettlementStepKind, SettlementFailureKind]
    | None = None,
    source_ref_prefix: str = "turn_journal",
) -> SettlementResult[dict[SettlementStepKind, Mapping[str, Any]]]:
    """Seed committed receipts in plan order from durable step payloads."""

    if completed_phases is not None and transaction_phases is not None:
        phases = tuple(str(phase) for phase in completed_phases)
        if phases != tuple(transaction_phases)[: len(phases)]:
            return SettlementResult.failed(
                kind=SettlementFailureKind.RECEIPT_MISSING,
                step_kind=SettlementStepKind.VALIDATION,
                reason="Turn journal phases are not an ordered transaction prefix",
            )
        if require_validation and "validation" not in phases:
            return SettlementResult.failed(
                kind=SettlementFailureKind.RECEIPT_MISSING,
                step_kind=SettlementStepKind.VALIDATION,
                reason="Turn settlement requires a committed validation receipt",
            )
    missing_kinds = dict(DEFAULT_MISSING_FAILURE_KINDS)
    if missing_failure_kinds:
        missing_kinds.update(missing_failure_kinds)
    receipts: list[SettlementReceipt] = []
    committed: dict[SettlementStepKind, Mapping[str, Any]] = {}
    for step_kind in ordered_steps:
        if step_kind is SettlementStepKind.VALIDATION and require_validation:
            if completed_phases is not None and "validation" not in completed_phases:
                return SettlementResult.failed(
                    kind=SettlementFailureKind.RECEIPT_MISSING,
                    step_kind=step_kind,
                    reason="Turn settlement requires a committed validation receipt",
                    receipts=tuple(receipts),
                )
            receipts.append(
                settlement_receipt(
                    identity,
                    step_kind=step_kind,
                    source_ref=(
                        f"{source_ref_prefix}:{identity.effect_id}#{step_kind.value}"
                    ),
                )
            )
            committed[step_kind] = {}
            continue
        if completed_phases is not None:
            committed_flag = step_kind.value in completed_phases
        else:
            committed_flag = True
        if not committed_flag:
            # Pending step: not yet committed; the caller may run its effect.
            continue
        payload = committed_payloads.get(step_kind)
        if payload is None:
            return SettlementResult.failed(
                kind=missing_kinds.get(step_kind, SettlementFailureKind.RECEIPT_MISSING),
                step_kind=step_kind,
                reason=MISSING_PAYLOAD_REASONS.get(
                    step_kind,
                    f"Turn journal is missing its committed {step_kind.value} payload",
                ),
                receipts=tuple(receipts),
            )
        if not is_committed_payload(payload):
            return SettlementResult.failed(
                kind=missing_kinds.get(step_kind, SettlementFailureKind.RECEIPT_MISSING),
                step_kind=step_kind,
                reason=MISSING_PAYLOAD_REASONS.get(
                    step_kind,
                    f"Turn journal is missing its committed {step_kind.value} payload",
                ),
                receipts=tuple(receipts),
            )
        receipts.append(
            settlement_receipt(
                identity,
                step_kind=step_kind,
                source_ref=f"{source_ref_prefix}:{identity.effect_id}#{step_kind.value}",
            )
        )
        committed[step_kind] = payload
    return SettlementResult.pure(committed, receipts=tuple(receipts))


def _callback_failure_kind(
    step_kind: SettlementStepKind,
    reason: str,
) -> SettlementFailureKind:
    if step_kind is SettlementStepKind.DURABLE_WRITEBACK:
        return SettlementFailureKind.WRITEBACK_REJECTED
    if step_kind is SettlementStepKind.TERMINAL_CLOSEOUT:
        return SettlementFailureKind.TERMINAL_CLOSEOUT_REJECTED
    if "budget" in reason.casefold():
        return SettlementFailureKind.BUDGET_REJECTED
    return SettlementFailureKind.QUOTA_SPEND_REJECTED


def commit_step_effect(
    identity: SettlementIdentity,
    *,
    step_kind: SettlementStepKind,
    transaction_phases: Sequence[str],
    effect: SettlementEffect,
    checkpoint: SettlementCheckpoint,
    prepare: SettlementEffectPrepare | None = None,
    abort: SettlementEffectAbort | None = None,
    prepared_effect_ref: str | None = None,
    resolve: SettlementEffectResolver | None = None,
    source_ref_prefix: str = "turn_journal",
) -> SettlementResult[Mapping[str, Any]]:
    """Resolve or run one idempotent step effect and record its receipt."""

    effect_ref = settlement_effect_ref(identity, step_kind)
    if prepared_effect_ref is not None:
        if prepared_effect_ref != effect_ref:
            return SettlementResult.failed(
                kind=SettlementFailureKind.IDENTITY_MISMATCH,
                step_kind=step_kind,
                reason=(
                    "prepared settlement effect does not match the current "
                    f"operation: journal effect is {prepared_effect_ref} but "
                    f"plan effect is {effect_ref}"
                ),
            )
        if resolve is None:
            return SettlementResult.failed(
                kind=SettlementFailureKind.EFFECT_OUTCOME_UNKNOWN,
                step_kind=step_kind,
                reason=(
                    "prepared settlement effect has no provider readback; "
                    "refusing to replay an ambiguous external effect"
                ),
            )
        resolution = resolve(effect_ref)
        if resolution.kind is SettlementEffectResolutionKind.UNKNOWN:
            return SettlementResult.failed(
                kind=SettlementFailureKind.EFFECT_OUTCOME_UNKNOWN,
                step_kind=step_kind,
                reason=(
                    resolution.reason
                    or "provider could not resolve the prepared settlement effect"
                ),
            )
        if resolution.kind is SettlementEffectResolutionKind.COMMITTED:
            payload = dict(resolution.payload or {})
            if not is_committed_payload(payload):
                return SettlementResult.failed(
                    kind=SettlementFailureKind.RECEIPT_MISSING,
                    step_kind=step_kind,
                    reason=(
                        "provider reported a committed settlement effect without "
                        "a durable committed payload"
                    ),
                )
            phase_index = tuple(transaction_phases).index(step_kind.value)
            completed_phases = tuple(transaction_phases)[: phase_index + 1]
            checkpoint(step_kind, payload, completed_phases)
            return SettlementResult.pure(
                payload,
                receipts=(
                    settlement_receipt(
                        identity,
                        step_kind=step_kind,
                        source_ref=f"{source_ref_prefix}:{effect_ref}",
                    ),
                ),
            )
        if resolution.kind is not SettlementEffectResolutionKind.ABSENT:
            return SettlementResult.failed(
                kind=SettlementFailureKind.EFFECT_OUTCOME_UNKNOWN,
                step_kind=step_kind,
                reason="provider returned an unsupported effect resolution state",
            )

    if prepared_effect_ref is None and prepare is not None:
        prepare(step_kind, effect_ref)
    payload = dict(effect(effect_ref))
    if not is_committed_payload(payload):
        if abort is not None:
            abort(step_kind, effect_ref)
        reason = str(
            payload.get("error")
            or payload.get("reason")
            or f"{step_kind.value} callback rejected the settlement"
        )
        return SettlementResult.failed(
            kind=_callback_failure_kind(step_kind, reason),
            step_kind=step_kind,
            reason=reason,
        )
    phase_index = tuple(transaction_phases).index(step_kind.value)
    completed_phases = tuple(transaction_phases)[: phase_index + 1]
    checkpoint(step_kind, payload, completed_phases)
    return SettlementResult.pure(
        payload,
        receipts=(
            settlement_receipt(
                identity,
                step_kind=step_kind,
                source_ref=f"{source_ref_prefix}:{effect_ref}",
            ),
        ),
    )

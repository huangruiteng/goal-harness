"""Python callback adapter for the TS-owned Effect settlement runtime.

The TypeScript runtime owns identity, receipt, replay, ordering, phase advance,
and failure classification. Python remains only where an existing bounded
context still supplies an external callback; it submits the callback result to
the TS reducer before checkpointing it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .effect_program import (
    SettlementFailure,
    SettlementFailureKind,
    SettlementIdentity,
    SettlementReceipt,
    SettlementResult,
    SettlementStepKind,
)
from .effect_runtime import effect_runtime_result


SettlementPayload = Mapping[str, Any]
SettlementEffect = Callable[[], Mapping[str, Any]]
SettlementCheckpoint = Callable[
    [SettlementStepKind, Mapping[str, Any], tuple[str, ...]],
    None,
]

def _identity_payload(identity: SettlementIdentity) -> dict[str, Any]:
    return identity.as_dict()


def _receipt_from_payload(payload: Mapping[str, Any]) -> SettlementReceipt:
    return SettlementReceipt(
        step_kind=SettlementStepKind(str(payload["step_kind"])),
        status=str(payload["status"]),
        effect_id=str(payload["effect_id"]),
        source_ref=str(payload.get("source_ref") or "") or None,
    )


def _result_from_payload(
    payload: Any,
    *,
    value_decoder: Callable[[Any], Any] | None = None,
) -> SettlementResult[Any]:
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript settlement result shape mismatch")
    receipts_value = payload.get("receipts")
    receipts = tuple(
        _receipt_from_payload(receipt)
        for receipt in receipts_value
        if isinstance(receipt, Mapping)
    ) if isinstance(receipts_value, list) else ()
    failure_value = payload.get("failure")
    failure = None
    if isinstance(failure_value, Mapping):
        details = failure_value.get("details")
        failure = SettlementFailure(
            kind=SettlementFailureKind(str(failure_value["kind"])),
            step_kind=SettlementStepKind(str(failure_value["step_kind"])),
            reason=str(failure_value["reason"]),
            details=dict(details) if isinstance(details, Mapping) else None,
        )
    value = payload.get("value")
    if value_decoder is not None and value is not None:
        value = value_decoder(value)
    return SettlementResult(value=value, receipts=receipts, failure=failure)


def effect_ids_match(
    committed_effect_id: str | None,
    expected_effect_id: str,
) -> bool:
    """Return whether committed receipts prove the expected effect id."""

    return bool(
        effect_runtime_result(
            "settlement.effect_ids_match",
            {
                "committed_effect_id": committed_effect_id,
                "expected_effect_id": expected_effect_id,
            },
        )
    )


def settlement_receipt(
    identity: SettlementIdentity,
    *,
    step_kind: SettlementStepKind,
    source_ref: str | None = None,
) -> SettlementReceipt:
    """Build one committed receipt for a settlement identity and step."""

    payload = effect_runtime_result(
        "settlement.receipt",
        {
            "identity": _identity_payload(identity),
            "step_kind": step_kind.value,
            "source_ref": source_ref,
        },
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript settlement receipt shape mismatch")
    return _receipt_from_payload(payload)


def settlement_identity_from_plan(
    transaction_plan: Mapping[str, Any],
) -> SettlementResult[SettlementIdentity]:
    """Resolve the complete typed settlement identity from a transaction plan."""

    def decode_identity(value: Any) -> SettlementIdentity:
        if not isinstance(value, Mapping):
            raise RuntimeError("TypeScript settlement identity shape mismatch")
        return SettlementIdentity(
            goal_id=str(value["goal_id"]),
            agent_id=str(value["agent_id"]),
            todo_id=str(value.get("todo_id") or "") or None,
            turn_instance_id=str(value["turn_instance_id"]),
            replan_obligation_id=(
                str(value.get("replan_obligation_id") or "") or None
            ),
        )

    return _result_from_payload(
        effect_runtime_result("settlement.identity_from_plan", transaction_plan),
        value_decoder=decode_identity,
    )


def require_matching_effect_id(
    committed_effect_id: str | None,
    expected_effect_id: str,
) -> SettlementResult[str]:
    """Fail closed when committed receipts belong to another effect id."""

    return _result_from_payload(
        effect_runtime_result(
            "settlement.match_effect",
            {
                "committed_effect_id": committed_effect_id,
                "expected_effect_id": expected_effect_id,
            },
        )
    )


def is_committed_payload(value: Mapping[str, Any] | None) -> bool:
    """Return whether a step payload durably committed its effect."""

    return bool(
        effect_runtime_result(
            "settlement.is_committed_payload",
            {"payload": dict(value) if isinstance(value, Mapping) else value},
        )
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

    serialized_payloads = {
        step_kind.value: dict(payload) if isinstance(payload, Mapping) else payload
        for step_kind, payload in committed_payloads.items()
    }
    result = effect_runtime_result(
        "settlement.seed",
        {
            "identity": _identity_payload(identity),
            "ordered_steps": [step.value for step in ordered_steps],
            "committed_payloads": serialized_payloads,
            "completed_phases": list(completed_phases) if completed_phases is not None else None,
            "transaction_phases": list(transaction_phases) if transaction_phases is not None else None,
            "require_validation": require_validation,
            "missing_failure_kinds": {
                step.value: kind.value
                for step, kind in (missing_failure_kinds or {}).items()
            },
            "source_ref_prefix": source_ref_prefix,
        },
    )
    return _result_from_payload(result)


def settlement_next_action(
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
) -> tuple[str, SettlementStepKind | None, SettlementResult[Any]]:
    """Ask the TS runtime which typed settlement effect is runnable next."""

    payload = effect_runtime_result(
        "settlement.next_action",
        {
            "identity": _identity_payload(identity),
            "ordered_steps": [step.value for step in ordered_steps],
            "committed_payloads": {
                step.value: dict(value) if isinstance(value, Mapping) else value
                for step, value in committed_payloads.items()
            },
            "completed_phases": list(completed_phases) if completed_phases is not None else None,
            "transaction_phases": list(transaction_phases) if transaction_phases is not None else None,
            "require_validation": require_validation,
            "missing_failure_kinds": {
                step.value: kind.value
                for step, kind in (missing_failure_kinds or {}).items()
            },
            "source_ref_prefix": source_ref_prefix,
        },
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript settlement next-action shape mismatch")
    decision = str(payload.get("decision") or "")
    if decision not in {"failed", "execute", "complete"}:
        raise RuntimeError("TypeScript settlement next-action decision mismatch")
    raw_step = payload.get("step_kind")
    step_kind = SettlementStepKind(str(raw_step)) if raw_step is not None else None
    return decision, step_kind, _result_from_payload(payload.get("result"))


def commit_step_effect(
    identity: SettlementIdentity,
    *,
    step_kind: SettlementStepKind,
    transaction_phases: Sequence[str],
    effect: SettlementEffect,
    checkpoint: SettlementCheckpoint,
    source_ref_prefix: str = "turn_journal",
) -> SettlementResult[Mapping[str, Any]]:
    """Run one step effect and record its committed receipt."""

    payload = dict(effect())
    reduction = effect_runtime_result(
        "settlement.commit_reduction",
        {
            "identity": _identity_payload(identity),
            "step_kind": step_kind.value,
            "transaction_phases": list(transaction_phases),
            "payload": payload,
            "source_ref_prefix": source_ref_prefix,
        },
    )
    if not isinstance(reduction, Mapping):
        raise RuntimeError("TypeScript settlement reduction shape mismatch")
    result = _result_from_payload(reduction.get("result"))
    completed = reduction.get("completed_phases")
    if result.failure is None:
        if not isinstance(completed, list):
            raise RuntimeError("TypeScript settlement reduction has no phase prefix")
        checkpoint(step_kind, payload, tuple(str(phase) for phase in completed))
    return result

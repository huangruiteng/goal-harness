"""Python callback adapter for the TS-owned Effect settlement runtime.

The TypeScript runtime owns identity, receipt, replay, ordering, phase advance,
and failure classification. Python remains only where an existing bounded
context still supplies an external callback; it submits the callback result to
the TS reducer before checkpointing it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
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


def _identity_payload(identity: SettlementIdentity) -> dict[str, Any]:
    return identity.as_dict()


def _receipt_from_payload(payload: Mapping[str, Any]) -> SettlementReceipt:
    return SettlementReceipt(
        step_kind=SettlementStepKind(str(payload["step_kind"])),
        status=str(payload["status"]),
        effect_id=str(payload["effect_id"]),
        source_ref=str(payload.get("source_ref") or "") or None,
    )


def decode_settlement_result(
    payload: Any,
    *,
    value_decoder: Callable[[Any], Any] | None = None,
    projection_payload: Mapping[str, Any] | None = None,
) -> SettlementResult[Any]:
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript settlement result shape mismatch")
    receipts_value = payload.get("receipts")
    receipts = (
        tuple(
            _receipt_from_payload(receipt)
            for receipt in receipts_value
            if isinstance(receipt, Mapping)
        )
        if isinstance(receipts_value, list)
        else ()
    )
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
    return SettlementResult(
        value=value,
        receipts=receipts,
        failure=failure,
        _runtime_payload=(
            dict(projection_payload)
            if isinstance(projection_payload, Mapping)
            else None
        ),
    )


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

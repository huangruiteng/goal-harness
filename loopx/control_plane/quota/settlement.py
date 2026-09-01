from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from ..settlement_driver import decode_settlement_result
from .effect_program import (
    SETTLEMENT_IDENTITY_SCHEMA_VERSION,
    SETTLEMENT_PLAN_SCHEMA_VERSION,
    SETTLEMENT_RECEIPT_SCHEMA_VERSION,
    SettlementFailure,
    SettlementFailureKind,
    SettlementIdentity,
    SettlementPlan,
    SettlementReceipt,
    SettlementResult,
    SettlementStep,
    SettlementStepKind,
    ReceiptBoundMonitorPhase,
    ReceiptBoundReplayPhase,
    build_codex_app_settlement_plan,
    build_turn_scoped_cli_settlement_plan,
    settlement_binding_args,
    settlement_result_payload,
    settlement_step_command,
)

QUOTA_SETTLEMENT_READBACK_REQUEST_SCHEMA = (
    "loopx_quota_settlement_readback_request_v0"
)
QUOTA_SETTLEMENT_READBACK_RESULT_SCHEMA = (
    "loopx_quota_settlement_readback_result_v0"
)


@dataclass(frozen=True, slots=True)
class QuotaSettlementReadback:
    identity: SettlementResult[SettlementIdentity]
    writeback: SettlementResult[dict[str, Any]]
    spend: SettlementResult[dict[str, Any]]
    delivery: SettlementResult[dict[str, Any]]
    settlement: SettlementResult[dict[str, Any]]
    terminal_closeout: SettlementResult[dict[str, Any]]
    terminal_settlement: SettlementResult[dict[str, Any]]
    workspace_causality: dict[str, str] | None
    writeback_run: dict[str, Any] | None
    spend_run: dict[str, Any] | None
    heartbeat_receipt: dict[str, Any] | None
    writeback_event: dict[str, Any] | None
    spend_event: dict[str, Any] | None
    completion_event: dict[str, Any] | None
    monitor_phase: ReceiptBoundMonitorPhase | None
    replay_phase: ReceiptBoundReplayPhase | None

__all__ = [
    "SETTLEMENT_IDENTITY_SCHEMA_VERSION",
    "SETTLEMENT_PLAN_SCHEMA_VERSION",
    "SETTLEMENT_RECEIPT_SCHEMA_VERSION",
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
    "read_heartbeat_settlement",
    "settlement_binding_args",
    "settlement_result_payload",
    "settlement_step_command",
]


def _readback_result(
    payload: Any,
    *,
    identity: bool = False,
) -> SettlementResult[Any]:
    if not isinstance(payload, Mapping):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    result = payload.get("result")
    projection = payload.get("payload")
    if not isinstance(result, Mapping) or not isinstance(projection, Mapping):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    return decode_settlement_result(
        result,
        value_decoder=(
            SettlementIdentity.from_runtime_payload if identity else None
        ),
        projection_payload=projection,
    )


def _optional_readback_record(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    return dict(value)


def read_heartbeat_settlement(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
    replan_obligation_id: str | None = None,
    infer_turn_instance_id: bool = False,
    allow_unbound_binding: bool = False,
) -> QuotaSettlementReadback | None:
    """Read one complete heartbeat settlement through the TS domain owner."""

    try:
        payload = effect_runtime_result(
            "quota.settlement.read",
            {
                "schema_version": QUOTA_SETTLEMENT_READBACK_REQUEST_SCHEMA,
                "runtime_root": str(runtime_root.expanduser()),
                "goal_id": goal_id,
                "agent_id": agent_id,
                "todo_id": todo_id,
                "turn_instance_id": turn_instance_id,
                "replan_obligation_id": replan_obligation_id,
                "infer_turn_instance_id": infer_turn_instance_id,
                "allow_unbound_binding": allow_unbound_binding,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(payload, Mapping) or (
        payload.get("schema_version")
        != QUOTA_SETTLEMENT_READBACK_RESULT_SCHEMA
    ):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    if payload.get("found") is False:
        if set(payload) != {"schema_version", "found"}:
            raise RuntimeError(
                "TypeScript quota settlement readback result shape mismatch"
            )
        return None
    if payload.get("found") is not True:
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    workspace_causality = _optional_readback_record(
        payload.get("workspace_causality")
    )
    monitor_phase = payload.get("monitor_phase")
    replay_phase = payload.get("replay_phase")
    if monitor_phase not in {None, "poll_due", "settlement_pending", "settled"} or (
        replay_phase not in {None, "open", "settlement_pending", "settled"}
    ):
        raise RuntimeError("TypeScript quota settlement readback result shape mismatch")
    return QuotaSettlementReadback(
        identity=_readback_result(payload.get("identity"), identity=True),
        writeback=_readback_result(payload.get("writeback")),
        spend=_readback_result(payload.get("spend")),
        delivery=_readback_result(payload.get("delivery")),
        settlement=_readback_result(payload.get("settlement")),
        terminal_closeout=_readback_result(payload.get("terminal_closeout")),
        terminal_settlement=_readback_result(payload.get("terminal_settlement")),
        workspace_causality=(
            {str(key): str(value) for key, value in workspace_causality.items()}
            if workspace_causality is not None
            else None
        ),
        writeback_run=_optional_readback_record(payload.get("writeback_run")),
        spend_run=_optional_readback_record(payload.get("spend_run")),
        heartbeat_receipt=_optional_readback_record(payload.get("heartbeat_receipt")),
        writeback_event=_optional_readback_record(payload.get("writeback_event")),
        spend_event=_optional_readback_record(payload.get("spend_event")),
        completion_event=_optional_readback_record(payload.get("completion_event")),
        monitor_phase=(
            ReceiptBoundMonitorPhase(str(monitor_phase))
            if monitor_phase is not None
            else None
        ),
        replay_phase=(
            ReceiptBoundReplayPhase(str(replay_phase))
            if replay_phase is not None
            else None
        ),
    )

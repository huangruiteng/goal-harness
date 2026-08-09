from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...rollout_event_log import load_rollout_events, rollout_event_log_path
from ...turn_identity import normalize_turn_instance_id
from ..todos.contract import normalize_todo_claimed_by, normalize_todo_id
from ..work_items.delivery_outcome import (
    ACCOUNTABLE_DELIVERY_OUTCOMES,
    normalize_delivery_outcome,
)
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
    build_codex_app_settlement_plan,
    settlement_binding_args,
    settlement_step_command,
)
from .heartbeat_receipt import find_heartbeat_receipt

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
    "find_settlement_spend_run",
    "find_settlement_step_event",
    "find_settlement_writeback",
    "require_settlement_spend",
    "require_settlement_todo_completion",
    "require_settlement_writeback",
    "resolve_heartbeat_settlement_identity",
    "settlement_binding_args",
    "settlement_result_payload",
    "settlement_step_command",
]


def resolve_heartbeat_settlement_identity(
    runtime_root: Path,
    *,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str | None,
) -> SettlementResult[SettlementIdentity]:
    normalized_agent_id = normalize_todo_claimed_by(agent_id)
    normalized_todo_id = normalize_todo_id(todo_id)
    try:
        normalized_turn_id = normalize_turn_instance_id(turn_instance_id)
    except ValueError as exc:
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
        )
    if not normalized_agent_id or not normalized_todo_id or not normalized_turn_id:
        return SettlementResult.failed(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=(
                "turn-scoped settlement requires agent_id, todo_id, and "
                "turn_instance_id"
            ),
        )
    receipt_event = find_heartbeat_receipt(
        runtime_root,
        goal_id=goal_id,
        agent_id=normalized_agent_id,
        turn_instance_id=normalized_turn_id,
    )
    if receipt_event is None:
        return SettlementResult.failed(
            kind=SettlementFailureKind.RECEIPT_MISSING,
            step_kind=SettlementStepKind.VALIDATION,
            reason=(
                "matching quota should-run heartbeat receipt is missing; rerun the "
                "guard with the same turn_instance_id"
            ),
        )
    details_value = receipt_event.get("details")
    details = details_value if isinstance(details_value, Mapping) else {}
    receipt_todo_id = normalize_todo_id(details.get("todo_id"))
    if receipt_todo_id != normalized_todo_id:
        return SettlementResult.failed(
            kind=SettlementFailureKind.IDENTITY_MISMATCH,
            step_kind=SettlementStepKind.VALIDATION,
            reason=(
                "settlement Todo does not match the original quota guard: "
                f"receipt todo is {receipt_todo_id or 'missing'} but requested "
                f"todo is {normalized_todo_id}"
            ),
        )
    identity = SettlementIdentity(
        goal_id=goal_id,
        agent_id=normalized_agent_id,
        todo_id=normalized_todo_id,
        turn_instance_id=normalized_turn_id,
    )
    receipt_effect_id = str(details.get("settlement_effect_id") or "").strip()
    if receipt_effect_id and receipt_effect_id != identity.effect_id:
        return SettlementResult.failed(
            kind=SettlementFailureKind.IDENTITY_MISMATCH,
            step_kind=SettlementStepKind.VALIDATION,
            reason=(
                "settlement effect does not match the original quota guard: "
                f"receipt effect is {receipt_effect_id} but expected "
                f"{identity.effect_id}"
            ),
        )
    event_id = str(receipt_event.get("event_id") or "").strip() or None
    return SettlementResult.pure(
        identity,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.VALIDATION,
                status="committed",
                effect_id=identity.effect_id,
                source_ref=f"rollout_event:{event_id}" if event_id else None,
            ),
        ),
    )


def _run_index_records(runtime_root: Path, goal_id: str) -> list[dict[str, Any]]:
    index_path = runtime_root / "goals" / goal_id / "runs" / "index.jsonl"
    if not index_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def find_settlement_writeback(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> dict[str, Any] | None:
    for run in reversed(_run_index_records(runtime_root, identity.goal_id)):
        if str(run.get("turn_instance_id") or "") != identity.turn_instance_id:
            continue
        if normalize_todo_id(run.get("todo_id")) != identity.todo_id:
            continue
        run_agent_id = normalize_todo_claimed_by(run.get("agent_id"))
        if run_agent_id != identity.agent_id:
            continue
        if (
            normalize_delivery_outcome(run.get("delivery_outcome"))
            not in ACCOUNTABLE_DELIVERY_OUTCOMES
        ):
            continue
        return run
    return None


def find_settlement_step_event(
    runtime_root: Path,
    identity: SettlementIdentity,
    *,
    event_kind: str,
) -> dict[str, Any] | None:
    events = load_rollout_events(rollout_event_log_path(runtime_root, identity.goal_id))
    for event in reversed(events):
        if event.get("event_kind") != event_kind:
            continue
        if str(event.get("goal_id") or "") != identity.goal_id:
            continue
        if str(event.get("agent_id") or "") != identity.agent_id:
            continue
        if str(event.get("run_id") or "") != identity.turn_instance_id:
            continue
        details_value = event.get("details")
        details = details_value if isinstance(details_value, Mapping) else {}
        if str(details.get("settlement_effect_id") or "") != identity.effect_id:
            continue
        return event
    return None


def require_settlement_todo_completion(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> SettlementResult[dict[str, Any]]:
    receipt_event = find_settlement_step_event(
        runtime_root,
        identity,
        event_kind="todo_complete",
    )
    if receipt_event is None:
        return SettlementResult.failed(
            kind=SettlementFailureKind.RECEIPT_MISSING,
            step_kind=SettlementStepKind.TODO_COMPLETION,
            reason="matching Todo completion receipt is missing",
        )
    event_id = str(receipt_event.get("event_id") or "").strip()
    return SettlementResult.pure(
        receipt_event,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.TODO_COMPLETION,
                status="committed",
                effect_id=identity.effect_id,
                source_ref=f"rollout_event:{event_id}" if event_id else None,
            ),
        ),
    )


def require_settlement_writeback(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> SettlementResult[dict[str, Any]]:
    run = find_settlement_writeback(runtime_root, identity)
    receipt_event = find_settlement_step_event(
        runtime_root,
        identity,
        event_kind="refresh_state",
    )
    if run is None or receipt_event is None:
        return SettlementResult.failed(
            kind=SettlementFailureKind.WRITEBACK_MISSING,
            step_kind=SettlementStepKind.DURABLE_WRITEBACK,
            reason=(
                "matching accountable refresh-state receipt is missing for the "
                "original settlement identity"
            ),
        )
    event_id = str(receipt_event.get("event_id") or "").strip()
    return SettlementResult.pure(
        run,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.DURABLE_WRITEBACK,
                status="committed",
                effect_id=identity.effect_id,
                source_ref=f"rollout_event:{event_id}" if event_id else None,
            ),
        ),
    )


def find_settlement_spend_run(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> dict[str, Any] | None:
    for run in reversed(_run_index_records(runtime_root, identity.goal_id)):
        if str(run.get("classification") or "") != "quota_slot_spent":
            continue
        if str(run.get("turn_instance_id") or "") != identity.turn_instance_id:
            continue
        if normalize_todo_id(run.get("todo_id")) != identity.todo_id:
            continue
        if normalize_todo_claimed_by(run.get("agent_id")) != identity.agent_id:
            continue
        return run
    return None


def require_settlement_spend(
    runtime_root: Path,
    identity: SettlementIdentity,
) -> SettlementResult[dict[str, Any]]:
    run = find_settlement_spend_run(runtime_root, identity)
    receipt_event = find_settlement_step_event(
        runtime_root,
        identity,
        event_kind="quota_spend",
    )
    if run is None or receipt_event is None:
        return SettlementResult.failed(
            kind=SettlementFailureKind.RECEIPT_MISSING,
            step_kind=SettlementStepKind.QUOTA_SPEND,
            reason="matching quota spend receipt is missing",
        )
    event_id = str(receipt_event.get("event_id") or "").strip()
    return SettlementResult.pure(
        run,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.QUOTA_SPEND,
                status="committed",
                effect_id=identity.effect_id,
                source_ref=f"rollout_event:{event_id}" if event_id else None,
            ),
        ),
    )


def settlement_result_payload(result: SettlementResult[Any]) -> dict[str, Any]:
    return {
        "ok": result.failure is None,
        "receipts": [receipt.as_dict() for receipt in result.receipts],
        "failure": result.failure.as_dict() if result.failure else None,
    }

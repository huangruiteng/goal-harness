"""CLI rollout helpers for heartbeat settlement identity and receipt wiring."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

from ..todos.contract import normalize_todo_id
from .effect_program import SettlementIdentity
from .error_codes import HeartbeatReceiptIdentityConflictError
from .heartbeat_receipt import (
    heartbeat_receipt_view,
    upgrade_identityless_heartbeat_receipt,
)
from .settlement import (
    require_settlement_spend,
    require_settlement_writeback,
    resolve_heartbeat_settlement_identity,
    settlement_result_payload,
)
from .settlement_workspace_causality import (
    build_delivery_workspace_causality,
    delivery_workspace_causality_event_fields,
)


def reconcile_existing_heartbeat_receipt(
    payload: dict[str, object],
    args: argparse.Namespace,
    *,
    runtime_root: Path,
    turn_instance_id: str,
    existing: dict[str, object],
) -> tuple[dict[str, object], str, bool, str]:
    """Bind an identity-less same-turn receipt without changing a bound receipt."""

    receipt = existing
    receipt_status = "replayed"
    receipt_appended = False
    rollout_todo_id = quota_rollout_todo_id(payload, args)
    if rollout_todo_id:
        existing_details_value = receipt.get("details")
        existing_details = (
            existing_details_value
            if isinstance(existing_details_value, Mapping)
            else {}
        )
        existing_todo_id = str(existing_details.get("todo_id") or "").strip()
        existing_effect_id = str(
            existing_details.get("settlement_effect_id") or ""
        ).strip()
        expected_effect_id = SettlementIdentity(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            todo_id=rollout_todo_id,
            turn_instance_id=turn_instance_id,
        ).effect_id
        if existing_todo_id and existing_effect_id:
            requested_todo_id = normalize_todo_id(args.todo_id)
            if requested_todo_id and requested_todo_id != existing_todo_id:
                raise HeartbeatReceiptIdentityConflictError(
                    "heartbeat receipt settlement identity conflicts with the "
                    "current selected Todo: explicitly requested Todo differs"
                )
            if (
                existing_todo_id != rollout_todo_id
                or existing_effect_id != expected_effect_id
            ):
                raise HeartbeatReceiptIdentityConflictError(
                    "heartbeat receipt settlement identity conflicts with the "
                    "current selected Todo"
                )
        else:
            rollout_details = quota_rollout_details(
                payload,
                args,
                todo_id=rollout_todo_id,
            )
            receipt, upgraded = upgrade_identityless_heartbeat_receipt(
                runtime_root,
                goal_id=args.goal_id,
                agent_id=args.agent_id,
                turn_instance_id=turn_instance_id,
                todo_id=rollout_todo_id,
                settlement_effect_id=expected_effect_id,
                status=str(
                    payload.get("effective_action")
                    or payload.get("decision")
                    or "should-run"
                ),
                summary=f"heartbeat quota receipt upgraded for turn={turn_instance_id}",
                details=rollout_details,
            )
            if upgraded:
                receipt_status = "upgraded"
                receipt_appended = True
    details_value = receipt.get("details")
    details: Mapping[str, object] = (
        details_value if isinstance(details_value, Mapping) else {}
    )
    stall_observation = str(details.get("stall_observation") or "not_applicable")
    return receipt, receipt_status, receipt_appended, stall_observation


def reconcile_existing_heartbeat_receipt_for_turn(
    payload: dict[str, object],
    args: argparse.Namespace,
    *,
    runtime_root: Path,
    turn_instance_id: str,
    existing: dict[str, object],
) -> tuple[dict[str, object], str, bool, str, bool]:
    """Reconcile an existing receipt and report whether the turn is receipt-ready."""

    receipt, status, appended, stall_observation = (
        reconcile_existing_heartbeat_receipt(
            payload,
            args,
            runtime_root=runtime_root,
            turn_instance_id=turn_instance_id,
            existing=existing,
        )
    )
    return receipt, status, appended, stall_observation, True


def render_existing_heartbeat_receipt_payload(
    payload: dict[str, object],
    *,
    receipt: dict[str, object],
    turn_instance_id: str,
    status: str,
    appended: bool,
) -> None:
    """Render the committed existing heartbeat receipt into a quota payload."""

    payload["heartbeat_receipt"] = heartbeat_receipt_view(
        receipt,
        turn_instance_id=turn_instance_id,
        status=status,
    )
    payload["rollout_event"] = {
        "schema_version": receipt.get("schema_version"),
        "event_id": receipt.get("event_id"),
        "event_kind": receipt.get("event_kind"),
        "recorded_at": receipt.get("recorded_at"),
        "status": receipt.get("status"),
        "appended": appended,
    }


def quota_rollout_todo_id(
    payload: Mapping[str, object],
    args: argparse.Namespace,
) -> str | None:
    selected_todo = (
        payload.get("selected_todo")
        if isinstance(payload.get("selected_todo"), Mapping)
        else {}
    )
    return (
        normalize_todo_id(payload.get("todo_id"))
        or normalize_todo_id(selected_todo.get("todo_id"))
        or normalize_todo_id(args.todo_id)
    )


def quota_rollout_details(
    payload: Mapping[str, object],
    args: argparse.Namespace,
    *,
    todo_id: str | None,
) -> dict[str, object]:
    successor_todo_ids = (
        payload.get("successor_todo_ids")
        if isinstance(payload.get("successor_todo_ids"), list)
        else []
    )
    selected_todo = (
        payload.get("selected_todo")
        if isinstance(payload.get("selected_todo"), Mapping)
        else None
    )
    workspace_causality = build_delivery_workspace_causality(selected_todo)
    details: dict[str, object] = {
        "command": "quota",
        "quota_command": args.quota_command,
        "ok": bool(payload.get("ok")),
        "should_run": bool(payload.get("should_run")),
        "appended": bool(payload.get("appended")),
        "slots": payload.get("slots") or "",
        "source": payload.get("source") or "",
        "todo_id": todo_id or "",
        "target_key": payload.get("target_key") or "",
        "successor_todo_ids": ",".join(
            str(successor_id)
            for successor_id in successor_todo_ids
            if str(successor_id).strip()
        ),
        "applied_rrule": payload.get("applied_rrule") or "",
        "settlement_effect_id": (
            payload.get("settlement_identity", {}).get("effect_id")
            if isinstance(payload.get("settlement_identity"), Mapping)
            else ""
        ),
    }
    if workspace_causality:
        details.update(delivery_workspace_causality_event_fields(workspace_causality))
    return details


def attach_spend_settlement_result(
    payload: dict[str, object],
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str | None,
    todo_id: str | None,
    turn_instance_id: str,
) -> None:
    guard_result = resolve_heartbeat_settlement_identity(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=todo_id,
        turn_instance_id=turn_instance_id,
    )
    identity = guard_result.value
    if identity is None:
        settlement_result = guard_result
    else:
        settlement_result = guard_result.bind(
            lambda resolved: require_settlement_writeback(
                runtime_root,
                resolved,
            )
        ).bind(
            lambda _writeback: require_settlement_spend(
                runtime_root,
                identity,
            )
        )
    payload["settlement_result"] = settlement_result_payload(
        settlement_result
    )
    if settlement_result.failure is not None:
        payload["ok"] = False
        payload["receipt_repair_required"] = True
        payload["reason"] = settlement_result.failure.reason
    elif payload.get("receipt_repair_required"):
        payload["receipt_repair_required"] = False
        payload["receipt_repaired"] = True

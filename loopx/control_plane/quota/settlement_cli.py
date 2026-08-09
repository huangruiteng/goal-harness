"""CLI rollout helpers for heartbeat settlement identity and receipt wiring."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

from ..todos.contract import normalize_todo_id
from .settlement import (
    require_settlement_spend,
    require_settlement_writeback,
    resolve_heartbeat_settlement_identity,
    settlement_result_payload,
)


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
    return {
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

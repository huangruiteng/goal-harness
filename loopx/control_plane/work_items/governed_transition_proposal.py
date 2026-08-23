"""Materialize governed provider proposals through LoopX-owned Todo APIs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from enum import StrEnum
from pathlib import Path
from typing import Any

from ...todos import (
    add_goal_todo,
    complete_goal_todo,
    list_goal_todos,
    update_goal_todo,
)
from ..runtime.public_safety import validate_public_safe_value
from ..todos.contract import (
    TODO_STATUS_DONE,
    TODO_STATUS_OPEN,
    TODO_TASK_CLASS_MONITOR,
    normalize_todo_capability_binding_ref,
)

GOVERNED_TRANSITION_RECEIPT_SCHEMA_VERSION = (
    "loopx_governed_transition_proposal_receipt_v0"
)
_RECEIPT_FIELDS = {
    "schema_version",
    "proposal_id",
    "proposal_digest",
    "kind",
    "monitor_key",
    "action",
    "todo_id",
    "status",
    "target_key",
}


TransitionCheckpoint = Callable[[list[dict[str, Any]]], None]


class GovernedTransitionSettlementPhase(StrEnum):
    """Turn-settlement phase that owns one admitted Kernel transition."""

    PRE_SETTLEMENT = "pre_settlement"
    POST_SETTLEMENT = "post_settlement"


_SETTLEMENT_PHASE_BY_PROPOSAL_KIND = {
    "continuous_monitor_upsert": GovernedTransitionSettlementPhase.PRE_SETTLEMENT,
    "continuous_monitor_complete": GovernedTransitionSettlementPhase.POST_SETTLEMENT,
}


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): deepcopy(item) for key, item in value.items()}


def validate_governed_transition_receipts(
    value: object,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError(
            "governed transition proposal receipts must contain at most 64 items"
        )
    receipts: list[dict[str, Any]] = []
    proposal_ids: set[str] = set()
    for index, raw in enumerate(value):
        receipt = _mapping(raw, f"governed transition receipt[{index}]")
        if set(receipt) != _RECEIPT_FIELDS:
            raise ValueError("governed transition proposal receipt fields are invalid")
        if receipt.get("schema_version") != GOVERNED_TRANSITION_RECEIPT_SCHEMA_VERSION:
            raise ValueError("governed transition proposal receipt schema is invalid")
        proposal_id = str(receipt.get("proposal_id") or "")
        if not proposal_id or proposal_id in proposal_ids:
            raise ValueError("governed transition proposal receipt identity is invalid")
        proposal_ids.add(proposal_id)
        if receipt.get("kind") not in {
            "continuous_monitor_upsert",
            "continuous_monitor_complete",
        }:
            raise ValueError("governed transition proposal receipt kind is invalid")
        if receipt.get("status") != "committed":
            raise ValueError("governed transition proposal receipt status is invalid")
        for field in (
            "proposal_digest",
            "monitor_key",
            "action",
            "todo_id",
        ):
            if not isinstance(receipt.get(field), str) or not receipt[field]:
                raise ValueError(
                    f"governed transition proposal receipt {field} is invalid"
                )
        if receipt.get("target_key") is not None and not isinstance(
            receipt.get("target_key"), str
        ):
            raise ValueError(
                "governed transition proposal receipt target_key is invalid"
            )
        validate_public_safe_value(receipt, path=f"transition_receipts[{index}]")
        receipts.append(receipt)
    return receipts


def _monitor_for_key(
    *,
    registry_path: Path,
    goal_id: str,
    monitor_key: str,
) -> dict[str, Any] | None:
    projection = list_goal_todos(
        registry_path=registry_path,
        goal_id=goal_id,
        role="agent",
    )
    matches = [
        item
        for item in projection.get("todos", [])
        if isinstance(item, dict)
        and normalize_todo_capability_binding_ref(item.get("capability_binding_ref"))
        == monitor_key
    ]
    if len(matches) > 1:
        raise ValueError("governed monitor proposal matched multiple Todos")
    if not matches:
        return None
    item = matches[0]
    if item.get("task_class") != TODO_TASK_CLASS_MONITOR:
        raise ValueError("governed monitor proposal matched a non-monitor Todo")
    return item


def _upsert_monitor(
    *,
    registry_path: Path,
    goal_id: str,
    agent_id: str,
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    monitor_key = str(proposal["monitor_key"])
    current = _monitor_for_key(
        registry_path=registry_path,
        goal_id=goal_id,
        monitor_key=monitor_key,
    )
    monitor_metadata = {
        "target_key": str(proposal["target_key"]),
        "cadence": str(proposal["cadence"]),
        "next_due_at": str(proposal["next_due_at"]),
        "expires_at": str(proposal["expires_at"]),
    }
    if current is None:
        result = add_goal_todo(
            registry_path=registry_path,
            goal_id=goal_id,
            role="agent",
            text=str(proposal["text"]),
            status=TODO_STATUS_OPEN,
            task_class=TODO_TASK_CLASS_MONITOR,
            action_kind=str(proposal["action_kind"]),
            capability_binding_ref=monitor_key,
            required_capabilities=[
                str(item) for item in proposal["required_capabilities"]
            ],
            claimed_by=agent_id,
            agent_id=agent_id,
            monitor_metadata=monitor_metadata,
        )
        action = "created" if result.get("added") else "reused"
    else:
        if current.get("status") == TODO_STATUS_DONE:
            raise ValueError("governed monitor proposal cannot reopen a completed Todo")
        if current.get("status") != TODO_STATUS_OPEN:
            raise ValueError("governed monitor proposal requires an open monitor Todo")
        owner = str(current.get("claimed_by") or "")
        if owner and owner != agent_id:
            raise ValueError("governed monitor proposal cannot reassign another Agent")
        result = update_goal_todo(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=str(current["todo_id"]),
            role="agent",
            text=str(proposal["text"]),
            status=TODO_STATUS_OPEN,
            task_class=TODO_TASK_CLASS_MONITOR,
            action_kind=str(proposal["action_kind"]),
            required_capabilities=[
                str(item) for item in proposal["required_capabilities"]
            ],
            claimed_by=agent_id,
            agent_id=agent_id,
            monitor_metadata=monitor_metadata,
        )
        action = "updated" if result.get("changed") else "unchanged"
    return {
        "action": action,
        "todo_id": str(result["todo_id"]),
        "target_key": str(proposal["target_key"]),
    }


def _complete_monitor(
    *,
    registry_path: Path,
    goal_id: str,
    agent_id: str,
    effect_id: str,
    proposal: Mapping[str, Any],
) -> dict[str, Any]:
    current = _monitor_for_key(
        registry_path=registry_path,
        goal_id=goal_id,
        monitor_key=str(proposal["monitor_key"]),
    )
    if current is None:
        raise ValueError("governed monitor completion has no materialized Todo")
    owner = str(current.get("claimed_by") or "")
    if owner and owner != agent_id:
        raise ValueError("governed monitor completion cannot mutate another Agent")
    completion_key = (
        "governed_transition_"
        + hashlib.sha256(f"{effect_id}:{proposal['proposal_id']}".encode()).hexdigest()[
            :32
        ]
    )
    result = complete_goal_todo(
        registry_path=registry_path,
        goal_id=goal_id,
        todo_id=str(current["todo_id"]),
        role="agent",
        evidence=str(proposal["evidence"]),
        completion_turn_key=completion_key,
        no_followup=True,
        claimed_by=agent_id,
        agent_id=agent_id,
        authority_reason="validated governed external-capability proposal",
    )
    return {
        "action": ("replayed" if result.get("idempotent_replay") else "completed"),
        "todo_id": str(result["todo_id"]),
        "target_key": current.get("target_key"),
    }


def settle_governed_transition_proposals(
    *,
    registry_path: str | Path,
    goal_id: str,
    agent_id: str,
    effect_id: str,
    proposals: Sequence[Mapping[str, Any]],
    existing_receipts: object,
    checkpoint: TransitionCheckpoint,
    phase: GovernedTransitionSettlementPhase,
) -> list[dict[str, Any]]:
    """Apply admitted proposals for one settlement phase and checkpoint receipts."""

    receipts = validate_governed_transition_receipts(existing_receipts)
    by_proposal_id = {str(item["proposal_id"]): item for item in receipts}
    for raw in proposals:
        proposal = _mapping(raw, "governed transition proposal")
        kind = str(proposal.get("kind") or "")
        proposal_phase = _SETTLEMENT_PHASE_BY_PROPOSAL_KIND.get(kind)
        if proposal_phase is None:
            raise ValueError("governed transition proposal kind is unsupported")
        proposal_id = str(proposal.get("proposal_id") or "")
        proposal_digest = _canonical_digest(proposal)
        replay = by_proposal_id.get(proposal_id)
        if replay is not None:
            if (
                replay.get("proposal_digest") != proposal_digest
                or replay.get("kind") != proposal.get("kind")
                or replay.get("monitor_key") != proposal.get("monitor_key")
            ):
                raise ValueError(
                    "governed transition proposal replay does not match its receipt"
                )
            continue
        if proposal_phase is not phase:
            continue
        if kind == "continuous_monitor_upsert":
            result = _upsert_monitor(
                registry_path=Path(registry_path).expanduser(),
                goal_id=goal_id,
                agent_id=agent_id,
                proposal=proposal,
            )
        elif kind == "continuous_monitor_complete":
            result = _complete_monitor(
                registry_path=Path(registry_path).expanduser(),
                goal_id=goal_id,
                agent_id=agent_id,
                effect_id=effect_id,
                proposal=proposal,
            )
        else:
            raise RuntimeError("governed transition proposal dispatch is incomplete")
        receipt = {
            "schema_version": GOVERNED_TRANSITION_RECEIPT_SCHEMA_VERSION,
            "proposal_id": proposal_id,
            "proposal_digest": proposal_digest,
            "kind": kind,
            "monitor_key": str(proposal["monitor_key"]),
            "action": str(result["action"]),
            "todo_id": str(result["todo_id"]),
            "status": "committed",
            "target_key": result.get("target_key"),
        }
        validate_public_safe_value(receipt, path="transition_receipt")
        receipts.append(receipt)
        by_proposal_id[proposal_id] = receipt
        checkpoint(receipts)
    return receipts

"""Bounded material rerank proposal and apply receipt contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ._validation import (
    capability_contract,
    check_record_keys,
    compact_text,
    compact_token,
    iso_timestamp,
    packet_ref,
    positive_int,
    token_list,
)

MATERIAL_RERANK_PROPOSAL_SCHEMA_VERSION = "material_rerank_proposal_v0"
MATERIAL_RERANK_APPLY_RECEIPT_SCHEMA_VERSION = "material_rerank_apply_receipt_v0"

_MOVE_FIELDS = {
    "evidence_refs",
    "from_rank",
    "material_ref",
    "reason_code",
    "to_rank",
}
_REQUIRED_MOVE_FIELDS = {
    "from_rank",
    "material_ref",
    "reason_code",
    "to_rank",
}
_APPLY_STATUSES = {"applied", "no_change", "rejected", "rolled_back"}


def _normalize_moves(
    values: Sequence[Mapping[str, Any]] | None,
    *,
    protected_material_refs: set[str],
    max_moved_items: int,
    max_rank_displacement: int,
    target_window_size: int,
) -> list[dict[str, Any]]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError("moves must be a sequence of objects")
    if len(values) > max_moved_items:
        raise ValueError("moves exceeds max_moved_items")

    normalized: list[dict[str, Any]] = []
    material_refs: set[str] = set()
    source_ranks: set[int] = set()
    target_ranks: set[int] = set()
    for index, value in enumerate(values):
        field = f"moves[{index}]"
        check_record_keys(
            value,
            field=field,
            allowed=_MOVE_FIELDS,
            required=_REQUIRED_MOVE_FIELDS,
        )
        material_ref = compact_token(
            value["material_ref"],
            field=f"{field}.material_ref",
        )
        if material_ref in protected_material_refs:
            raise ValueError(f"{field}.material_ref is protected")
        if material_ref in material_refs:
            raise ValueError("moves material_ref values must be unique")
        from_rank = positive_int(value["from_rank"], field=f"{field}.from_rank")
        to_rank = positive_int(value["to_rank"], field=f"{field}.to_rank")
        if from_rank > target_window_size or to_rank > target_window_size:
            raise ValueError(f"{field} ranks must stay within target_window_size")
        if abs(from_rank - to_rank) > max_rank_displacement:
            raise ValueError(f"{field} exceeds max_rank_displacement")
        if from_rank == to_rank:
            raise ValueError(f"{field} must change rank")
        if from_rank in source_ranks:
            raise ValueError("moves from_rank values must be unique")
        if to_rank in target_ranks:
            raise ValueError("moves to_rank values must be unique")
        material_refs.add(material_ref)
        source_ranks.add(from_rank)
        target_ranks.add(to_rank)
        normalized.append(
            {
                "material_ref": material_ref,
                "from_rank": from_rank,
                "to_rank": to_rank,
                "reason_code": compact_token(
                    value["reason_code"],
                    field=f"{field}.reason_code",
                ),
                "evidence_refs": token_list(
                    value.get("evidence_refs"),
                    field=f"{field}.evidence_refs",
                    max_items=10,
                ),
            }
        )
    return sorted(
        normalized,
        key=lambda item: json.dumps(
            item,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def build_material_rerank_proposal(
    *,
    goal_id: str,
    proposal_id: str,
    inventory_ref: str,
    decision_evidence_ref: str,
    observed_at: str,
    target_window_size: int,
    max_moved_items: int,
    max_rank_displacement: int,
    moves: Sequence[Mapping[str, Any]] | None = None,
    protected_material_refs: Sequence[str] | None = None,
    no_change_reason: str | None = None,
) -> dict[str, Any]:
    """Propose a bounded delta; never rewrite or apply a whole material queue."""

    window = positive_int(target_window_size, field="target_window_size")
    max_moved = positive_int(max_moved_items, field="max_moved_items")
    max_displacement = positive_int(
        max_rank_displacement,
        field="max_rank_displacement",
    )
    protected = token_list(
        protected_material_refs,
        field="protected_material_refs",
    )
    normalized_moves = _normalize_moves(
        moves,
        protected_material_refs=set(protected),
        max_moved_items=max_moved,
        max_rank_displacement=max_displacement,
        target_window_size=window,
    )
    if not normalized_moves and no_change_reason is None:
        raise ValueError("no_change_reason is required when moves is empty")
    if normalized_moves and no_change_reason is not None:
        raise ValueError("no_change_reason is only valid when moves is empty")

    proposal: dict[str, Any] = {
        "schema_version": MATERIAL_RERANK_PROPOSAL_SCHEMA_VERSION,
        "goal_id": compact_token(goal_id, field="goal_id"),
        "proposal_id": compact_token(proposal_id, field="proposal_id"),
        "inventory_ref": compact_token(inventory_ref, field="inventory_ref"),
        "decision_evidence_ref": compact_token(
            decision_evidence_ref,
            field="decision_evidence_ref",
        ),
        "observed_at": iso_timestamp(observed_at, field="observed_at"),
        "visibility": "public_safe",
        "capability": capability_contract(packet_role="rerank_proposal"),
        "constraints": {
            "target_window_size": window,
            "max_moved_items": max_moved,
            "max_rank_displacement": max_displacement,
            "protected_material_refs": protected,
        },
        "moves": normalized_moves,
        "no_change": not normalized_moves,
        "apply_authorized": False,
        "raw_content_captured": False,
    }
    if no_change_reason is not None:
        proposal["no_change_reason"] = compact_text(
            no_change_reason,
            field="no_change_reason",
        )
    proposal["proposal_ref"] = packet_ref("material-rerank", proposal)
    return proposal


def build_material_rerank_apply_receipt(
    *,
    goal_id: str,
    receipt_id: str,
    proposal_ref: str,
    observed_at: str,
    status: str,
    before_revision: str,
    after_revision: str,
    owner_gate_ref: str,
    validation_ref: str,
    applied_material_refs: Sequence[str] | None = None,
    rollback_ref: str | None = None,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    """Record the result of an owner-gated apply, rejection, no-op, or rollback."""

    normalized_status = compact_token(status, field="status")
    if normalized_status not in _APPLY_STATUSES:
        raise ValueError(f"unsupported status: {normalized_status}")
    before = compact_token(before_revision, field="before_revision")
    after = compact_token(after_revision, field="after_revision")
    applied_refs = token_list(
        applied_material_refs,
        field="applied_material_refs",
    )

    if normalized_status == "applied":
        if not applied_refs:
            raise ValueError("applied status requires applied_material_refs")
        if before == after:
            raise ValueError("applied status requires a new after_revision")
        if rollback_ref is None:
            raise ValueError("applied status requires rollback_ref")
    elif normalized_status == "rolled_back":
        if before == after:
            raise ValueError("rolled_back status requires a new after_revision")
        if rollback_ref is None:
            raise ValueError("rolled_back status requires rollback_ref")
    else:
        if applied_refs:
            raise ValueError(
                f"{normalized_status} status cannot include applied_material_refs"
            )
        if before != after:
            raise ValueError(
                f"{normalized_status} status must preserve the store revision"
            )
    if normalized_status == "rejected" and rejection_reason is None:
        raise ValueError("rejected status requires rejection_reason")
    if normalized_status != "rejected" and rejection_reason is not None:
        raise ValueError("rejection_reason is only valid for rejected status")

    receipt: dict[str, Any] = {
        "schema_version": MATERIAL_RERANK_APPLY_RECEIPT_SCHEMA_VERSION,
        "goal_id": compact_token(goal_id, field="goal_id"),
        "receipt_id": compact_token(receipt_id, field="receipt_id"),
        "proposal_ref": compact_token(proposal_ref, field="proposal_ref"),
        "observed_at": iso_timestamp(observed_at, field="observed_at"),
        "status": normalized_status,
        "before_revision": before,
        "after_revision": after,
        "owner_gate_ref": compact_token(owner_gate_ref, field="owner_gate_ref"),
        "validation_ref": compact_token(validation_ref, field="validation_ref"),
        "applied_material_refs": applied_refs,
        "visibility": "public_safe",
        "capability": capability_contract(packet_role="rerank_apply_receipt"),
        "raw_content_captured": False,
        "private_locations_captured": False,
    }
    if rollback_ref is not None:
        receipt["rollback_ref"] = compact_token(
            rollback_ref,
            field="rollback_ref",
        )
    if rejection_reason is not None:
        receipt["rejection_reason"] = compact_text(
            rejection_reason,
            field="rejection_reason",
        )
    receipt["receipt_ref"] = packet_ref("material-rerank-apply", receipt)
    return receipt

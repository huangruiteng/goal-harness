"""Auditable material candidate and archive lifecycle receipts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ._validation import (
    capability_contract,
    compact_token,
    iso_timestamp,
    packet_ref,
    token_list,
)
from .inventory import MATERIAL_LIFECYCLE_STATES

MATERIAL_LIFECYCLE_RECEIPT_SCHEMA_VERSION = "material_lifecycle_receipt_v0"

_ALLOWED_TRANSITIONS = {
    ("unread", "candidate"),
    ("candidate", "active"),
    ("candidate", "archived"),
    ("active", "archived"),
    ("active", "carryover"),
    ("carryover", "active"),
    ("archived", "active"),
}


def build_material_lifecycle_receipt(
    *,
    goal_id: str,
    receipt_id: str,
    material_ref: str,
    from_state: str,
    to_state: str,
    observed_at: str,
    source_ref: str,
    source_revision: str,
    transition_authority_ref: str,
    evidence_refs: Sequence[str] | None = None,
    artifact_ref: str | None = None,
    archive_ref: str | None = None,
    decision_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Record a validated lifecycle transition without carrying source content."""

    normalized_from = compact_token(from_state, field="from_state")
    normalized_to = compact_token(to_state, field="to_state")
    if normalized_from not in MATERIAL_LIFECYCLE_STATES:
        raise ValueError(f"unsupported from_state: {normalized_from}")
    if normalized_to not in MATERIAL_LIFECYCLE_STATES:
        raise ValueError(f"unsupported to_state: {normalized_to}")
    if (normalized_from, normalized_to) not in _ALLOWED_TRANSITIONS:
        raise ValueError(
            f"unsupported material lifecycle transition: "
            f"{normalized_from}->{normalized_to}"
        )
    if (
        normalized_from == "archived" or normalized_to == "archived"
    ) and not archive_ref:
        raise ValueError("archive_ref is required for archived transitions")

    receipt: dict[str, Any] = {
        "schema_version": MATERIAL_LIFECYCLE_RECEIPT_SCHEMA_VERSION,
        "goal_id": compact_token(goal_id, field="goal_id"),
        "receipt_id": compact_token(receipt_id, field="receipt_id"),
        "material_ref": compact_token(material_ref, field="material_ref"),
        "from_state": normalized_from,
        "to_state": normalized_to,
        "observed_at": iso_timestamp(observed_at, field="observed_at"),
        "source_ref": compact_token(source_ref, field="source_ref"),
        "source_revision": compact_token(
            source_revision,
            field="source_revision",
        ),
        "transition_authority_ref": compact_token(
            transition_authority_ref,
            field="transition_authority_ref",
        ),
        "evidence_refs": token_list(evidence_refs, field="evidence_refs"),
        "visibility": "public_safe",
        "capability": capability_contract(packet_role="lifecycle_receipt"),
        "source_reference_preserved": True,
        "raw_content_captured": False,
        "private_locations_captured": False,
    }
    if artifact_ref is not None:
        receipt["artifact_ref"] = compact_token(artifact_ref, field="artifact_ref")
    if archive_ref is not None:
        receipt["archive_ref"] = compact_token(archive_ref, field="archive_ref")
    if decision_evidence_ref is not None:
        receipt["decision_evidence_ref"] = compact_token(
            decision_evidence_ref,
            field="decision_evidence_ref",
        )
    receipt["receipt_ref"] = packet_ref("material-lifecycle", receipt)
    return receipt

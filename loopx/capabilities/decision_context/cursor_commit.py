"""Validated private cursor commit for Decision Context."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from ...file_lock import exclusive_file_lock
from ...rollout_event_log import (
    ROLLOUT_EVENT_SCHEMA_VERSION,
    load_rollout_events,
)
from .assembler import (
    DECISION_CONTEXT_ASSEMBLY_SCHEMA_VERSION,
    DECISION_CURSOR_CHECKPOINT_SCHEMA_VERSION,
    DecisionContextAssembly,
)
from .packets import (
    DECISION_EVIDENCE_PACKET_SCHEMA_VERSION,
    DECISION_OUTCOME_RECEIPT_SCHEMA_VERSION,
    DECISION_PROPOSAL_SCHEMA_VERSION,
)
from .private_state import (
    load_private_decision_cursors,
    private_file_digest,
    write_private_decision_cursors_atomic,
)
from .profile import DecisionContextProfile, resolve_decision_context_activation

DECISION_CURSOR_COMMIT_RECEIPT_SCHEMA_VERSION = "decision_cursor_commit_receipt_v0"

_LIFECYCLE_WRITEBACK_EVENT_KINDS = {
    "refresh_state",
    "todo_add",
    "todo_complete",
    "todo_update",
    "validation",
}
_LIFECYCLE_WRITEBACK_READ_LIMIT = 1000


def _opaque_ref(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _new_packet_ref(prefix: str, packet: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            packet,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _validated_packet_ref(
    prefix: str,
    packet: Mapping[str, Any],
    *,
    field: str,
) -> str:
    body = dict(packet)
    actual = str(body.pop(field, "") or "").strip()
    if actual != _new_packet_ref(prefix, body):
        raise ValueError(f"decision-context {field} is invalid")
    return actual


def _event_id(event: Mapping[str, Any]) -> str:
    body = {key: value for key, value in event.items() if key != "event_id"}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _load_current_cursors(
    path: Path,
    *,
    profile: DecisionContextProfile,
) -> dict[str, str]:
    return load_private_decision_cursors(
        path if path.expanduser().exists() else None,
        profile=profile,
    )


def _validate_decision_packet_chain(
    *,
    assembly: DecisionContextAssembly,
    proposal: Mapping[str, Any],
    outcome_receipt: Mapping[str, Any],
) -> tuple[str, str, str, Mapping[str, Any]]:
    packet = assembly.public_packet()
    if packet.get("schema_version") != DECISION_CONTEXT_ASSEMBLY_SCHEMA_VERSION:
        raise ValueError("decision-context assembly schema is invalid")
    _validated_packet_ref(
        "decision-context-assembly",
        packet,
        field="assembly_ref",
    )

    evidence = packet.get("evidence_packet")
    if (
        not isinstance(evidence, Mapping)
        or evidence.get("schema_version") != DECISION_EVIDENCE_PACKET_SCHEMA_VERSION
    ):
        raise ValueError("decision-context evidence packet is invalid")
    evidence_ref = _validated_packet_ref(
        "decision-evidence",
        evidence,
        field="packet_ref",
    )

    checkpoint = packet.get("cursor_checkpoint")
    if (
        not isinstance(checkpoint, Mapping)
        or checkpoint.get("schema_version") != DECISION_CURSOR_CHECKPOINT_SCHEMA_VERSION
    ):
        raise ValueError("decision-context cursor checkpoint is invalid")
    _validated_packet_ref(
        "decision-cursor-checkpoint",
        checkpoint,
        field="checkpoint_ref",
    )
    if (
        checkpoint.get("evidence_packet_ref") != evidence_ref
        or checkpoint.get("apply_requires_validated_decision_writeback") is not True
        or checkpoint.get("applied") is not False
    ):
        raise ValueError("decision-context cursor checkpoint is not committable")

    if proposal.get("schema_version") != DECISION_PROPOSAL_SCHEMA_VERSION:
        raise ValueError("decision-context proposal schema is invalid")
    proposal_ref = _validated_packet_ref(
        "decision-proposal",
        proposal,
        field="packet_ref",
    )
    if (
        proposal.get("goal_id") != packet.get("goal_id")
        or proposal.get("decision_id") != packet.get("decision_id")
        or proposal.get("evidence_packet_ref") != evidence_ref
    ):
        raise ValueError("decision-context proposal does not match evidence")

    if outcome_receipt.get("schema_version") != DECISION_OUTCOME_RECEIPT_SCHEMA_VERSION:
        raise ValueError("decision-context outcome receipt schema is invalid")
    outcome_ref = _validated_packet_ref(
        "decision-outcome",
        outcome_receipt,
        field="packet_ref",
    )
    if (
        outcome_receipt.get("goal_id") != packet.get("goal_id")
        or outcome_receipt.get("decision_id") != packet.get("decision_id")
        or outcome_receipt.get("proposal_packet_ref") != proposal_ref
    ):
        raise ValueError("decision-context outcome receipt does not match proposal")
    return evidence_ref, proposal_ref, outcome_ref, checkpoint


def _validate_lifecycle_writeback(
    *,
    event_log_path: Path,
    event_id: str,
    goal_id: str,
    decision_id: str,
    required_artifact_refs: Collection[str],
) -> Mapping[str, Any]:
    matches = [
        event
        for event in load_rollout_events(
            event_log_path.expanduser(),
            limit=_LIFECYCLE_WRITEBACK_READ_LIMIT,
        )
        if event.get("event_id") == event_id
    ]
    if len(matches) != 1:
        raise ValueError("validated lifecycle writeback event was not found")
    event = matches[0]
    if (
        event.get("schema_version") != ROLLOUT_EVENT_SCHEMA_VERSION
        or _event_id(event) != event_id
    ):
        raise ValueError("validated lifecycle writeback event is invalid")
    causality = event.get("causality")
    artifacts = event.get("artifact_refs")
    boundary = event.get("boundary")
    if (
        event.get("goal_id") != goal_id
        or event.get("event_kind") not in _LIFECYCLE_WRITEBACK_EVENT_KINDS
        or event.get("status") != "committed"
        or not isinstance(causality, Mapping)
        or causality.get("decision_id") != decision_id
        or not isinstance(artifacts, list)
        or any(not isinstance(ref, str) for ref in artifacts)
        or not set(required_artifact_refs).issubset(set(artifacts))
        or not isinstance(boundary, Mapping)
        or not boundary
        or any(value is not False for value in boundary.values())
    ):
        raise ValueError("validated lifecycle writeback does not match decision")
    return event


def commit_profile_decision_cursors(
    *,
    goal_id: str,
    agent_id: str,
    profile_path: Path,
    cursor_path: Path,
    assembly: DecisionContextAssembly,
    proposal: Mapping[str, Any],
    outcome_receipt: Mapping[str, Any],
    lifecycle_event_log_path: Path,
    lifecycle_event_id: str,
) -> dict[str, Any]:
    """CAS-commit private cursors after exact-read lifecycle writeback validation."""

    profile_digest_before = private_file_digest(profile_path)
    activation, profile = resolve_decision_context_activation(
        goal_id=goal_id,
        agent_id=agent_id,
        profile_path=profile_path,
        available_source_provider_ids=assembly.runtime_bound_provider_ids,
    )
    profile_digest_after = private_file_digest(profile_path)
    if (
        activation.get("available") is not True
        or profile is None
        or profile_digest_before != profile_digest_after
        or assembly.profile_digest != profile_digest_after
    ):
        raise ValueError("decision-context profile changed since evidence assembly")

    evidence_ref, proposal_ref, outcome_ref, checkpoint = (
        _validate_decision_packet_chain(
            assembly=assembly,
            proposal=proposal,
            outcome_receipt=outcome_receipt,
        )
    )
    packet = assembly.public_packet()
    if packet.get("goal_id") != goal_id:
        raise ValueError("decision-context assembly goal does not match profile")
    decision_id = str(packet.get("decision_id") or "")
    event = _validate_lifecycle_writeback(
        event_log_path=lifecycle_event_log_path,
        event_id=lifecycle_event_id,
        goal_id=goal_id,
        decision_id=decision_id,
        required_artifact_refs={evidence_ref, proposal_ref, outcome_ref},
    )

    proposals = dict(assembly.proposed_cursors)
    if not proposals:
        raise ValueError("decision-context assembly has no cursor proposals")
    expected = dict(assembly.expected_cursors)
    source_specs = {source.source_id: source for source in profile.sources}
    checkpoint_rows = checkpoint.get("sources")
    if not isinstance(checkpoint_rows, list):
        raise ValueError("decision-context cursor checkpoint sources are invalid")
    rows = {
        str(row.get("source_id")): row
        for row in checkpoint_rows
        if isinstance(row, Mapping)
    }
    if set(proposals) - set(source_specs):
        raise ValueError("decision-context cursor proposal source is unavailable")

    commit_rows: list[dict[str, Any]] = []
    for source_id, proposed_cursor in sorted(proposals.items()):
        row = rows.get(source_id)
        spec = source_specs[source_id]
        expected_cursor = expected.get(source_id)
        expected_before_ref = (
            _opaque_ref(
                "source-cursor",
                spec.provider_id,
                source_id,
                expected_cursor,
            )
            if expected_cursor
            else None
        )
        expected_after_ref = _opaque_ref(
            "source-cursor",
            spec.provider_id,
            source_id,
            proposed_cursor,
        )
        if (
            not isinstance(row, Mapping)
            or row.get("disposition") != "ready_after_writeback"
            or row.get("cursor_before_ref") != expected_before_ref
            or row.get("cursor_after_ref") != expected_after_ref
        ):
            raise ValueError(
                "decision-context cursor proposal does not match checkpoint"
            )
        commit_rows.append(
            {
                "source_id": source_id,
                "cursor_before_ref": expected_before_ref,
                "cursor_after_ref": expected_after_ref,
            }
        )

    cursor_state_mutated = False
    with exclusive_file_lock(cursor_path.expanduser()):
        current = _load_current_cursors(cursor_path, profile=profile)
        statuses: dict[str, str] = {}
        updated = dict(current)
        for source_id, proposed_cursor in sorted(proposals.items()):
            current_cursor = current.get(source_id)
            if current_cursor == proposed_cursor:
                statuses[source_id] = "replayed"
                continue
            if current_cursor != expected.get(source_id):
                raise ValueError(
                    "decision-context cursor state changed since evidence assembly"
                )
            updated[source_id] = proposed_cursor
            statuses[source_id] = "advanced"
            cursor_state_mutated = True
        if cursor_state_mutated:
            write_private_decision_cursors_atomic(cursor_path, updated)
        readback = _load_current_cursors(cursor_path, profile=profile)
        if any(readback.get(key) != value for key, value in proposals.items()):
            raise ValueError("decision-context cursor readback verification failed")

    for row in commit_rows:
        row["status"] = statuses[str(row["source_id"])]
    receipt: dict[str, Any] = {
        "schema_version": DECISION_CURSOR_COMMIT_RECEIPT_SCHEMA_VERSION,
        "goal_id": goal_id,
        "decision_id": decision_id,
        "checkpoint_ref": checkpoint["checkpoint_ref"],
        "evidence_packet_ref": evidence_ref,
        "proposal_packet_ref": proposal_ref,
        "outcome_receipt_ref": outcome_ref,
        "lifecycle_event_id": event["event_id"],
        "status": "committed" if cursor_state_mutated else "replayed",
        "source_count": len(commit_rows),
        "sources": commit_rows,
        "cursor_state_mutated": cursor_state_mutated,
        "readback_verified": True,
        "visibility": "public_safe",
        "core_state_mutated": False,
        "private_cursor_state_written": cursor_state_mutated,
        "raw_cursors_captured": False,
        "private_paths_captured": False,
        "raw_context_captured": False,
        "credentials_captured": False,
    }
    receipt["receipt_ref"] = _new_packet_ref("decision-cursor-commit", receipt)
    return receipt

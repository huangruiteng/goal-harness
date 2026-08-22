"""Provider-neutral contracts for Agent-scoped external event connectors.

Provider extensions own credentials, raw event bodies, source identifiers, and
cursor values.  This module validates the small routing and acknowledgement
contract that LoopX needs in order to bind one external source to one Agent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from ..file_lock import exclusive_file_lock

CONNECTOR_SCHEMA_VERSION = "agent_external_connector_v0"
ACK_DECISION_SCHEMA_VERSION = "agent_external_event_ack_decision_v0"
EFFECT_RECEIPT_SCHEMA_VERSION = "agent_external_event_effect_receipt_v0"
RESPONSE_RECEIPT_SCHEMA_VERSION = "agent_external_event_response_receipt_v0"
EVENT_SCHEMA_VERSION = "agent_external_connector_event_v0"
CURSOR_STATE_SCHEMA_VERSION = "agent_external_connector_cursor_v0"
INBOX_STATUS_SCHEMA_VERSION = "agent_external_connector_inbox_status_v0"

SAFE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}")


class ExternalSourceKind(str, Enum):
    GROUP_MESSAGE = "group_message"
    DOCUMENT_COMMENT = "document_comment"


class ExternalCapturePolicy(str, Enum):
    ADDRESSED_ONLY = "addressed_only"
    CONFIGURED_SOURCE_ALL = "configured_source_all"
    INCREMENTAL = "incremental"


class ExternalIngressPolicy(str, Enum):
    LIVE_STEERING = "live_steering"
    SESSION_QUEUE = "session_queue"
    ASYNC_INBOX = "async_inbox"


class ExternalResponsePolicy(str, Enum):
    NO_RESPONSE = "no_response"
    SOURCE_THREAD = "source_thread"
    TOPIC_REPLY = "topic_reply"
    CONFIGURED_MIRROR = "configured_mirror"


class ExternalConnectorLifecycle(str, Enum):
    CONNECTED = "connected"
    LISTENING = "listening"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class ExternalConnectorCapability(str, Enum):
    REALTIME_RECEIVE = "realtime_receive"
    HISTORY_CATCH_UP = "history_catch_up"
    RESPONSE_WRITE = "response_write"
    RESPONSE_READBACK = "response_readback"
    ACKNOWLEDGE = "acknowledge"


class ExternalEffectKind(str, Enum):
    WORKING_SESSION_TURN = "working_session_turn"
    TODO_UPDATE = "todo_update"
    AUTHORITY_UPDATE = "authority_update"
    DESIGN_UPDATE = "design_update"
    NO_FOLLOW_UP = "no_follow_up"


def _enum_value(enum_type: type[Enum], value: Any, *, field: str) -> str:
    normalized = str(value or "").strip().lower()
    try:
        selected = enum_type(normalized)
    except ValueError as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ValueError(f"{field} must be one of: {allowed}") from exc
    return str(selected.value)


def _safe_token(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not SAFE_TOKEN_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must be an opaque public-safe token")
    return normalized


def external_event_ref(event_id: str) -> str:
    """Return the content-free identity used to bind public-safe receipts."""

    event = _safe_token(event_id, field="event_id")
    return f"sha256:{hashlib.sha256(event.encode('utf-8')).hexdigest()[:24]}"


def build_external_event_response_receipt(
    *,
    event_id: str,
    external_write_performed: bool,
    verification_performed: bool,
    response_verified: bool,
) -> dict[str, Any]:
    """Normalize provider proof into one event-bound response receipt."""

    proof = {
        "external_write_performed": external_write_performed,
        "verification_performed": verification_performed,
        "response_verified": response_verified,
    }
    if any(not isinstance(value, bool) for value in proof.values()):
        raise TypeError("external response proof fields must be booleans")
    return {
        "schema_version": RESPONSE_RECEIPT_SCHEMA_VERSION,
        "event_ref": external_event_ref(event_id),
        **proof,
        "private_event_id_captured": False,
        "private_response_content_captured": False,
    }


def _owner_local_ref(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or "://" in normalized
        or any(not part or part in {".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{field} must be an owner-local opaque reference")
    return normalized


def _private_value(value: Any, *, field: str, limit: int = 2048) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > limit
        or any(ord(character) < 32 for character in normalized)
    ):
        raise ValueError(f"{field} must be a bounded owner-private value")
    return normalized


def _timestamp(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _capability_values(values: Sequence[str]) -> list[str]:
    normalized = {
        _enum_value(ExternalConnectorCapability, value, field="capabilities")
        for value in values
    }
    return sorted(normalized)


def normalize_external_connector_binding(
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate an owner-local Connector binding at a caller boundary."""
    if binding.get("schema_version") != CONNECTOR_SCHEMA_VERSION:
        raise ValueError("external connector binding schema is invalid")
    return build_external_connector_binding(
        goal_ref=str(binding.get("goal_ref") or ""),
        agent_ref=str(binding.get("agent_ref") or ""),
        provider_kind=str(binding.get("provider_kind") or ""),
        source_kind=str(binding.get("source_kind") or ""),
        source_ref=str(binding.get("source_ref") or ""),
        capture_policy=str(binding.get("capture_policy") or ""),
        ingress_policy=str(binding.get("ingress_policy") or ""),
        response_policy=str(binding.get("response_policy") or ""),
        cursor_ref=(
            str(binding.get("cursor_ref")) if binding.get("cursor_ref") else None
        ),
        lifecycle=str(binding.get("lifecycle") or ""),
        capabilities=[str(value) for value in binding.get("capabilities", [])],
        session_ref=(
            str(binding.get("session_ref")) if binding.get("session_ref") else None
        ),
        inbox_ref=(str(binding.get("inbox_ref")) if binding.get("inbox_ref") else None),
    )


def build_external_connector_binding(
    *,
    goal_ref: str,
    agent_ref: str,
    provider_kind: str,
    source_kind: str,
    source_ref: str,
    capture_policy: str,
    ingress_policy: str,
    response_policy: str,
    cursor_ref: str | None,
    lifecycle: str,
    capabilities: Sequence[str],
    session_ref: str | None = None,
    inbox_ref: str | None = None,
) -> dict[str, Any]:
    """Validate and return one owner-local Agent Connector binding."""

    goal = _safe_token(goal_ref, field="goal_ref")
    agent = _safe_token(agent_ref, field="agent_ref")
    provider = _safe_token(provider_kind, field="provider_kind")
    source = _enum_value(ExternalSourceKind, source_kind, field="source_kind")
    source_reference = _safe_token(source_ref, field="source_ref")
    capture = _enum_value(
        ExternalCapturePolicy,
        capture_policy,
        field="capture_policy",
    )
    ingress = _enum_value(
        ExternalIngressPolicy,
        ingress_policy,
        field="ingress_policy",
    )
    response = _enum_value(
        ExternalResponsePolicy,
        response_policy,
        field="response_policy",
    )
    lifecycle_value = _enum_value(
        ExternalConnectorLifecycle,
        lifecycle,
        field="lifecycle",
    )
    capability_values = _capability_values(capabilities)
    capability_set = set(capability_values)
    session = _safe_token(session_ref, field="session_ref") if session_ref else None
    inbox = _owner_local_ref(inbox_ref, field="inbox_ref") if inbox_ref else None
    cursor = _owner_local_ref(cursor_ref, field="cursor_ref") if cursor_ref else None

    if (
        ingress
        in {
            ExternalIngressPolicy.LIVE_STEERING.value,
            ExternalIngressPolicy.SESSION_QUEUE.value,
        }
        and not session
    ):
        raise ValueError(f"{ingress} requires an exact session_ref")
    if ingress == ExternalIngressPolicy.ASYNC_INBOX.value and not inbox:
        raise ValueError("async_inbox requires an owner-local inbox_ref")
    if ingress == ExternalIngressPolicy.ASYNC_INBOX.value and session:
        raise ValueError("async_inbox cannot bind an exact session_ref")
    if (
        capture == ExternalCapturePolicy.INCREMENTAL.value
        or ExternalConnectorCapability.HISTORY_CATCH_UP.value in capability_set
        or ExternalConnectorCapability.ACKNOWLEDGE.value in capability_set
    ) and not cursor:
        raise ValueError(
            "incremental capture, history_catch_up, and acknowledge require an "
            "owner-local cursor_ref"
        )
    response_capabilities = {
        ExternalConnectorCapability.RESPONSE_WRITE.value,
        ExternalConnectorCapability.RESPONSE_READBACK.value,
    }
    if response == ExternalResponsePolicy.NO_RESPONSE.value:
        if capability_set.intersection(response_capabilities):
            raise ValueError("no_response cannot advertise response capabilities")
    elif not response_capabilities.issubset(capability_set):
        raise ValueError(
            "a response policy requires response_write and response_readback"
        )

    binding: dict[str, Any] = {
        "schema_version": CONNECTOR_SCHEMA_VERSION,
        "goal_ref": goal,
        "agent_ref": agent,
        "provider_kind": provider,
        "source_kind": source,
        "source_ref": source_reference,
        "capture_policy": capture,
        "ingress_policy": ingress,
        "response_policy": response,
        "cursor_ref": cursor,
        "lifecycle": lifecycle_value,
        "capabilities": capability_values,
    }
    if session:
        binding["session_ref"] = session
    if inbox:
        binding["inbox_ref"] = inbox
    return binding


def project_external_connector_status(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Return a content-free status projection without owner-local references."""

    normalized = normalize_external_connector_binding(binding)
    return {
        "schema_version": "agent_external_connector_status_v0",
        "goal_ref": normalized["goal_ref"],
        "agent_ref": normalized["agent_ref"],
        "provider_kind": normalized["provider_kind"],
        "source_kind": normalized["source_kind"],
        "capture_policy": normalized["capture_policy"],
        "ingress_policy": normalized["ingress_policy"],
        "response_policy": normalized["response_policy"],
        "lifecycle": normalized["lifecycle"],
        "capabilities": normalized["capabilities"],
        "session_bound": "session_ref" in normalized,
        "inbox_bound": "inbox_ref" in normalized,
        "cursor_bound": normalized["cursor_ref"] is not None,
        "private_source_ref_captured": False,
        "private_cursor_ref_captured": False,
    }


def decide_external_event_ack(
    *,
    event_id: str,
    effect_receipt: Mapping[str, Any] | None,
    response_policy: str,
    response_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed until durable effect and required response readback exist."""

    event = _safe_token(event_id, field="event_id")
    response = _enum_value(
        ExternalResponsePolicy,
        response_policy,
        field="response_policy",
    )
    effect_ready = bool(
        isinstance(effect_receipt, Mapping)
        and effect_receipt.get("schema_version") == EFFECT_RECEIPT_SCHEMA_VERSION
        and str(effect_receipt.get("event_id") or "") == event
        and SAFE_TOKEN_PATTERN.fullmatch(str(effect_receipt.get("effect_id") or ""))
        and str(effect_receipt.get("status") or "") == "committed"
        and str(effect_receipt.get("effect_kind") or "")
        in {item.value for item in ExternalEffectKind}
    )
    response_required = response != ExternalResponsePolicy.NO_RESPONSE.value
    response_ready = bool(
        not response_required
        or (
            isinstance(response_receipt, Mapping)
            and response_receipt.get("schema_version")
            == RESPONSE_RECEIPT_SCHEMA_VERSION
            and response_receipt.get("event_ref") == external_event_ref(event)
            and response_receipt.get("external_write_performed") is True
            and response_receipt.get("verification_performed") is True
            and response_receipt.get("response_verified") is True
        )
    )
    ack_allowed = effect_ready and response_ready
    return {
        "schema_version": ACK_DECISION_SCHEMA_VERSION,
        "ack_allowed": ack_allowed,
        "effect_ready": effect_ready,
        "response_required": response_required,
        "response_ready": response_ready,
        "reason": (
            "ready"
            if ack_allowed
            else "durable_effect_required"
            if not effect_ready
            else "verified_response_required"
        ),
        "private_event_content_captured": False,
        "private_provider_payload_captured": False,
    }


def build_external_connector_event(
    *,
    event_id: str,
    content: str,
    occurred_at: str,
    addressed: bool,
    event_cursor: str,
    anchor_ref: str | None = None,
    reply_chain_ref: str | None = None,
) -> dict[str, Any]:
    """Return one compact owner-private event accepted from a provider.

    Provider extensions translate their payloads into this envelope.  The
    body and provider references are deliberately suitable only for the
    owner-local inbox; public status uses :func:`inspect_external_connector_inbox`.
    """

    body = str(content or "").strip()
    if not body or len(body) > 20_000 or "\x00" in body:
        raise ValueError("content must be non-empty owner-private text")
    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": _safe_token(event_id, field="event_id"),
        "content": body,
        "occurred_at": _timestamp(occurred_at, field="occurred_at"),
        "addressed": bool(addressed),
        "event_cursor": _private_value(event_cursor, field="event_cursor"),
    }
    if anchor_ref:
        event["anchor_ref"] = _private_value(anchor_ref, field="anchor_ref")
    if reply_chain_ref:
        event["reply_chain_ref"] = _private_value(
            reply_chain_ref,
            field="reply_chain_ref",
        )
    return event


def _event_from_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != EVENT_SCHEMA_VERSION:
        raise ValueError("external connector event schema is invalid")
    return build_external_connector_event(
        event_id=str(value.get("event_id") or ""),
        content=str(value.get("content") or ""),
        occurred_at=str(value.get("occurred_at") or ""),
        addressed=value.get("addressed") is True,
        event_cursor=str(value.get("event_cursor") or ""),
        anchor_ref=(str(value.get("anchor_ref")) if value.get("anchor_ref") else None),
        reply_chain_ref=(
            str(value.get("reply_chain_ref")) if value.get("reply_chain_ref") else None
        ),
    )


def _resolve_owner_local_path(
    *,
    project: str | Path,
    ref: str,
    field: str,
) -> Path:
    root = Path(project).expanduser().resolve()
    relative = PurePosixPath(_owner_local_ref(ref, field=field))
    resolved = (root / Path(*relative.parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes the owner project") from exc
    return resolved


def _binding_paths(
    *,
    project: str | Path,
    binding: Mapping[str, Any],
) -> tuple[dict[str, Any], Path, Path]:
    normalized = normalize_external_connector_binding(binding)
    if normalized["ingress_policy"] != ExternalIngressPolicy.ASYNC_INBOX.value:
        raise ValueError("external connector inbox runtime requires async_inbox")
    inbox_ref = str(normalized.get("inbox_ref") or "")
    cursor_ref = str(normalized.get("cursor_ref") or "")
    if not inbox_ref or not cursor_ref:
        raise ValueError("external connector inbox requires inbox_ref and cursor_ref")
    inbox = _resolve_owner_local_path(
        project=project,
        ref=inbox_ref,
        field="inbox_ref",
    )
    cursor = _resolve_owner_local_path(
        project=project,
        ref=cursor_ref,
        field="cursor_ref",
    )
    return normalized, inbox, cursor


def _default_cursor_state() -> dict[str, Any]:
    return {
        "schema_version": CURSOR_STATE_SCHEMA_VERSION,
        "committed_cursor": None,
        "next_sequence": 1,
        "acknowledged_event_ids": [],
        "last_capture_at": None,
        "failure_count": 0,
        "last_failure_at": None,
        "last_error_code": None,
    }


def _load_cursor_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _default_cursor_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("external connector cursor state is unreadable") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != CURSOR_STATE_SCHEMA_VERSION
    ):
        raise ValueError("external connector cursor state schema is invalid")
    state = _default_cursor_state()
    state["committed_cursor"] = (
        _private_value(value.get("committed_cursor"), field="committed_cursor")
        if value.get("committed_cursor")
        else None
    )
    next_sequence = value.get("next_sequence")
    if not isinstance(next_sequence, int) or next_sequence < 1:
        raise ValueError("external connector next_sequence is invalid")
    state["next_sequence"] = next_sequence
    acknowledged = value.get("acknowledged_event_ids")
    if not isinstance(acknowledged, list):
        raise TypeError("external connector acknowledged_event_ids is invalid")
    state["acknowledged_event_ids"] = sorted(
        {_safe_token(item, field="acknowledged_event_ids") for item in acknowledged}
    )
    for field in ("last_capture_at", "last_failure_at"):
        state[field] = (
            _timestamp(value.get(field), field=field) if value.get(field) else None
        )
    failure_count = value.get("failure_count", 0)
    if not isinstance(failure_count, int) or failure_count < 0:
        raise ValueError("external connector failure_count is invalid")
    state["failure_count"] = failure_count
    state["last_error_code"] = (
        _safe_token(value.get("last_error_code"), field="last_error_code")
        if value.get("last_error_code")
        else None
    )
    return state


def _write_private_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _event_path(inbox: Path, event_id: str) -> Path:
    digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
    return inbox / "events" / f"{digest}.json"


def _stored_events(inbox: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    events_root = inbox / "events"
    for path in sorted(events_root.glob("*.json")) if events_root.is_dir() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("external connector inbox event is unreadable") from exc
        if not isinstance(value, Mapping):
            raise TypeError("external connector inbox event is invalid")
        event = _event_from_mapping(value)
        sequence = value.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            raise ValueError("external connector event sequence is invalid")
        event["sequence"] = sequence
        if value.get("page_next_cursor"):
            event["page_next_cursor"] = _private_value(
                value.get("page_next_cursor"),
                field="page_next_cursor",
            )
        events.append(event)
    events.sort(key=lambda item: (item["sequence"], item["event_id"]))
    return events


def capture_external_connector_events(
    *,
    project: str | Path,
    binding: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    expected_cursor: str | None,
    next_cursor: str,
    max_pending: int = 1000,
    execute: bool = False,
) -> dict[str, Any]:
    """Capture one bounded provider page without advancing past pending events."""

    normalized, inbox, cursor_path = _binding_paths(
        project=project,
        binding=binding,
    )
    capabilities = set(normalized["capabilities"])
    if ExternalConnectorCapability.HISTORY_CATCH_UP.value not in capabilities:
        raise ValueError("external connector does not advertise history_catch_up")
    requested_next_cursor = _private_value(next_cursor, field="next_cursor")
    requested_expected_cursor = (
        _private_value(expected_cursor, field="expected_cursor")
        if expected_cursor is not None
        else None
    )
    if len(events) > 500:
        raise ValueError("external connector capture page exceeds 500 events")
    bounded_pending = max(1, min(int(max_pending), 10_000))
    canonical = [_event_from_mapping(value) for value in events]

    def operation() -> dict[str, Any]:
        state = _load_cursor_state(cursor_path)
        if state["committed_cursor"] != requested_expected_cursor:
            return {
                "ok": False,
                "schema_version": "agent_external_connector_capture_v0",
                "status": "cursor_mismatch",
                "execute": execute,
                "requested_count": len(canonical),
                "accepted_count": 0,
                "filtered_count": 0,
                "duplicate_count": 0,
                "cursor_advanced": False,
                "private_event_content_captured": False,
                "private_cursor_value_captured": False,
            }
        existing = _stored_events(inbox)
        existing_ids = {str(item["event_id"]) for item in existing}
        acknowledged = set(state["acknowledged_event_ids"])
        accepted: list[dict[str, Any]] = []
        duplicate_ids: set[str] = set()
        filtered_count = 0
        duplicate_count = 0
        for event in canonical:
            event_id = str(event["event_id"])
            if (
                event_id in acknowledged
                or event_id in existing_ids
                or any(str(item["event_id"]) == event_id for item in accepted)
            ):
                duplicate_count += 1
                duplicate_ids.add(event_id)
                continue
            if (
                normalized["capture_policy"]
                == ExternalCapturePolicy.ADDRESSED_ONLY.value
                and event["addressed"] is not True
            ):
                filtered_count += 1
                continue
            accepted.append(event)

        current_pending_count = sum(
            str(item["event_id"]) not in acknowledged for item in existing
        )
        if current_pending_count + len(accepted) > bounded_pending:
            return {
                "ok": False,
                "schema_version": "agent_external_connector_capture_v0",
                "status": "backpressure_required",
                "execute": execute,
                "requested_count": len(canonical),
                "accepted_count": 0,
                "filtered_count": filtered_count,
                "duplicate_count": duplicate_count,
                "pending_count": current_pending_count,
                "max_pending": bounded_pending,
                "cursor_advanced": False,
                "private_event_content_captured": False,
                "private_cursor_value_captured": False,
            }

        sequence = max(
            int(state["next_sequence"]),
            max((int(item["sequence"]) for item in existing), default=0) + 1,
        )
        stored: list[dict[str, Any]] = []
        for event in accepted:
            stored.append({**event, "sequence": sequence})
            sequence += 1
        if stored:
            stored[-1]["page_next_cursor"] = requested_next_cursor
        cursor_advanced = bool(
            not stored and (not duplicate_ids or duplicate_ids.issubset(acknowledged))
        )
        updated_state = {
            **state,
            "committed_cursor": (
                requested_next_cursor if cursor_advanced else state["committed_cursor"]
            ),
            "next_sequence": sequence,
            "last_capture_at": _now_iso(),
        }
        if execute:
            for event in stored:
                _write_private_json_atomic(
                    _event_path(inbox, str(event["event_id"])),
                    event,
                )
            _write_private_json_atomic(cursor_path, updated_state)
        return {
            "ok": True,
            "schema_version": "agent_external_connector_capture_v0",
            "status": "captured" if stored else "page_checkpointed",
            "execute": execute,
            "requested_count": len(canonical),
            "accepted_count": len(stored),
            "filtered_count": filtered_count,
            "duplicate_count": duplicate_count,
            "cursor_advanced": cursor_advanced,
            "write_performed": execute,
            "private_event_content_captured": False,
            "private_cursor_value_captured": False,
        }

    if not execute:
        return operation()
    with exclusive_file_lock(
        cursor_path,
        operation="capture_external_connector_events",
    ):
        return operation()


def drain_external_connector_inbox(
    *,
    project: str | Path,
    binding: Mapping[str, Any],
    limit: int = 20,
) -> dict[str, Any]:
    """Return ordered owner-private pending events to the bound Agent only."""

    _normalized, inbox, cursor_path = _binding_paths(project=project, binding=binding)
    state = _load_cursor_state(cursor_path)
    acknowledged = set(state["acknowledged_event_ids"])
    bounded_limit = max(1, min(int(limit), 100))
    pending = [
        event
        for event in _stored_events(inbox)
        if str(event["event_id"]) not in acknowledged
    ]
    items = pending[:bounded_limit]
    return {
        "ok": True,
        "schema_version": "agent_external_connector_drain_v0",
        "pending_count": len(pending),
        "returned_count": len(items),
        "items": items,
        "local_private_content_returned": bool(items),
        "external_reads_performed": False,
        "external_writes_performed": False,
    }


def inspect_external_connector_inbox(
    *,
    project: str | Path,
    binding: Mapping[str, Any],
    now: datetime | None = None,
    stale_after_seconds: int = 300,
) -> dict[str, Any]:
    """Project content-free pending, failure, and freshness state."""

    normalized, inbox, cursor_path = _binding_paths(project=project, binding=binding)
    state = _load_cursor_state(cursor_path)
    acknowledged = set(state["acknowledged_event_ids"])
    pending = [
        event
        for event in _stored_events(inbox)
        if str(event["event_id"]) not in acknowledged
    ]
    current = (now or datetime.now(UTC)).astimezone(UTC)
    oldest_age_seconds: int | None = None
    if pending:
        oldest = min(
            datetime.fromisoformat(str(event["occurred_at"])) for event in pending
        )
        oldest_age_seconds = max(0, int((current - oldest).total_seconds()))
    last_capture_at = state.get("last_capture_at")
    if not last_capture_at:
        freshness = "never_captured"
    else:
        captured_at = datetime.fromisoformat(str(last_capture_at))
        freshness = (
            "stale"
            if (current - captured_at).total_seconds() > max(1, stale_after_seconds)
            else "current"
        )
    return {
        "ok": True,
        "schema_version": INBOX_STATUS_SCHEMA_VERSION,
        "goal_ref": normalized["goal_ref"],
        "agent_ref": normalized["agent_ref"],
        "provider_kind": normalized["provider_kind"],
        "source_kind": normalized["source_kind"],
        "pending_count": len(pending),
        "oldest_pending_age_seconds": oldest_age_seconds,
        "failure_count": state["failure_count"],
        "last_failure_at": state["last_failure_at"],
        "last_error_code": state["last_error_code"],
        "freshness": freshness,
        "cursor_bound": True,
        "private_event_ids_captured": False,
        "private_event_content_captured": False,
        "private_source_ref_captured": False,
        "private_cursor_value_captured": False,
    }


def record_external_connector_failure(
    *,
    project: str | Path,
    binding: Mapping[str, Any],
    error_code: str,
    execute: bool = False,
) -> dict[str, Any]:
    """Persist a content-free provider failure without its payload."""

    _normalized, _inbox, cursor_path = _binding_paths(
        project=project,
        binding=binding,
    )
    normalized_error = _safe_token(error_code, field="error_code")

    def operation() -> dict[str, Any]:
        state = _load_cursor_state(cursor_path)
        updated_state = {
            **state,
            "failure_count": int(state["failure_count"]) + 1,
            "last_failure_at": _now_iso(),
            "last_error_code": normalized_error,
        }
        if execute:
            _write_private_json_atomic(cursor_path, updated_state)
        return {
            "ok": True,
            "schema_version": "agent_external_connector_failure_v0",
            "execute": execute,
            "recorded": execute,
            "error_code": normalized_error,
            "failure_count": updated_state["failure_count"],
            "private_provider_payload_captured": False,
        }

    if not execute:
        return operation()
    with exclusive_file_lock(
        cursor_path,
        operation="record_external_connector_failure",
    ):
        return operation()


def settle_external_connector_event(
    *,
    project: str | Path,
    binding: Mapping[str, Any],
    event_id: str,
    effect_receipt: Mapping[str, Any] | None,
    response_receipt: Mapping[str, Any] | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """ACK one ordered event and advance its page cursor only after proof."""

    normalized, inbox, cursor_path = _binding_paths(project=project, binding=binding)
    event = _safe_token(event_id, field="event_id")
    if ExternalConnectorCapability.ACKNOWLEDGE.value not in set(
        normalized["capabilities"]
    ):
        raise ValueError("external connector does not advertise acknowledge")

    def operation() -> dict[str, Any]:
        state = _load_cursor_state(cursor_path)
        acknowledged = set(state["acknowledged_event_ids"])
        if event in acknowledged:
            private_event_deleted = False
            if execute:
                event_path = _event_path(inbox, event)
                private_event_deleted = event_path.is_file()
                event_path.unlink(missing_ok=True)
            return {
                "ok": True,
                "schema_version": "agent_external_connector_settlement_v0",
                "status": "already_acknowledged",
                "execute": execute,
                "event_ref": external_event_ref(event),
                "cursor_advanced": False,
                "private_event_deleted": private_event_deleted,
                "private_event_id_captured": False,
                "private_cursor_value_captured": False,
            }
        stored = _stored_events(inbox)
        event_record = next(
            (item for item in stored if str(item["event_id"]) == event),
            None,
        )
        if event_record is None:
            raise ValueError("external connector event is not captured")
        pending = [item for item in stored if str(item["event_id"]) not in acknowledged]
        if not pending or str(pending[0]["event_id"]) != event:
            return {
                "ok": False,
                "schema_version": "agent_external_connector_settlement_v0",
                "status": "ordered_event_required",
                "execute": execute,
                "event_ref": external_event_ref(event),
                "cursor_advanced": False,
                "private_event_id_captured": False,
                "private_cursor_value_captured": False,
            }
        ack_decision = decide_external_event_ack(
            event_id=event,
            effect_receipt=effect_receipt,
            response_policy=str(normalized["response_policy"]),
            response_receipt=response_receipt,
        )
        if not ack_decision["ack_allowed"]:
            return {
                "ok": False,
                "schema_version": "agent_external_connector_settlement_v0",
                "status": ack_decision["reason"],
                "execute": execute,
                "event_ref": external_event_ref(event),
                "cursor_advanced": False,
                "ack_decision": ack_decision,
                "private_event_id_captured": False,
                "private_cursor_value_captured": False,
            }
        acknowledged.add(event)
        page_next_cursor = event_record.get("page_next_cursor")
        cursor_advanced = bool(page_next_cursor)
        updated_state = {
            **state,
            "acknowledged_event_ids": sorted(acknowledged),
            "committed_cursor": (
                page_next_cursor if page_next_cursor else state["committed_cursor"]
            ),
        }
        if execute:
            _write_private_json_atomic(cursor_path, updated_state)
            event_path = _event_path(inbox, event)
            private_event_deleted = event_path.is_file()
            event_path.unlink(missing_ok=True)
        else:
            private_event_deleted = False
        return {
            "ok": True,
            "schema_version": "agent_external_connector_settlement_v0",
            "status": "acknowledged" if execute else "preview_ready",
            "execute": execute,
            "event_ref": external_event_ref(event),
            "cursor_advanced": cursor_advanced,
            "private_event_deleted": private_event_deleted,
            "effect_kind": str((effect_receipt or {}).get("effect_kind") or ""),
            "private_event_id_captured": False,
            "private_cursor_value_captured": False,
        }

    if not execute:
        return operation()
    with exclusive_file_lock(
        cursor_path,
        operation="settle_external_connector_event",
    ):
        return operation()

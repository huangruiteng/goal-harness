"""Provider-neutral contracts for Agent-scoped external event connectors.

Provider extensions own credentials, raw event bodies, source identifiers, and
cursor values.  This module validates the small routing and acknowledgement
contract that LoopX needs in order to bind one external source to one Agent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

CONNECTOR_SCHEMA_VERSION = "agent_external_connector_v0"
ACK_DECISION_SCHEMA_VERSION = "agent_external_event_ack_decision_v0"
EFFECT_RECEIPT_SCHEMA_VERSION = "agent_external_event_effect_receipt_v0"

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


def _capability_values(values: Sequence[str]) -> list[str]:
    normalized = {
        _enum_value(ExternalConnectorCapability, value, field="capabilities")
        for value in values
    }
    return sorted(normalized)


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

    if binding.get("schema_version") != CONNECTOR_SCHEMA_VERSION:
        raise ValueError("external connector binding schema is invalid")
    normalized = build_external_connector_binding(
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
            and response_receipt.get("external_write_performed") is True
            and response_receipt.get("verification_performed") is True
            and (
                response_receipt.get("response_verified") is True
                or response_receipt.get("reply_verified") is True
                or response_receipt.get("readback_verified") is True
            )
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

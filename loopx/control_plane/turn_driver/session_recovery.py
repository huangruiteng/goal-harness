"""Typed failed-Turn host session recovery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .driver import reconcile_failed_turn_session_request


HOST_RECOVERY_SCHEMA_VERSION = "loopx_turn_host_recovery_v0"
HOST_RECOVERY_KINDS = frozenset({"resume_session"})

SessionBindingResolver = Callable[
    [Mapping[str, Any]],
    Mapping[str, Any] | None,
]


def require_host_recovery_kind(value: str) -> str:
    if value not in HOST_RECOVERY_KINDS:
        raise ValueError("unsupported built-in host recovery kind")
    return value


def build_host_recovery_record(kind: str) -> dict[str, str]:
    return {
        "schema_version": HOST_RECOVERY_SCHEMA_VERSION,
        "kind": require_host_recovery_kind(kind),
    }


def reconcile_failed_turn_retry_request(
    request: Mapping[str, Any],
    journal: Mapping[str, Any],
    *,
    session_binding_resolver: SessionBindingResolver | None,
) -> dict[str, Any]:
    recovery_value = journal.get("host_recovery")
    recovery = dict(recovery_value) if isinstance(recovery_value, Mapping) else {}
    if not recovery:
        return dict(request)
    if recovery.get("schema_version") != HOST_RECOVERY_SCHEMA_VERSION:
        raise ValueError("failed-Turn host recovery has an unsupported schema")
    if recovery.get("kind") not in HOST_RECOVERY_KINDS:
        raise ValueError("failed-Turn host recovery has an unsupported kind")
    receipt_value = journal.get("receipt")
    receipt = dict(receipt_value) if isinstance(receipt_value, Mapping) else {}
    if receipt.get("failed_phase") != "host_execute":
        raise ValueError("failed-Turn session recovery requires a host execution failure")
    if session_binding_resolver is None:
        raise ValueError("failed-Turn session recovery has no binding resolver")
    envelope_value = request.get("turn_envelope")
    envelope = dict(envelope_value) if isinstance(envelope_value, Mapping) else {}
    try:
        session_binding = session_binding_resolver(envelope)
    except Exception:  # noqa: BLE001 - provider boundary fails closed
        raise ValueError(
            "failed-Turn recovery session binding could not be resolved"
        ) from None
    return reconcile_failed_turn_session_request(
        request,
        session_binding=session_binding,
    )

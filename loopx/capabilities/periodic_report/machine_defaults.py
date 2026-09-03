from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...control_plane.todos.contract import normalize_todo_claimed_by
from ..machine_configuration.contract import (
    MACHINE_CONFIGURATION_SCHEMA,
    MachineConfigurationNamespace,
    MachineConfigurationRegistry,
    machine_configuration_revision,
    normalize_machine_configuration,
)


MACHINE_DEFAULTS_SCHEMA = MACHINE_CONFIGURATION_SCHEMA
PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA = "periodic_report_machine_defaults_v0"
GOAL_SUBSCRIPTION_SCHEMA = "periodic_report_goal_subscription_v0"
DELIVERY_IDENTITY_SCHEMA = "periodic_report_goal_delivery_identity_v0"
DELIVERY_PLAN_REQUEST_SCHEMA = "periodic_report_goal_delivery_plan_request_v0"
DELIVERY_PLAN_SCHEMA = "periodic_report_goal_delivery_plan_v0"

_INHERITANCE_MODE = "live_machine_default"


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _reject_unknown(value: Mapping[str, Any], *, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} contains unsupported fields: {', '.join(unknown)}")


def _text(value: object, label: str, *, maximum: int = 160) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return text


def _agent_id(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = normalize_todo_claimed_by(value)
    if normalized is None:
        raise ValueError(f"{label} must be a public-safe Agent id")
    return normalized


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def normalize_periodic_report_machine_defaults(
    raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the periodic-report-owned machine configuration namespace."""

    periodic = _mapping(raw, "periodic_report")
    _reject_unknown(
        periodic,
        allowed={
            "schema_version",
            "enabled",
            "inheritance",
            "profile_preset",
            "route_ref",
            "timezone",
        },
        label="periodic_report",
    )
    if periodic.get("schema_version") != PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA:
        raise ValueError(
            "periodic_report must use " + PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA
        )
    enabled = periodic.get("enabled")
    if not isinstance(enabled, bool):
        raise TypeError("periodic_report.enabled must be a boolean")
    inheritance = _text(
        periodic.get("inheritance", _INHERITANCE_MODE),
        "periodic_report.inheritance",
    )
    if inheritance != _INHERITANCE_MODE:
        raise ValueError("periodic_report.inheritance must be live_machine_default")
    timezone = _text(
        periodic.get("timezone", "UTC"),
        "periodic_report.timezone",
    )
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("periodic_report.timezone is unknown") from exc
    normalized_periodic: dict[str, Any] = {
        "schema_version": PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA,
        "enabled": enabled,
        "inheritance": inheritance,
        "timezone": timezone,
    }
    if enabled:
        normalized_periodic["profile_preset"] = _text(
            periodic.get("profile_preset"),
            "periodic_report.profile_preset",
        )
        normalized_periodic["route_ref"] = _text(
            periodic.get("route_ref"),
            "periodic_report.route_ref",
        )
    else:
        for field in ("profile_preset", "route_ref"):
            value = str(periodic.get(field) or "").strip()
            if value:
                normalized_periodic[field] = _text(
                    value,
                    f"periodic_report.{field}",
                )
    return normalized_periodic


def periodic_report_machine_configuration_namespace() -> MachineConfigurationNamespace:
    return MachineConfigurationNamespace(
        namespace="periodic_report",
        schema_versions=frozenset({PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA}),
        normalize=normalize_periodic_report_machine_defaults,
        project_public=lambda value: dict(value),
    )


def _machine_configuration_registry() -> MachineConfigurationRegistry:
    return MachineConfigurationRegistry().register(
        periodic_report_machine_configuration_namespace()
    )


def normalize_loopx_machine_defaults(raw: object) -> dict[str, Any]:
    """Compatibility name for the generic typed machine configuration envelope."""

    return normalize_machine_configuration(
        raw, registry=_machine_configuration_registry()
    )


def loopx_machine_defaults_revision(raw: object) -> str:
    """Compatibility revision for a validated machine configuration."""

    return machine_configuration_revision(normalize_loopx_machine_defaults(raw))


def _periodic_report_defaults(
    machine_configuration: Mapping[str, Any],
) -> tuple[dict[str, Any], str] | None:
    """Read only this capability's namespace from a generic machine document."""

    payload = _mapping(machine_configuration, "machine_configuration")
    _reject_unknown(
        payload,
        allowed={"schema_version", "namespaces"},
        label="machine_configuration",
    )
    if payload.get("schema_version") != MACHINE_CONFIGURATION_SCHEMA:
        raise ValueError(
            f"machine_configuration must use {MACHINE_CONFIGURATION_SCHEMA}"
        )
    namespaces = _mapping(
        payload.get("namespaces"),
        "machine_configuration.namespaces",
    )
    raw_periodic = namespaces.get("periodic_report")
    if raw_periodic is None:
        return None
    periodic = normalize_periodic_report_machine_defaults(
        _mapping(
            raw_periodic,
            "machine_configuration.namespaces.periodic_report",
        )
    )
    source_revision = _digest(
        {
            "namespace": "periodic_report",
            "configuration": periodic,
        }
    )
    return periodic, source_revision


def _goal_periodic_report(goal: Mapping[str, Any]) -> dict[str, Any] | None:
    control_plane = goal.get("control_plane")
    if not isinstance(control_plane, Mapping):
        return None
    periodic = control_plane.get("periodic_report")
    return dict(periodic) if isinstance(periodic, Mapping) else None


def _normalized_goal_subscription(
    *,
    goal_id: str,
    config: Mapping[str, Any],
    source: str,
    source_revision: str | None,
) -> dict[str, Any]:
    enabled = config.get("enabled")
    if not isinstance(enabled, bool):
        raise TypeError("goal periodic_report.enabled must be a boolean")
    timezone_name = _text(
        config.get("timezone", "UTC"), "goal periodic_report.timezone"
    )
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("goal periodic_report.timezone is unknown") from exc
    profile_preset = str(config.get("profile_preset") or "").strip() or None
    route_ref = str(config.get("route_ref") or "").strip() or None
    if enabled:
        profile_preset = _text(
            profile_preset, "goal periodic_report.profile_preset"
        )
        route_ref = _text(route_ref, "goal periodic_report.route_ref")
    subscription: dict[str, Any] = {
        "schema_version": GOAL_SUBSCRIPTION_SCHEMA,
        "goal_id": goal_id,
        "enabled": enabled,
        "source": source,
        "source_revision": source_revision,
        "profile_preset": profile_preset,
        "route_ref": route_ref,
        "timezone": timezone_name,
    }
    subscription["effective_revision"] = _digest(subscription)
    return subscription


def resolve_goal_periodic_report_subscription(
    goal: Mapping[str, Any],
    machine_defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve one live machine default beneath a complete Goal override."""

    goal_id = _text(goal.get("id"), "goal.id")
    existing = _goal_periodic_report(goal)
    if existing is not None:
        return _normalized_goal_subscription(
            goal_id=goal_id,
            config=existing,
            source="goal_override",
            source_revision=None,
        )
    if machine_defaults is None:
        return _normalized_goal_subscription(
            goal_id=goal_id,
            config={"enabled": False, "timezone": "UTC"},
            source="not_configured",
            source_revision=None,
        )
    resolved_default = _periodic_report_defaults(machine_defaults)
    if resolved_default is None:
        return _normalized_goal_subscription(
            goal_id=goal_id,
            config={"enabled": False, "timezone": "UTC"},
            source="not_configured",
            source_revision=None,
        )
    periodic_defaults, source_revision = resolved_default
    return _normalized_goal_subscription(
        goal_id=goal_id,
        config=periodic_defaults,
        source="machine_default",
        source_revision=source_revision,
    )


def build_goal_periodic_report_delivery_identity(
    *,
    goal_id: str,
    period_start_at: str,
    period_end_at: str,
    route_id: str,
) -> dict[str, Any]:
    """Build the executor-independent identity for one Goal report delivery."""

    normalized_goal_id = _text(goal_id, "goal_id")
    normalized_route_id = _text(route_id, "route_id")
    try:
        start = datetime.fromisoformat(period_start_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(period_end_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("report period timestamps must be ISO-8601") from exc
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("report period timestamps must include a timezone")
    if end <= start:
        raise ValueError("report period end must be after its start")
    identity: dict[str, Any] = {
        "schema_version": DELIVERY_IDENTITY_SCHEMA,
        "goal_id": normalized_goal_id,
        "period_start_at": start.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "period_end_at": end.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "route_id": normalized_route_id,
    }
    identity["idempotency_key"] = "periodic-report-goal:" + _digest(
        identity
    ).removeprefix("sha256:")
    return identity


def select_goal_periodic_report_executor(
    *, reporting_agent_id: object, eligible_agent_ids: list[object]
) -> dict[str, Any]:
    """Prefer the selected candidate's reporter while keeping Goal-owned failover."""

    reporter = _agent_id(reporting_agent_id, "reporting_agent_id")
    eligible = sorted(
        {
            _agent_id(agent_id, f"eligible_agent_ids[{index}]")
            for index, agent_id in enumerate(eligible_agent_ids)
        }
    )
    if reporter in eligible:
        selected = reporter
        reason = "reporting_agent_preferred"
    elif eligible:
        selected = eligible[0]
        reason = "reporting_agent_unavailable_failover"
    else:
        selected = None
        reason = "no_eligible_executor"
    return {
        "reporting_agent_id": reporter,
        "selected_agent_id": selected,
        "selection_reason": reason,
        "eligible_agent_ids": eligible,
    }


def build_goal_periodic_report_delivery_plan(
    request: Mapping[str, Any],
    *,
    machine_defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Arbitrate one effect-free Goal delivery plan from a reporting Agent event."""

    payload = _mapping(request, "request")
    _reject_unknown(
        payload,
        allowed={
            "schema_version",
            "goal",
            "period_window",
            "reporting_agent_id",
            "eligible_agent_ids",
        },
        label="request",
    )
    if payload.get("schema_version") != DELIVERY_PLAN_REQUEST_SCHEMA:
        raise ValueError(f"request must use {DELIVERY_PLAN_REQUEST_SCHEMA}")
    goal = _mapping(payload.get("goal"), "request.goal")
    period = _mapping(payload.get("period_window"), "request.period_window")
    eligible_raw = payload.get("eligible_agent_ids")
    if not isinstance(eligible_raw, list):
        raise TypeError("request.eligible_agent_ids must be a list")
    subscription = resolve_goal_periodic_report_subscription(
        goal,
        machine_defaults,
    )
    if subscription["enabled"] is not True:
        return {
            "ok": True,
            "schema_version": DELIVERY_PLAN_SCHEMA,
            "status": "not_subscribed",
            "subscription": subscription,
            "delivery_identity": None,
            "executor": None,
        }
    route_ref = _text(subscription.get("route_ref"), "subscription.route_ref")
    identity = build_goal_periodic_report_delivery_identity(
        goal_id=str(subscription["goal_id"]),
        period_start_at=_text(period.get("start_at"), "period_window.start_at"),
        period_end_at=_text(period.get("end_at"), "period_window.end_at"),
        route_id=route_ref,
    )
    executor = select_goal_periodic_report_executor(
        reporting_agent_id=payload.get("reporting_agent_id"),
        eligible_agent_ids=eligible_raw,
    )
    return {
        "ok": True,
        "schema_version": DELIVERY_PLAN_SCHEMA,
        "status": "ready" if executor["selected_agent_id"] else "executor_unavailable",
        "subscription": subscription,
        "delivery_identity": identity,
        "executor": executor,
    }


__all__ = [
    "DELIVERY_IDENTITY_SCHEMA",
    "DELIVERY_PLAN_REQUEST_SCHEMA",
    "DELIVERY_PLAN_SCHEMA",
    "GOAL_SUBSCRIPTION_SCHEMA",
    "MACHINE_DEFAULTS_SCHEMA",
    "PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA",
    "build_goal_periodic_report_delivery_identity",
    "build_goal_periodic_report_delivery_plan",
    "loopx_machine_defaults_revision",
    "normalize_loopx_machine_defaults",
    "normalize_periodic_report_machine_defaults",
    "periodic_report_machine_configuration_namespace",
    "resolve_goal_periodic_report_subscription",
    "select_goal_periodic_report_executor",
]

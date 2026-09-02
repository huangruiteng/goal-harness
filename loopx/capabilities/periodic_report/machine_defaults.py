from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
BACKFILL_PLAN_SCHEMA = "periodic_report_machine_default_backfill_plan_v0"
DELIVERY_IDENTITY_SCHEMA = "periodic_report_goal_delivery_identity_v0"
DELIVERY_PLAN_REQUEST_SCHEMA = "periodic_report_goal_delivery_plan_request_v0"
DELIVERY_PLAN_SCHEMA = "periodic_report_goal_delivery_plan_v0"

_INHERITANCE_MODE = "materialize_on_goal_connect"
_TERMINAL_GOAL_STATUSES = {
    "archived",
    "canceled",
    "cancelled",
    "completed",
    "disconnected",
    "retired",
    "stopped",
}


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
        raise ValueError(
            "periodic_report.inheritance must be materialize_on_goal_connect"
        )
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


def _periodic_report_defaults(machine_defaults: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_loopx_machine_defaults(machine_defaults)
    return dict(normalized["namespaces"]["periodic_report"])


def _goal_periodic_report(goal: Mapping[str, Any]) -> dict[str, Any] | None:
    control_plane = goal.get("control_plane")
    if not isinstance(control_plane, Mapping):
        return None
    periodic = control_plane.get("periodic_report")
    return dict(periodic) if isinstance(periodic, Mapping) else None


def _normalized_goal_subscription(
    *, goal_id: str, config: Mapping[str, Any], source: str
) -> dict[str, Any]:
    enabled = config.get("enabled") is True
    subscription: dict[str, Any] = {
        "schema_version": GOAL_SUBSCRIPTION_SCHEMA,
        "goal_id": goal_id,
        "enabled": enabled,
        "source": source,
        "profile_preset": str(config.get("profile_preset") or "").strip() or None,
        "route_ref": str(config.get("route_ref") or "").strip() or None,
        "timezone": str(config.get("timezone") or "UTC").strip(),
    }
    subscription["effective_revision"] = _digest(subscription)
    return subscription


def resolve_goal_periodic_report_subscription(
    goal: Mapping[str, Any], machine_defaults: Mapping[str, Any]
) -> dict[str, Any]:
    """Resolve ownership without making the executing Agent part of identity."""

    goal_id = _text(goal.get("id"), "goal.id")
    periodic_defaults = _periodic_report_defaults(machine_defaults)
    existing = _goal_periodic_report(goal)
    if existing is not None:
        effective = {
            **periodic_defaults,
            **existing,
        }
        effective.pop("inheritance", None)
        source = (
            "machine_default"
            if existing.get("source") == "machine_default"
            else "goal_override"
        )
        return _normalized_goal_subscription(
            goal_id=goal_id,
            config=effective,
            source=source,
        )
    return _normalized_goal_subscription(
        goal_id=goal_id,
        config=periodic_defaults,
        source="machine_default_preview",
    )


def _materialized_periodic_config(
    machine_defaults: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = normalize_loopx_machine_defaults(machine_defaults)
    periodic = dict(normalized["namespaces"]["periodic_report"])
    periodic.pop("schema_version", None)
    periodic.pop("inheritance", None)
    periodic["source"] = "machine_default"
    periodic["source_revision"] = machine_configuration_revision(normalized)
    return periodic


def _state_path(goal: Mapping[str, Any]) -> Path | None:
    state_file = str(goal.get("state_file") or "").strip()
    repo = str(goal.get("repo") or "").strip()
    if not state_file or not repo:
        return None
    path = Path(state_file).expanduser()
    return path if path.is_absolute() else Path(repo).expanduser() / path


def plan_periodic_report_machine_default_backfill(
    registry: Mapping[str, Any],
    machine_defaults: Mapping[str, Any],
    *,
    state_file_exists: Callable[[Path], bool] = Path.is_file,
) -> dict[str, Any]:
    """Build a path-free per-Goal migration ledger before any registry write."""

    normalized_defaults = normalize_loopx_machine_defaults(machine_defaults)
    intended = _materialized_periodic_config(normalized_defaults)
    rows: list[dict[str, Any]] = []
    goals = registry.get("goals")
    for raw_goal in goals if isinstance(goals, list) else []:
        if not isinstance(raw_goal, Mapping):
            continue
        goal_id = str(raw_goal.get("id") or "").strip()
        if not goal_id:
            continue
        existing = _goal_periodic_report(raw_goal)
        status = str(raw_goal.get("status") or "active").strip().lower()
        state_path = _state_path(raw_goal)
        if status in _TERMINAL_GOAL_STATUSES:
            action, reason = "excluded", "goal_not_active"
        elif state_path is None or not state_file_exists(state_path):
            action, reason = "excluded", "authoritative_state_unavailable"
        elif existing is not None and existing.get("source") != "machine_default":
            action, reason = "preserve", "goal_override"
        elif existing == intended:
            action, reason = "unchanged", "already_materialized"
        elif existing is None:
            action, reason = "materialize", "machine_default_missing"
        else:
            action, reason = "update", "inherited_default_revision_changed"
        rows.append(
            {
                "goal_id": goal_id,
                "action": action,
                "reason": reason,
            }
        )
    counts = {
        action: sum(row["action"] == action for row in rows)
        for action in ("materialize", "update", "unchanged", "preserve", "excluded")
    }
    plan: dict[str, Any] = {
        "schema_version": BACKFILL_PLAN_SCHEMA,
        "machine_defaults_revision": machine_configuration_revision(
            normalized_defaults
        ),
        "rows": rows,
        "counts": counts,
        "writes_required": counts["materialize"] + counts["update"],
    }
    plan["plan_revision"] = _digest(plan)
    return plan


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
    *, reporting_agent_id: str, eligible_agent_ids: list[str]
) -> dict[str, Any]:
    """Prefer the selected candidate's reporter while keeping Goal-owned failover."""

    reporter = _text(reporting_agent_id, "reporting_agent_id")
    eligible = sorted(
        {
            str(agent_id).strip()
            for agent_id in eligible_agent_ids
            if str(agent_id).strip()
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
) -> dict[str, Any]:
    """Arbitrate one effect-free Goal delivery plan from a reporting Agent event."""

    payload = _mapping(request, "request")
    _reject_unknown(
        payload,
        allowed={
            "schema_version",
            "goal",
            "machine_defaults",
            "period_window",
            "reporting_agent_id",
            "eligible_agent_ids",
        },
        label="request",
    )
    if payload.get("schema_version") != DELIVERY_PLAN_REQUEST_SCHEMA:
        raise ValueError(f"request must use {DELIVERY_PLAN_REQUEST_SCHEMA}")
    goal = _mapping(payload.get("goal"), "request.goal")
    machine_defaults = _mapping(
        payload.get("machine_defaults"), "request.machine_defaults"
    )
    period = _mapping(payload.get("period_window"), "request.period_window")
    eligible_raw = payload.get("eligible_agent_ids")
    if not isinstance(eligible_raw, list):
        raise TypeError("request.eligible_agent_ids must be a list")
    subscription = resolve_goal_periodic_report_subscription(goal, machine_defaults)
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
        reporting_agent_id=_text(
            payload.get("reporting_agent_id"), "request.reporting_agent_id"
        ),
        eligible_agent_ids=[str(agent_id) for agent_id in eligible_raw],
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
    "BACKFILL_PLAN_SCHEMA",
    "DELIVERY_IDENTITY_SCHEMA",
    "DELIVERY_PLAN_REQUEST_SCHEMA",
    "DELIVERY_PLAN_SCHEMA",
    "GOAL_SUBSCRIPTION_SCHEMA",
    "MACHINE_DEFAULTS_SCHEMA",
    "PERIODIC_REPORT_MACHINE_DEFAULTS_SCHEMA",
    "build_goal_periodic_report_delivery_identity",
    "build_goal_periodic_report_delivery_plan",
    "normalize_loopx_machine_defaults",
    "normalize_periodic_report_machine_defaults",
    "periodic_report_machine_configuration_namespace",
    "plan_periodic_report_machine_default_backfill",
    "resolve_goal_periodic_report_subscription",
    "select_goal_periodic_report_executor",
]

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ...file_lock import exclusive_file_lock
from ...registry import atomic_write_json
from .concurrency_envelope import (
    BENCHMARK_CONCURRENCY_ENVELOPE_SCHEMA_VERSION,
    _bounded_int,
    _now_iso,
    _reject_unknown_fields,
    _timestamp,
    build_benchmark_concurrency_status,
    normalize_benchmark_concurrency_envelope,
    normalize_benchmark_resource_headroom_receipt,
    read_benchmark_concurrency_envelope,
)

BENCHMARK_ADAPTIVE_CONCURRENCY_POLICY_SCHEMA_VERSION = (
    "benchmark_adaptive_concurrency_policy_v0"
)
BENCHMARK_CONCURRENCY_FEEDBACK_SCHEMA_VERSION = "benchmark_concurrency_feedback_v0"
BENCHMARK_ADAPTIVE_CONCURRENCY_DECISION_SCHEMA_VERSION = (
    "benchmark_adaptive_concurrency_decision_v0"
)

_MAX_FEEDBACK_VALIDITY = timedelta(minutes=15)
_POLICY_FIELDS = {
    "schema_version",
    "minimum_target_active_cases",
    "increase_step",
    "decrease_step",
    "saturated_healthy_windows_required",
}
_FEEDBACK_FIELDS = {
    "schema_version",
    "observed_envelope_updated_at",
    "window_started_at",
    "observed_at",
    "expires_at",
    "saturated_healthy_window_streak",
    "launch_attempts",
    "launch_failures",
    "provider_capacity_rejections",
    "runner_invalid_transitions",
}


def build_benchmark_adaptive_concurrency_policy(
    *,
    minimum_target_active_cases: int = 1,
    increase_step: int = 1,
    decrease_step: int = 1,
    saturated_healthy_windows_required: int = 2,
) -> dict[str, Any]:
    return normalize_benchmark_adaptive_concurrency_policy(
        {
            "schema_version": BENCHMARK_ADAPTIVE_CONCURRENCY_POLICY_SCHEMA_VERSION,
            "minimum_target_active_cases": minimum_target_active_cases,
            "increase_step": increase_step,
            "decrease_step": decrease_step,
            "saturated_healthy_windows_required": saturated_healthy_windows_required,
        }
    )


def normalize_benchmark_adaptive_concurrency_policy(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("benchmark adaptive concurrency policy must be an object")
    _reject_unknown_fields(value, allowed=_POLICY_FIELDS, field="policy")
    if (
        value.get("schema_version")
        != BENCHMARK_ADAPTIVE_CONCURRENCY_POLICY_SCHEMA_VERSION
    ):
        raise ValueError("benchmark adaptive concurrency policy schema mismatch")
    return {
        "schema_version": BENCHMARK_ADAPTIVE_CONCURRENCY_POLICY_SCHEMA_VERSION,
        "minimum_target_active_cases": _bounded_int(
            value.get("minimum_target_active_cases"),
            field="minimum_target_active_cases",
            minimum=1,
        ),
        "increase_step": _bounded_int(
            value.get("increase_step"), field="increase_step", minimum=1
        ),
        "decrease_step": _bounded_int(
            value.get("decrease_step"), field="decrease_step", minimum=1
        ),
        "saturated_healthy_windows_required": _bounded_int(
            value.get("saturated_healthy_windows_required"),
            field="saturated_healthy_windows_required",
            minimum=1,
        ),
    }


def normalize_benchmark_concurrency_feedback(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("benchmark concurrency feedback must be an object")
    _reject_unknown_fields(value, allowed=_FEEDBACK_FIELDS, field="feedback")
    if value.get("schema_version") != BENCHMARK_CONCURRENCY_FEEDBACK_SCHEMA_VERSION:
        raise ValueError("benchmark concurrency feedback schema mismatch")
    window_started_at = _timestamp(
        value.get("window_started_at"), field="window_started_at"
    )
    observed_at = _timestamp(value.get("observed_at"), field="observed_at")
    expires_at = _timestamp(value.get("expires_at"), field="expires_at")
    window_start = datetime.fromisoformat(window_started_at)
    observed = datetime.fromisoformat(observed_at)
    expires = datetime.fromisoformat(expires_at)
    if window_start > observed:
        raise ValueError("window_started_at cannot be later than observed_at")
    if expires <= observed:
        raise ValueError("expires_at must be later than observed_at")
    if expires - observed > _MAX_FEEDBACK_VALIDITY:
        raise ValueError(
            "benchmark concurrency feedback validity must not exceed 15 minutes"
        )
    launch_attempts = _bounded_int(
        value.get("launch_attempts"), field="launch_attempts"
    )
    launch_failures = _bounded_int(
        value.get("launch_failures"), field="launch_failures"
    )
    capacity_rejections = _bounded_int(
        value.get("provider_capacity_rejections"),
        field="provider_capacity_rejections",
    )
    if launch_failures > launch_attempts:
        raise ValueError("launch_failures cannot exceed launch_attempts")
    if capacity_rejections > launch_attempts:
        raise ValueError("provider_capacity_rejections cannot exceed launch_attempts")
    return {
        "schema_version": BENCHMARK_CONCURRENCY_FEEDBACK_SCHEMA_VERSION,
        "observed_envelope_updated_at": _timestamp(
            value.get("observed_envelope_updated_at"),
            field="observed_envelope_updated_at",
        ),
        "window_started_at": window_started_at,
        "observed_at": observed_at,
        "expires_at": expires_at,
        "saturated_healthy_window_streak": _bounded_int(
            value.get("saturated_healthy_window_streak"),
            field="saturated_healthy_window_streak",
        ),
        "launch_attempts": launch_attempts,
        "launch_failures": launch_failures,
        "provider_capacity_rejections": capacity_rejections,
        "runner_invalid_transitions": _bounded_int(
            value.get("runner_invalid_transitions"),
            field="runner_invalid_transitions",
        ),
    }


def _headroom_state(
    receipt: Mapping[str, Any] | None, *, decision_at: str
) -> tuple[str, list[str]]:
    if receipt is None:
        return "unresolved", ["resource_headroom_receipt_required"]
    normalized = normalize_benchmark_resource_headroom_receipt(receipt)
    decision_time = datetime.fromisoformat(decision_at)
    observed_time = datetime.fromisoformat(normalized["observed_at"])
    expires_time = datetime.fromisoformat(normalized["expires_at"])
    if observed_time > decision_time:
        return "unresolved", ["resource_headroom_receipt_from_future"]
    if decision_time >= expires_time:
        return "unresolved", ["resource_headroom_receipt_expired"]
    insufficient = [
        f"{item['kind']}_insufficient"
        for item in normalized["checks"]
        if item["state"] == "insufficient"
    ]
    if insufficient:
        return "insufficient", insufficient
    unresolved = [
        f"{item['kind']}_unresolved"
        for item in normalized["checks"]
        if item["state"] == "unresolved"
    ]
    if unresolved:
        return "unresolved", unresolved
    return "sufficient", []


def _pressure_reasons(
    feedback: Mapping[str, Any], *, headroom_state: str, headroom_reasons: list[str]
) -> list[str]:
    reasons = [
        field
        for field in (
            "launch_failures",
            "provider_capacity_rejections",
            "runner_invalid_transitions",
        )
        if feedback[field] > 0
    ]
    if headroom_state == "insufficient":
        reasons.extend(headroom_reasons)
    return sorted(set(reasons))


def _adaptive_action(
    *,
    current_target: int,
    max_active_cases: int,
    active_count: int,
    policy: Mapping[str, Any],
    feedback: Mapping[str, Any],
    feedback_reasons: list[str],
    headroom_state: str,
    headroom_reasons: list[str],
    pressure_reasons: list[str],
) -> tuple[str, int, list[str]]:
    if feedback_reasons:
        return "hold", current_target, feedback_reasons
    if pressure_reasons:
        next_target = max(
            policy["minimum_target_active_cases"],
            current_target - policy["decrease_step"],
        )
        return "decrease", next_target, pressure_reasons
    if headroom_state != "sufficient":
        return "hold", current_target, headroom_reasons
    if active_count < current_target:
        return "hold", current_target, ["target_not_saturated"]
    if active_count > current_target:
        return "hold", current_target, ["active_count_above_target"]
    if current_target >= max_active_cases:
        return "hold", current_target, ["operator_hard_ceiling_reached"]
    if (
        feedback["saturated_healthy_window_streak"]
        < policy["saturated_healthy_windows_required"]
    ):
        return "hold", current_target, ["saturated_healthy_window_streak_incomplete"]
    next_target = min(max_active_cases, current_target + policy["increase_step"])
    return "increase", next_target, ["saturated_healthy_windows_with_headroom"]


def build_benchmark_adaptive_concurrency_decision(
    envelope: Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any],
    feedback: Mapping[str, Any],
    resource_headroom_receipt: Mapping[str, Any] | None,
    decided_at: str | None = None,
) -> dict[str, Any]:
    compact_policy = normalize_benchmark_adaptive_concurrency_policy(policy)
    compact_feedback = normalize_benchmark_concurrency_feedback(feedback)
    timestamp = _timestamp(decided_at or _now_iso(), field="decided_at")
    if envelope is None:
        return {
            "ok": False,
            "schema_version": BENCHMARK_ADAPTIVE_CONCURRENCY_DECISION_SCHEMA_VERSION,
            "action": "hold",
            "reason_codes": ["concurrency_envelope_not_configured"],
            "write_performed": False,
        }
    normalized = normalize_benchmark_concurrency_envelope(envelope)
    config = normalized["config"]
    current_target = config["target_active_cases"]
    if compact_policy["minimum_target_active_cases"] > config["max_active_cases"]:
        raise ValueError("minimum_target_active_cases cannot exceed max_active_cases")

    decision_time = datetime.fromisoformat(timestamp)
    feedback_observed = datetime.fromisoformat(compact_feedback["observed_at"])
    feedback_expires = datetime.fromisoformat(compact_feedback["expires_at"])
    feedback_reasons: list[str] = []
    if (
        compact_feedback["observed_envelope_updated_at"]
        != normalized["updated_at"]
    ):
        feedback_reasons.append("concurrency_feedback_envelope_revision_mismatch")
    if feedback_observed > decision_time:
        feedback_reasons.append("concurrency_feedback_from_future")
    if decision_time >= feedback_expires:
        feedback_reasons.append("concurrency_feedback_expired")
    headroom_state, headroom_reasons = _headroom_state(
        resource_headroom_receipt, decision_at=timestamp
    )
    status = build_benchmark_concurrency_status(normalized)
    active_count = status["active_counts"]["total"]

    action, next_target, reasons = _adaptive_action(
        current_target=current_target,
        max_active_cases=config["max_active_cases"],
        active_count=active_count,
        policy=compact_policy,
        feedback=compact_feedback,
        feedback_reasons=feedback_reasons,
        headroom_state=headroom_state,
        headroom_reasons=headroom_reasons,
        pressure_reasons=_pressure_reasons(
            compact_feedback,
            headroom_state=headroom_state,
            headroom_reasons=headroom_reasons,
        ),
    )

    return {
        "ok": True,
        "schema_version": BENCHMARK_ADAPTIVE_CONCURRENCY_DECISION_SCHEMA_VERSION,
        "decided_at": timestamp,
        "action": action,
        "reason_codes": reasons,
        "current_target_active_cases": current_target,
        "next_target_active_cases": next_target,
        "active_cases": active_count,
        "max_active_cases": config["max_active_cases"],
        "operator_hard_ceiling_changed": False,
        "active_runs_terminated": False,
        "policy": compact_policy,
        "feedback": compact_feedback,
        "resource_headroom": {
            "state": headroom_state,
            "reason_codes": headroom_reasons,
            "receipt_persisted": False,
        },
        "write_performed": False,
    }


def tune_benchmark_concurrency_target(
    path: str | Path,
    *,
    policy: Mapping[str, Any],
    feedback: Mapping[str, Any],
    resource_headroom_receipt: Mapping[str, Any] | None,
    execute: bool = False,
    agent_id: str | None = None,
    decided_at: str | None = None,
) -> dict[str, Any]:
    target = Path(path).expanduser()
    timestamp = _timestamp(decided_at or _now_iso(), field="decided_at")

    def build(
        current: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        decision = build_benchmark_adaptive_concurrency_decision(
            current,
            policy=policy,
            feedback=feedback,
            resource_headroom_receipt=resource_headroom_receipt,
            decided_at=timestamp,
        )
        decision["dry_run"] = not execute
        if not decision["ok"] or current is None:
            return decision, None
        normalized = normalize_benchmark_concurrency_envelope(current)
        if (
            decision["next_target_active_cases"]
            == decision["current_target_active_cases"]
        ):
            decision["status"] = build_benchmark_concurrency_status(normalized)
            return decision, None
        next_envelope = normalize_benchmark_concurrency_envelope(
            {
                "schema_version": BENCHMARK_CONCURRENCY_ENVELOPE_SCHEMA_VERSION,
                "configured_at": normalized["configured_at"],
                "updated_at": timestamp,
                "config": {
                    **normalized["config"],
                    "target_active_cases": decision["next_target_active_cases"],
                },
                "active_runs": normalized["active_runs"],
            }
        )
        decision["status"] = build_benchmark_concurrency_status(next_envelope)
        return decision, next_envelope

    if not execute:
        result, _ = build(read_benchmark_concurrency_envelope(target))
        return result
    with exclusive_file_lock(
        target, agent_id=agent_id, operation="benchmark_concurrency_tune"
    ):
        result, next_envelope = build(read_benchmark_concurrency_envelope(target))
        if next_envelope is not None:
            atomic_write_json(target, next_envelope)
            result["write_performed"] = True
        return result

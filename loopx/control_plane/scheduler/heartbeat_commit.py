from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result


SCHEDULER_HEARTBEAT_COMMIT_REQUEST_SCHEMA = (
    "loopx_scheduler_heartbeat_commit_request_v0"
)
SCHEDULER_HEARTBEAT_COMMIT_RESULT_SCHEMA = "loopx_scheduler_heartbeat_commit_result_v0"


def _required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"scheduler heartbeat {label} must be a boolean")
    return value


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    return _required_bool(value, label)


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"scheduler heartbeat {label} must be a non-empty string")
    return value.strip()


def _required_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"scheduler heartbeat {label} must be an integer")
    return value


def _first_present(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


def _stable_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_stable_value(item) for item in value]
    if not isinstance(value, Mapping):
        return value
    return {key: _stable_value(child) for key, child in sorted(value.items())}


def scheduler_state_digest(state: Mapping[str, Any] | None) -> str | None:
    if state is None:
        return None
    # The TS transaction owns this receipt metadata. It is deliberately
    # excluded from the domain-state CAS digest so a replay does not make the
    # next Python facade call appear stale merely because the receipt changed.
    payload = {key: value for key, value in state.items() if key != "heartbeat_commit"}
    encoded = json.dumps(
        _stable_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def scheduler_heartbeat_operation_id(
    *,
    goal_id: str,
    agent_id: str,
    surface: str,
    state_key: str,
    outcome: str,
    state: Mapping[str, Any] | None = None,
    facts: Mapping[str, Any] | None = None,
    ack: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "goal_id": goal_id,
        "agent_id": agent_id,
        "surface": surface,
        "state_key": state_key,
        "outcome": outcome,
        "state": {
            key: value
            for key, value in (state or {}).items()
            if key != "heartbeat_commit"
        },
        "facts": dict(facts or {}),
        "ack": ack,
        "failure": failure,
    }
    encoded = json.dumps(
        _stable_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"scheduler-heartbeat:{hashlib.sha256(encoded).hexdigest()}"


def commit_scheduler_heartbeat(
    *,
    runtime_root: Path,
    goal_id: str,
    agent_id: str,
    surface: str,
    state_key: str,
    outcome: str,
    state: Mapping[str, Any] | None = None,
    facts: Mapping[str, Any] | None = None,
    ack: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
    operation_id: str | None = None,
    expected_state_digest: str | None = None,
    execute: bool = True,
) -> Mapping[str, Any]:
    if outcome not in {"ack", "failure", "host_failure"}:
        raise ValueError("scheduler heartbeat outcome must be 'ack' or 'failure'")
    safe_operation_id = operation_id or scheduler_heartbeat_operation_id(
        goal_id=goal_id,
        agent_id=agent_id,
        surface=surface,
        state_key=state_key,
        outcome=outcome,
        state=state,
        facts=facts,
        ack=ack,
        failure=failure,
    )
    operation = "ack" if outcome == "ack" else "host_failure"
    safe_state = dict(state or {})
    safe_facts = dict(facts or {})
    ack_payload = dict(ack) if ack is not None else None
    failure_payload = dict(failure) if failure is not None else None
    progression_minutes = safe_facts.get(
        "progression_minutes", safe_state.get("progression_minutes")
    )
    if not isinstance(progression_minutes, list) or not progression_minutes:
        raise ValueError("scheduler heartbeat state must include progression_minutes")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in progression_minutes
    ):
        raise ValueError(
            "scheduler heartbeat progression_minutes must be positive integers"
        )
    progression_index = safe_facts.get(
        "progression_index", safe_state.get("progression_index")
    )
    progression_index = _required_int(progression_index, "progression_index")
    if progression_index < 0 or progression_index >= len(progression_minutes):
        raise ValueError("scheduler heartbeat progression_index is out of range")
    reset_token = _required_text(
        safe_facts.get("reset_token", safe_state.get("reset_token")),
        "reset_token",
    )
    identity_signature = _required_text(
        safe_facts.get("identity_signature", safe_state.get("identity_signature")),
        "identity_signature",
    )
    expected_value = (ack_payload or {}).get("expected_rrule")
    if expected_value is None:
        expected_value = safe_facts.get("expected_rrule")
    if expected_value is None:
        expected_value = (failure_payload or {}).get("target_rrule")
    expected_rrule = (
        ""
        if expected_value in (None, "")
        else _required_text(expected_value, "expected_rrule")
    )
    applied_value = (ack_payload or {}).get("applied_rrule")
    if applied_value is None:
        applied_value = safe_facts.get("applied_rrule")
    applied_rrule = (
        ""
        if applied_value in (None, "")
        else _required_text(applied_value, "applied_rrule")
    )
    observed_value = (failure_payload or {}).get("observed_host_rrule")
    if observed_value is None:
        observed_value = safe_facts.get("observed_host_rrule")
    observed_host_rrule = (
        ""
        if observed_value in (None, "")
        else _required_text(observed_value, "observed_host_rrule")
    )
    prior_failures = safe_facts.get("prior_host_update_failures")
    if prior_failures is None:
        prior_failures = safe_state.get("host_update_failures")
    if prior_failures is None and safe_state.get("host_update_failure") is not None:
        prior_failures = [safe_state["host_update_failure"]]
    if prior_failures is not None and (
        not isinstance(prior_failures, list)
        or any(not isinstance(item, Mapping) for item in prior_failures)
    ):
        raise ValueError("scheduler heartbeat prior failure cache must be a list")
    # A compact-facts caller must prove whether a host mutation was needed.
    # Keep the legacy full-state path compatible with older callers while
    # refusing to manufacture authority for the new transaction boundary.
    if "apply_needed" in safe_facts:
        apply_needed = _optional_bool(safe_facts["apply_needed"], "apply_needed")
    elif failure_payload is not None and "apply_needed" in failure_payload:
        apply_needed = _optional_bool(failure_payload["apply_needed"], "apply_needed")
    elif operation == "host_failure" and safe_state:
        apply_needed = True
    else:
        apply_needed = None
    failure_kind_value = _first_present(
        safe_facts.get("failure_kind"),
        (failure_payload or {}).get("failure_kind"),
    )
    failure_kind = (
        None
        if failure_kind_value in (None, "")
        else _required_text(failure_kind_value, "failure_kind")
    )

    params: dict[str, Any] = {
        "schema_version": SCHEDULER_HEARTBEAT_COMMIT_REQUEST_SCHEMA,
        "operation": operation,
        "effect_id": safe_operation_id,
        "runtime_root": str(runtime_root),
        "goal_id": goal_id,
        "agent_id": agent_id,
        "surface": surface,
        "state_key": state_key,
        "expected_state_digest": expected_state_digest,
        "reset_token": reset_token,
        "identity_signature": identity_signature,
        "progression_index": progression_index,
        "progression_minutes": progression_minutes,
        # An exact ACK event omits expected_rrule; null lets the TS decoder
        # derive it from progression_index/progression_minutes.
        "expected_rrule": expected_rrule or None,
        "applied_rrule": applied_rrule,
        "cadence_class": _required_text(
            _first_present(
                (ack_payload or {}).get("cadence_class"),
                (failure_payload or {}).get("cadence_class"),
                safe_facts.get("cadence_class"),
                default="default",
            ),
            "cadence_class",
        ),
        "stale_tolerance_minutes": _required_int(
            _first_present(
                (ack_payload or {}).get("stale_tolerance_minutes"),
                (failure_payload or {}).get("stale_tolerance_minutes"),
                safe_facts.get("stale_tolerance_minutes"),
                default=2,
            ),
            "stale_tolerance_minutes",
        ),
        "generated_at": _required_text(
            safe_facts.get("generated_at", safe_state.get("updated_at")),
            "generated_at",
        ),
        "execute": _required_bool(safe_facts.get("execute", execute), "execute"),
        "ack_needed": _optional_bool(
            safe_facts.get("ack_needed", (ack_payload or {}).get("ack_needed")),
            "ack_needed",
        ),
        "apply_needed": apply_needed,
        "source": _required_text(
            safe_facts.get(
                "source",
                (failure_payload or {}).get("source")
                or (ack_payload or {}).get("source")
                or (
                    "quota_scheduler_host_update_failure"
                    if operation == "host_failure"
                    else "quota_scheduler_ack"
                ),
            ),
            "source",
        ),
        "host_match_observed": _required_bool(
            safe_facts.get("host_match_observed", False), "host_match_observed"
        ),
        "failure_kind": failure_kind,
        "observed_host_rrule": observed_host_rrule,
        "prior_host_update_failures": prior_failures or [],
    }
    try:
        result = effect_runtime_result("scheduler.heartbeat.commit", params)
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if (
        not isinstance(result, Mapping)
        or result.get("schema_version") != SCHEDULER_HEARTBEAT_COMMIT_RESULT_SCHEMA
        or result.get("operation") != operation
        or result.get("effect_id") != safe_operation_id
    ):
        raise RuntimeError(
            "TypeScript scheduler heartbeat commit result shape mismatch"
        )
    return result

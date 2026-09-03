"""Reduce post-run treatment-control observations to a public-safe receipt."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

BENCHMARK_TREATMENT_CONTINUATION_OBSERVATION_SCHEMA_VERSION = (
    "benchmark_treatment_continuation_observation_v0"
)
BENCHMARK_TREATMENT_CONTINUATION_RECEIPT_SCHEMA_VERSION = (
    "benchmark_treatment_continuation_receipt_v0"
)

_OBSERVATION_FIELDS = {
    "schema_version",
    "treatment_applicable",
    "startup_state",
    "observation_complete",
    "post_start_control_events",
    "terminal_control_state",
    "precommit_validation_state",
}
_CONTROL_EVENT_FIELDS = {
    "todo_transition_count",
    "technical_replan_count",
    "control_closeout_count",
}
_SUSTAINING_CONTROL_EVENT_FIELDS = {
    "todo_transition_count",
    "technical_replan_count",
}
_STARTUP_STATES = {"qualified", "not_qualified", "unknown", "not_applicable"}
_TERMINAL_CONTROL_STATES = {
    "settled",
    "unsettled",
    "unknown",
    "not_applicable",
}
_VALIDATION_STATES = {"observed", "not_observed", "unknown", "not_applicable"}


def _strict_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    return value


def _enum(value: object, *, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{field} is unsupported")
    return value


def _count(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    if value > 1_000_000:
        raise ValueError(f"{field} exceeds the supported bound")
    return value


def _reason_codes(
    *,
    classification: str,
    startup_state: str,
    observation_complete: bool,
    terminal_control_state: str,
    precommit_validation_state: str,
    terminal_only_control_observed: bool,
) -> list[str]:
    reasons = [f"control_persistence_{classification}"]
    if startup_state != "qualified" and classification != "not_applicable":
        reasons.append(f"startup_{startup_state}")
    if not observation_complete and classification == "unknown":
        reasons.append("post_run_observation_incomplete")
    if terminal_only_control_observed:
        reasons.append("terminal_only_control_does_not_establish_persistence")
    reasons.append(f"terminal_control_{terminal_control_state}")
    reasons.append(f"precommit_validation_{precommit_validation_state}")
    return reasons


def build_benchmark_treatment_continuation_receipt(
    observation: Mapping[str, Any],
) -> dict[str, object]:
    """Build a score-neutral receipt from compact post-run mechanism facts.

    ``sustained`` means at least one task-facing Todo transition or technical
    replan changed the solving course after qualified startup and before the
    result was fixed. Terminal-only settlement and closeout remain visible but
    cannot establish persistence by themselves.
    """

    if not isinstance(observation, Mapping):
        raise TypeError("observation must be an object")
    if set(observation) != _OBSERVATION_FIELDS:
        raise ValueError("observation fields do not match the public contract")
    if (
        observation.get("schema_version")
        != BENCHMARK_TREATMENT_CONTINUATION_OBSERVATION_SCHEMA_VERSION
    ):
        raise ValueError("observation schema_version is unsupported")

    treatment_applicable = _strict_bool(
        observation.get("treatment_applicable"),
        field="treatment_applicable",
    )
    startup_state = _enum(
        observation.get("startup_state"),
        field="startup_state",
        allowed=_STARTUP_STATES,
    )
    observation_complete = _strict_bool(
        observation.get("observation_complete"),
        field="observation_complete",
    )
    terminal_control_state = _enum(
        observation.get("terminal_control_state"),
        field="terminal_control_state",
        allowed=_TERMINAL_CONTROL_STATES,
    )
    precommit_validation_state = _enum(
        observation.get("precommit_validation_state"),
        field="precommit_validation_state",
        allowed=_VALIDATION_STATES,
    )

    events = observation.get("post_start_control_events")
    if not isinstance(events, Mapping) or set(events) != _CONTROL_EVENT_FIELDS:
        raise ValueError(
            "post_start_control_events fields do not match the public contract"
        )
    event_counts = {
        field: _count(events.get(field), field=f"post_start_control_events.{field}")
        for field in sorted(_CONTROL_EVENT_FIELDS)
    }
    event_count = sum(event_counts.values())
    sustaining_event_count = sum(
        event_counts[field] for field in _SUSTAINING_CONTROL_EVENT_FIELDS
    )
    terminal_only_event_count = event_counts["control_closeout_count"]

    if not treatment_applicable:
        if startup_state != "not_applicable":
            raise ValueError("non-treatment observation must use not_applicable startup")
        if terminal_control_state != "not_applicable":
            raise ValueError(
                "non-treatment observation must use not_applicable terminal control"
            )
        if event_count:
            raise ValueError("non-treatment observation cannot contain control events")
        classification = "not_applicable"
    elif startup_state != "qualified":
        if startup_state == "not_applicable":
            raise ValueError("applicable treatment cannot use not_applicable startup")
        classification = "unknown"
    elif sustaining_event_count:
        classification = "sustained"
    elif observation_complete:
        classification = "startup_only"
    else:
        classification = "unknown"

    return {
        "schema_version": BENCHMARK_TREATMENT_CONTINUATION_RECEIPT_SCHEMA_VERSION,
        "ok": True,
        "classification": classification,
        "startup_state": startup_state,
        "observation_complete": observation_complete,
        "post_start_control_observed": event_count > 0,
        "post_start_control_event_count": event_count,
        "post_start_control_event_counts": event_counts,
        "terminal_control_state": terminal_control_state,
        "precommit_validation_state": precommit_validation_state,
        "reason_codes": _reason_codes(
            classification=classification,
            startup_state=startup_state,
            observation_complete=observation_complete,
            terminal_control_state=terminal_control_state,
            precommit_validation_state=precommit_validation_state,
            terminal_only_control_observed=terminal_only_event_count > 0,
        ),
        "score_semantics": {
            "score_countability_unchanged": True,
            "integrity_qualification_unchanged": True,
            "treatment_fidelity_unchanged": True,
            "claim_scope": "post_run_mechanism_analysis_only",
        },
        "public_boundary": {
            "raw_content_recorded": False,
            "path_recorded": False,
            "run_identity_recorded": False,
        },
        "write_performed": False,
    }

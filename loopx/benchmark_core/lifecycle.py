from __future__ import annotations

from enum import Enum
from typing import Any


BENCHMARK_LIFECYCLE_STATE_SCHEMA_VERSION = "benchmark_lifecycle_state_v0"
BENCHMARK_CANONICAL_LIFECYCLE_SCHEMA_VERSION = "benchmark_canonical_lifecycle_v0"


class BenchmarkLifecyclePhase(str, Enum):
    NOT_STARTED = "not_started"
    PROCESS_STARTED = "process_started"
    RUNNER_ACCEPTED_ARGS = "runner_accepted_args"
    JOB_ROOT_MATERIALIZED = "job_root_materialized"
    TRIAL_STARTED = "trial_started"
    WORKER_STARTED = "worker_started"
    RESULT_WRITTEN = "result_written"
    VERIFIER_SCORED = "verifier_scored"


CANONICAL_LIFECYCLE_PHASES = tuple(phase.value for phase in BenchmarkLifecyclePhase)
CASE_ENTRY_PHASES = {
    BenchmarkLifecyclePhase.JOB_ROOT_MATERIALIZED.value,
    BenchmarkLifecyclePhase.TRIAL_STARTED.value,
    BenchmarkLifecyclePhase.WORKER_STARTED.value,
    BenchmarkLifecyclePhase.RESULT_WRITTEN.value,
    BenchmarkLifecyclePhase.VERIFIER_SCORED.value,
}


def _coerce_flags(flags: dict[str, Any]) -> dict[str, bool]:
    coerced: dict[str, bool] = {}
    previous = True
    for phase in CANONICAL_LIFECYCLE_PHASES:
        if phase == BenchmarkLifecyclePhase.NOT_STARTED.value:
            continue
        ready = bool(flags.get(phase))
        coerced[phase] = bool(previous and ready)
        previous = coerced[phase]
    return coerced


def canonical_lifecycle(**flags: Any) -> dict[str, Any]:
    """Return an adapter-neutral lifecycle projection.

    `process_started` is intentionally not enough to enter a benchmark case.
    Control-plane accounting should only treat the case as entered once the
    job root materializes or a later phase is observed.
    """

    ready = _coerce_flags(flags)
    phase = BenchmarkLifecyclePhase.NOT_STARTED.value
    for candidate in CANONICAL_LIFECYCLE_PHASES[1:]:
        if ready.get(candidate):
            phase = candidate
        else:
            break
    entered_case = phase in CASE_ENTRY_PHASES
    next_required_phase = ""
    for candidate in CANONICAL_LIFECYCLE_PHASES[1:]:
        if not ready.get(candidate):
            next_required_phase = candidate
            break
    return {
        "schema_version": BENCHMARK_CANONICAL_LIFECYCLE_SCHEMA_VERSION,
        "current_phase": phase,
        "entered_benchmark_case": entered_case,
        "case_attempt_countable": entered_case,
        "next_required_phase": next_required_phase,
        "phase_ready": ready,
    }


def compact_benchmark_canonical_lifecycle(value: Any) -> dict[str, Any]:
    """Return the public-safe subset of a canonical lifecycle projection."""

    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    if value.get("schema_version") == BENCHMARK_CANONICAL_LIFECYCLE_SCHEMA_VERSION:
        compact["schema_version"] = BENCHMARK_CANONICAL_LIFECYCLE_SCHEMA_VERSION
    for field in ("current_phase", "next_required_phase"):
        raw = value.get(field)
        if isinstance(raw, str) and raw in CANONICAL_LIFECYCLE_PHASES:
            compact[field] = raw
    for field in ("entered_benchmark_case", "case_attempt_countable"):
        if isinstance(value.get(field), bool):
            compact[field] = value[field]
    phase_ready = value.get("phase_ready")
    if isinstance(phase_ready, dict):
        compact_phase_ready: dict[str, bool] = {}
        for key, ready in phase_ready.items():
            if key in CANONICAL_LIFECYCLE_PHASES and isinstance(ready, bool):
                compact_phase_ready[key] = ready
        if compact_phase_ready:
            compact["phase_ready"] = compact_phase_ready
    return compact

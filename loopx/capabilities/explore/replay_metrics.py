"""Generic, public-safe metrics for Explore replay execution."""

from __future__ import annotations

import threading
from collections import Counter
from typing import Any, Mapping, Sequence


_COUNT_FIELDS = (
    "capture_attempt_count",
    "capture_success_count",
    "capture_failure_count",
    "capture_compensation_count",
    "capture_compensation_failure_count",
    "orphaned_adapter_binding_count",
    "orphaned_agent_state_count",
    "replacement_capture_attempt_count",
    "replacement_capture_success_count",
    "replacement_capture_failure_count",
    "replacement_projection_mismatch_count",
    "replay_point_selection_count",
    "replay_point_fidelity_fallback_count",
    "replay_point_fidelity_filtered_selection_count",
    "child_group_attempt_count",
    "child_group_success_count",
    "child_group_failure_count",
    "child_group_settled_count",
    "child_candidate_success_count",
    "child_candidate_failure_count",
    "child_parallel_group_count",
    "child_process_isolated_parallel_group_count",
    "child_parallel_downgrade_group_count",
    "child_serial_fallback_group_count",
    "child_session_fork_attempt_count",
    "child_session_fork_success_count",
    "child_session_fork_failure_count",
    "child_session_release_attempt_count",
    "child_session_release_success_count",
    "child_session_release_failure_count",
    "child_intent_assessment_count",
    "child_intent_allowed_count",
    "child_intent_denied_count",
    "child_outcome_assessment_count",
    "child_outcome_allowed_count",
    "child_outcome_denied_count",
    "replay_attempt_count",
    "replay_success_count",
    "replay_failure_count",
    "restore_attempt_count",
    "restore_success_count",
    "restore_failure_count",
    "prefix_reuse_verified_count",
    "prefix_reconstruction_count",
    "prefix_reuse_unknown_count",
    "equivalence_attempt_count",
    "equivalence_verified_count",
    "equivalence_unverified_count",
    "equivalence_failure_count",
    "suffix_attempt_count",
    "suffix_success_count",
    "suffix_failure_count",
    "suffix_finalization_attempt_count",
    "suffix_finalization_success_count",
    "suffix_finalization_failure_count",
    "replay_point_quarantine_count",
    "release_attempt_count",
    "release_success_count",
    "release_failure_count",
)
_MINUTE_FIELDS = (
    "capture_minutes",
    "restore_minutes",
    "equivalence_minutes",
    "suffix_minutes",
    "replay_wall_minutes",
    "release_minutes",
)


class ReplayMetricLedger:
    """Small thread-safe accumulator shared by ReplayPoint registries."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._minutes: Counter[str] = Counter()
        self._fidelity: Counter[str] = Counter()
        self._lock = threading.Lock()

    def increment(self, field: str, amount: int = 1) -> None:
        if field not in _COUNT_FIELDS:
            raise ValueError(f"unknown replay count metric: {field}")
        with self._lock:
            self._counts[field] += int(amount)

    def add_seconds(self, field: str, seconds: float) -> None:
        if field not in _MINUTE_FIELDS:
            raise ValueError(f"unknown replay duration metric: {field}")
        with self._lock:
            self._minutes[field] += max(0.0, float(seconds)) / 60.0

    def observe_fidelity(self, fidelity: str) -> None:
        normalized = str(fidelity or "").strip()
        if not normalized:
            raise ValueError("fidelity metric key must be non-empty")
        with self._lock:
            self._fidelity[normalized] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            payload: dict[str, Any] = {
                field: int(self._counts[field]) for field in _COUNT_FIELDS
            }
            payload.update(
                {
                    field: round(float(self._minutes[field]), 6)
                    for field in _MINUTE_FIELDS
                }
            )
            payload["restored_fidelity_counts"] = dict(sorted(self._fidelity.items()))
            return payload


def summarize_counterfactual_results(
    results: Sequence[Any],
    *,
    fresh_compute_minutes_by_candidate: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Summarize promotion quality and optional fresh-run compute avoidance."""

    decision_counts: Counter[str] = Counter()
    fidelity_counts: Counter[str] = Counter()
    failed_fix_count = 0
    guard_regression_count = 0
    missing_validation_count = 0
    avoided_prefix_events = 0
    addressed_prefix_events = 0
    verified_reused_prefix_events = 0
    replay_distance_events = 0
    restore_minutes = 0.0
    equivalence_minutes = 0.0
    suffix_minutes = 0.0
    replay_wall_minutes = 0.0
    estimated_fresh_minutes = 0.0
    estimated_avoided_minutes = 0.0
    promoted_avoided_minutes = 0.0
    fresh_samples = 0
    prefix_reuse_counts: Counter[str] = Counter()
    baselines = fresh_compute_minutes_by_candidate or {}

    for result in results:
        decision = str(result.decision.value)
        fidelity = str(result.restore.achieved_fidelity.value)
        decision_counts[decision] += 1
        fidelity_counts[fidelity] += 1
        failed_fix_count += len(result.failed_fixes)
        guard_regression_count += len(result.regressed_guards)
        missing_validation_count += len(result.missing_validations)
        avoided_prefix_events += int(result.avoided_prefix_event_count)
        addressed_prefix_events += int(result.addressed_prefix_event_count)
        verified_reused_prefix_events += int(result.verified_reused_prefix_event_count)
        if result.restore.prefix_reused is True:
            prefix_reuse_counts["verified_reuse"] += 1
        elif result.restore.prefix_reused is False:
            prefix_reuse_counts["reconstructed"] += 1
        else:
            prefix_reuse_counts["unknown"] += 1
        replay_distance_events += int(result.replay_distance_events)
        restore_minutes += float(result.restore.restore_minutes)
        equivalence_minutes += float(result.restore.equivalence_minutes)
        suffix_minutes += float(result.restore.suffix_minutes)
        replay_wall_minutes += float(result.restore.replay_wall_minutes)

        if result.candidate_id in baselines:
            fresh = max(0.0, float(baselines[result.candidate_id]))
            avoided = max(0.0, fresh - float(result.restore.replay_wall_minutes))
            estimated_fresh_minutes += fresh
            estimated_avoided_minutes += avoided
            fresh_samples += 1
            if decision == "promoted":
                promoted_avoided_minutes += avoided

    return {
        "counterfactual_attempt_count": len(results),
        "promotion_count": int(decision_counts["promoted"]),
        "rejection_count": int(decision_counts["rejected"]),
        "observed_only_count": int(decision_counts["observed_only"]),
        "failed_fix_count": failed_fix_count,
        "guard_regression_count": guard_regression_count,
        "missing_validation_count": missing_validation_count,
        "addressed_prefix_event_count": addressed_prefix_events,
        "avoided_prefix_event_count": avoided_prefix_events,
        "verified_reused_prefix_event_count": verified_reused_prefix_events,
        "replay_distance_event_count": replay_distance_events,
        "restore_minutes": round(restore_minutes, 6),
        "equivalence_minutes": round(equivalence_minutes, 6),
        "suffix_minutes": round(suffix_minutes, 6),
        "replay_wall_minutes": round(replay_wall_minutes, 6),
        "fresh_compute_sample_count": fresh_samples,
        "estimated_fresh_compute_minutes": round(estimated_fresh_minutes, 6),
        "estimated_avoided_compute_minutes": round(estimated_avoided_minutes, 6),
        "promoted_avoided_compute_minutes": round(promoted_avoided_minutes, 6),
        "decision_counts": dict(sorted(decision_counts.items())),
        "restored_fidelity_counts": dict(sorted(fidelity_counts.items())),
        "prefix_reuse_counts": dict(sorted(prefix_reuse_counts.items())),
    }

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from .state import normalize_scheduler_rrule, rrule_for_minutes


SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA = (
    "loopx_scheduler_state_transition_request_v0"
)
SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA = (
    "loopx_scheduler_state_transition_result_v0"
)


class SchedulerCadenceTransition(str, Enum):
    INITIAL = "initial"
    IDENTITY_RESET = "identity_reset"
    RETRY_UNACKNOWLEDGED_FAILURE = "retry_unacknowledged_failure"
    HOLD_ACTIVE_INITIAL = "hold_active_initial"
    ADVANCE_AFTER_INTERVAL = "advance_after_interval"
    HOLD_UNTIL_INTERVAL = "hold_until_interval"


@dataclass(frozen=True)
class SchedulerCadenceDecision:
    current_index: int
    state_status: str
    transition: SchedulerCadenceTransition
    current_cadence_acknowledged: bool


def _runtime_result(params: dict[str, Any]) -> Mapping[str, Any]:
    try:
        result = effect_runtime_result("scheduler.state_transition.evaluate", params)
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping):
        raise RuntimeError("TypeScript scheduler transition result must be an object")
    if result.get("schema_version") != SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA:
        raise RuntimeError("TypeScript scheduler transition result shape mismatch")
    return result


def _scheduler_applied_index(
    progression_minutes: Sequence[int], scheduler_state: Mapping[str, Any]
) -> int:
    raw_index = scheduler_state.get("progression_index")
    if raw_index is None:
        return -1
    try:
        applied_index = int(raw_index)
    except (TypeError, ValueError):
        return -1
    return applied_index if 0 <= applied_index < len(progression_minutes) else -1


def decide_scheduler_cadence_transition(
    progression_minutes: Sequence[int],
    *,
    scheduler_state: Mapping[str, Any],
    reset_token: str,
    identity_signature: str,
    advance_same_identity: bool,
    applied_interval_elapsed: bool,
    has_host_update_failures: bool,
) -> SchedulerCadenceDecision:
    """Choose the cadence index through the TypeScript transition kernel."""

    if not progression_minutes:
        raise ValueError("scheduler cadence progression must not be empty")
    identity_matches = bool(scheduler_state) and (
        scheduler_state.get("reset_token") == reset_token
        and scheduler_state.get("identity_signature") == identity_signature
    )
    applied_index = _scheduler_applied_index(progression_minutes, scheduler_state)
    applied_target_rrule = (
        rrule_for_minutes(progression_minutes[applied_index])
        if 0 <= applied_index < len(progression_minutes)
        else ""
    )
    current_cadence_acknowledged = (
        bool(applied_target_rrule)
        and normalize_scheduler_rrule(scheduler_state.get("last_applied_rrule"))
        == applied_target_rrule
    )
    result = _runtime_result(
        {
            "schema_version": SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
            "operation": "cadence",
            "progression_size": len(progression_minutes),
            "state_present": bool(scheduler_state),
            "identity_matches": identity_matches,
            "applied_index": applied_index,
            "current_cadence_acknowledged": current_cadence_acknowledged,
            "advance_same_identity": advance_same_identity,
            "applied_interval_elapsed": applied_interval_elapsed,
            "has_host_update_failures": has_host_update_failures,
        }
    )
    transition = result.get("transition")
    current_index = result.get("current_index")
    state_status = result.get("state_status")
    acknowledged = result.get("current_cadence_acknowledged")
    if (
        result.get("operation") != "cadence"
        or isinstance(current_index, bool)
        or not isinstance(current_index, int)
        or not isinstance(state_status, str)
        or transition not in {item.value for item in SchedulerCadenceTransition}
        or not isinstance(acknowledged, bool)
    ):
        raise RuntimeError("TypeScript scheduler cadence result shape mismatch")
    return SchedulerCadenceDecision(
        current_index=current_index,
        state_status=state_status,
        transition=SchedulerCadenceTransition(str(transition)),
        current_cadence_acknowledged=acknowledged,
    )


class SchedulerHostTransition(str, Enum):
    APPLY_REQUIRED = "apply_required"
    HOST_MATCH_ACK_REQUIRED = "host_match_ack_required"
    RECORDED_FAILURE_SUPPRESSED = "recorded_failure_suppressed"
    SETTLED = "settled"


@dataclass(frozen=True)
class SchedulerHostDecision:
    transition: SchedulerHostTransition
    current_target_has_failure: bool
    repeated_failed_pair: bool

    @property
    def apply_needed(self) -> bool:
        return self.transition == SchedulerHostTransition.APPLY_REQUIRED

    @property
    def host_match_ack_needed(self) -> bool:
        return self.transition == SchedulerHostTransition.HOST_MATCH_ACK_REQUIRED

    @property
    def host_failure_suppressed(self) -> bool:
        return self.transition == SchedulerHostTransition.RECORDED_FAILURE_SUPPRESSED

    @property
    def ack_needed(self) -> bool:
        return self.transition in {
            SchedulerHostTransition.APPLY_REQUIRED,
            SchedulerHostTransition.HOST_MATCH_ACK_REQUIRED,
        }


def decide_scheduler_host_transition(
    *,
    state_status: str,
    observed_host_rrule: str,
    effective_host_rrule: str,
    current_rrule: str,
    current_rrule_already_applied: bool,
    scheduler_state_acknowledges_current_rrule: bool,
    all_host_update_failures: Collection[Mapping[str, Any]],
    recorded_host_failure: Mapping[str, Any] | None,
) -> SchedulerHostDecision:
    """Classify the host action through the TypeScript transition kernel."""

    current_target_has_failure = any(
        normalize_scheduler_rrule(failure.get("target_rrule")) == current_rrule
        for failure in all_host_update_failures
    )
    failed_target_rrule = normalize_scheduler_rrule(
        (recorded_host_failure or {}).get("target_rrule")
    )
    failed_observed_host_rrule = normalize_scheduler_rrule(
        (recorded_host_failure or {}).get("observed_host_rrule")
    )
    repeated_failed_pair = bool(
        failed_target_rrule == current_rrule
        and failed_observed_host_rrule == effective_host_rrule
    )

    result = _runtime_result(
        {
            "schema_version": SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
            "operation": "host",
            "state_status": state_status,
            "observed_host_rrule_present": bool(observed_host_rrule),
            "current_rrule_already_applied": current_rrule_already_applied,
            "scheduler_state_acknowledges_current_rrule": (
                scheduler_state_acknowledges_current_rrule
            ),
            "current_target_has_failure": current_target_has_failure,
            "repeated_failed_pair": repeated_failed_pair,
        }
    )
    transition = result.get("transition")
    result_has_failure = result.get("current_target_has_failure")
    result_repeated_pair = result.get("repeated_failed_pair")
    if (
        result.get("operation") != "host"
        or transition not in {item.value for item in SchedulerHostTransition}
        or not isinstance(result_has_failure, bool)
        or not isinstance(result_repeated_pair, bool)
    ):
        raise RuntimeError("TypeScript scheduler host result shape mismatch")
    return SchedulerHostDecision(
        transition=SchedulerHostTransition(str(transition)),
        current_target_has_failure=result_has_failure,
        repeated_failed_pair=result_repeated_pair,
    )

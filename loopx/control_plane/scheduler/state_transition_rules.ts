import type { JsonObject } from "../effect_program.ts";

export const SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA =
  "loopx_scheduler_state_transition_request_v0";
export const SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA =
  "loopx_scheduler_state_transition_result_v0";

export const SCHEDULER_CADENCE_TRANSITIONS = [
  "initial",
  "identity_reset",
  "retry_unacknowledged_failure",
  "hold_active_initial",
  "advance_after_interval",
  "hold_until_interval",
] as const;
export type SchedulerCadenceTransition =
  (typeof SCHEDULER_CADENCE_TRANSITIONS)[number];

export const SCHEDULER_HOST_TRANSITIONS = [
  "apply_required",
  "host_match_ack_required",
  "recorded_failure_suppressed",
  "settled",
] as const;
export type SchedulerHostTransition =
  (typeof SCHEDULER_HOST_TRANSITIONS)[number];

function requiredObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function requiredInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`${label} must be an integer`);
  }
  return value;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function requestObject(value: unknown): JsonObject {
  const request = requiredObject(value, "scheduler.state_transition params");
  if (request.schema_version !== SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA) {
    throw new Error("Scheduler state transition request schema mismatch");
  }
  return request;
}

function evaluateCadence(request: JsonObject): JsonObject {
  const progressionSize = requiredInteger(
    request.progression_size,
    "progression_size",
  );
  if (progressionSize < 1) {
    throw new Error("scheduler cadence progression must not be empty");
  }
  if (!requiredBoolean(request.state_present, "state_present")) {
    return {
      schema_version: SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA,
      operation: "cadence",
      current_index: 0,
      state_status: "missing",
      transition: "initial",
      current_cadence_acknowledged: false,
    };
  }
  if (!requiredBoolean(request.identity_matches, "identity_matches")) {
    return {
      schema_version: SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA,
      operation: "cadence",
      current_index: 0,
      state_status: "reset_required",
      transition: "identity_reset",
      current_cadence_acknowledged: false,
    };
  }

  const appliedIndex = requiredInteger(request.applied_index, "applied_index");
  const acknowledged = requiredBoolean(
    request.current_cadence_acknowledged,
    "current_cadence_acknowledged",
  );
  let nextIndex: number;
  let transition: SchedulerCadenceTransition;
  if (requiredBoolean(request.has_host_update_failures, "has_host_update_failures") &&
    !acknowledged) {
    nextIndex = appliedIndex;
    transition = "retry_unacknowledged_failure";
  } else if (!requiredBoolean(request.advance_same_identity, "advance_same_identity")) {
    nextIndex = 0;
    transition = "hold_active_initial";
  } else if (requiredBoolean(request.applied_interval_elapsed, "applied_interval_elapsed")) {
    nextIndex = appliedIndex + 1;
    transition = "advance_after_interval";
  } else {
    nextIndex = appliedIndex;
    transition = "hold_until_interval";
  }
  return {
    schema_version: SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA,
    operation: "cadence",
    current_index: Math.min(Math.max(nextIndex, 0), progressionSize - 1),
    state_status: "same_identity",
    transition,
    current_cadence_acknowledged: acknowledged,
  };
}

function evaluateHost(request: JsonObject): JsonObject {
  const stateStatus = requiredString(request.state_status, "state_status");
  const currentTargetHasFailure = requiredBoolean(
    request.current_target_has_failure,
    "current_target_has_failure",
  );
  const repeatedFailedPair = requiredBoolean(
    request.repeated_failed_pair,
    "repeated_failed_pair",
  );
  let transition: SchedulerHostTransition;
  if (
    requiredBoolean(request.observed_host_rrule_present, "observed_host_rrule_present") &&
    requiredBoolean(request.current_rrule_already_applied, "current_rrule_already_applied") &&
    (!requiredBoolean(
      request.scheduler_state_acknowledges_current_rrule,
      "scheduler_state_acknowledges_current_rrule",
    ) || stateStatus !== "same_identity" || currentTargetHasFailure)
  ) {
    transition = "host_match_ack_required";
  } else if (
    requiredBoolean(request.current_rrule_already_applied, "current_rrule_already_applied") &&
    stateStatus === "same_identity"
  ) {
    transition = "settled";
  } else if (repeatedFailedPair) {
    transition = "recorded_failure_suppressed";
  } else {
    transition = "apply_required";
  }
  return {
    schema_version: SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA,
    operation: "host",
    transition,
    current_target_has_failure: currentTargetHasFailure,
    repeated_failed_pair: repeatedFailedPair,
  };
}

export function evaluateSchedulerStateTransition(value: unknown): JsonObject {
  const request = requestObject(value);
  if (request.operation === "cadence") return evaluateCadence(request);
  if (request.operation === "host") return evaluateHost(request);
  throw new Error("Scheduler state transition operation is unsupported");
}

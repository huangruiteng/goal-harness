import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import type { JsonObject } from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  atomicWriteJson,
  withFileMutationLock,
} from "../effect_runtime_io.ts";
import {
  requireBoolean as requiredBoolean,
  requireInteger as requiredInteger,
  requireJsonObject as requiredObject,
  requireNonEmptyString as requiredString,
  requireStringLiteral,
} from "../runtime_decode.ts";
import {
  buildSchedulerState,
  CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
  CODEX_APP_SURFACE,
  mergeSchedulerHostUpdateFailure,
  normalizeSchedulerHostUpdateFailures,
  normalizeSchedulerRrule,
  normalizeSchedulerState,
  retainedSchedulerHostUpdateFailures,
  rruleForMinutes,
  schedulerRruleIntervalMinutes,
  schedulerStatePath,
  loadSchedulerState,
  normalizeSchedulerHostUpdateFailure,
  SCHEDULER_STATE_STORE_REQUEST_SCHEMA,
  type SchedulerScope,
} from "./state_store.ts";
import { evaluateSchedulerStateTransition } from "./state_transition_rules.ts";

export const SCHEDULER_HEARTBEAT_COMMIT_REQUEST_SCHEMA =
  "loopx_scheduler_heartbeat_commit_request_v0";
export const SCHEDULER_HEARTBEAT_COMMIT_RESULT_SCHEMA =
  "loopx_scheduler_heartbeat_commit_result_v0";
export const SCHEDULER_HEARTBEAT_COMMIT_RECEIPT_SCHEMA =
  "scheduler_heartbeat_commit_receipt_v0";
export const SCHEDULER_HEARTBEAT_COMMIT_OPERATIONS = [
  "ack",
  "host_failure",
] as const;
export type SchedulerHeartbeatCommitOperation =
  (typeof SCHEDULER_HEARTBEAT_COMMIT_OPERATIONS)[number];

export const SCHEDULER_ACK_STALE_HINT_TOLERANCE_MINUTES = 2;

export type SchedulerHeartbeatCommitStatus =
  "written" | "replayed" | "conflict" | "skipped" | "preview";

export interface SchedulerHeartbeatCommitRequest {
  schema_version: typeof SCHEDULER_HEARTBEAT_COMMIT_REQUEST_SCHEMA;
  operation: SchedulerHeartbeatCommitOperation;
  effect_id: string;
  runtime_root: string;
  scope: SchedulerScope;
  reset_token: string;
  identity_signature: string;
  progression_index: number;
  progression_minutes: number[];
  expected_rrule: string;
  applied_rrule: string;
  cadence_class: string;
  stale_tolerance_minutes: number;
  generated_at: string;
  expected_state_digest: string | null;
  execute: boolean;
  ack_needed: boolean | null;
  apply_needed: boolean | null;
  source: string;
  host_match_observed: boolean;
  failure_kind: string | null;
  observed_host_rrule: string;
  prior_host_update_failures: JsonObject[];
}
interface CommitMetadata {
  schema_version: typeof SCHEDULER_HEARTBEAT_COMMIT_RECEIPT_SCHEMA;
  effect_id: string;
  request_digest: string;
  operation: SchedulerHeartbeatCommitOperation;
}

export interface SchedulerHeartbeatCommitResult extends JsonObject {
  schema_version: typeof SCHEDULER_HEARTBEAT_COMMIT_RESULT_SCHEMA;
  operation: SchedulerHeartbeatCommitOperation;
  effect_id: string;
  status: SchedulerHeartbeatCommitStatus;
  written: boolean;
  replayed: boolean;
  conflict: boolean;
  already_applied: boolean;
  path: string;
  state: JsonObject | null;
  expected_state_digest: string | null;
  actual_state_digest: string | null;
  state_digest: string | null;
  reason: string;
  reason_code?: string;
  expected_rrule?: string;
  applied_rrule?: string;
  target_rrule?: string;
  observed_host_rrule?: string;
  failure_count?: number;
  stale_hint_accepted?: boolean;
  stale_hint_tolerance_minutes?: number;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([key, child]) => [key, stableValue(child)]),
  );
}

function sha256(value: string): string {
  return `sha256:${createHash("sha256").update(value, "utf8").digest("hex")}`;
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

export function schedulerHeartbeatCommitStateDigest(
  state: JsonObject | null,
): string | null {
  if (state === null) return null;
  const domainState = Object.fromEntries(
    Object.entries(state).filter(([key]) => key !== "heartbeat_commit"),
  );
  return sha256(canonicalJson(domainState));
}

// Aliases keep the digest useful to callers that name it after the state store.
export const schedulerStateDigest = schedulerHeartbeatCommitStateDigest;

function requestDigest(request: SchedulerHeartbeatCommitRequest): string {
  return sha256(canonicalJson({
    schema_version: request.schema_version,
    operation: request.operation,
    runtime_root: request.runtime_root,
    goal_id: request.scope.goalId,
    agent_id: request.scope.agentId,
    surface: request.scope.surface,
    state_key: request.scope.stateKey,
    reset_token: request.reset_token,
    identity_signature: request.identity_signature,
    progression_index: request.progression_index,
    progression_minutes: request.progression_minutes,
    expected_rrule: request.expected_rrule,
    applied_rrule: request.applied_rrule,
    cadence_class: request.cadence_class,
    stale_tolerance_minutes: request.stale_tolerance_minutes,
    generated_at: request.generated_at,
    expected_state_digest: request.expected_state_digest,
    execute: request.execute,
    ack_needed: request.ack_needed,
    apply_needed: request.apply_needed,
    source: request.source,
    host_match_observed: request.host_match_observed,
    failure_kind: request.failure_kind,
    observed_host_rrule: request.observed_host_rrule,
    prior_host_update_failures: request.prior_host_update_failures,
  }));
}

function textOrDefault(
  value: unknown,
  label: string,
  defaultValue: string,
): string {
  if (value === undefined || value === null || value === "") return defaultValue;
  return requiredString(value, label).trim();
}

function optionalBoolean(value: unknown, label: string): boolean | null {
  if (value === undefined || value === null) return null;
  return requiredBoolean(value, label);
}

function optionalDigest(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  return requiredString(value, "expected_state_digest").trim();
}

function positiveIntegerList(value: unknown, label: string): number[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new EffectRuntimeRequestError(`${label} must be a non-empty array of positive integers`);
  }
  const result = value.map((item, index) => {
    const number = requiredInteger(item, `${label}[${index}]`);
    if (number <= 0) {
      throw new EffectRuntimeRequestError(`${label} must be a non-empty array of positive integers`);
    }
    return number;
  });
  return result;
}

function optionalFailureList(value: unknown): JsonObject[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new EffectRuntimeRequestError("prior_host_update_failures must be an array");
  }
  const normalized = value.map((candidate, index) => {
    const failure = normalizeSchedulerHostUpdateFailure(candidate);
    if (!failure) {
      throw new EffectRuntimeRequestError(
        `prior_host_update_failures[${index}] is malformed`,
      );
    }
    return failure;
  });
  return normalizeSchedulerHostUpdateFailures(normalized);
}

function requestObject(value: unknown): SchedulerHeartbeatCommitRequest {
  const request = requiredObject(value, "scheduler.heartbeat.commit params");
  if (request.schema_version !== SCHEDULER_HEARTBEAT_COMMIT_REQUEST_SCHEMA) {
    throw new EffectRuntimeRequestError("Scheduler heartbeat commit request schema mismatch");
  }
  const operation = requireStringLiteral(
    request.operation,
    SCHEDULER_HEARTBEAT_COMMIT_OPERATIONS,
    "scheduler heartbeat commit operation",
    "Scheduler heartbeat commit operation is unsupported",
  );
  const effectId = requiredString(request.effect_id, "effect_id").trim();
  const runtimeRoot = requiredString(request.runtime_root, "runtime_root").trim();
  const goalId = requiredString(request.goal_id, "goal_id").trim();
  const agentId = requiredString(request.agent_id, "agent_id").trim();
  const surface = textOrDefault(request.surface, "surface", CODEX_APP_SURFACE);
  const stateKey = textOrDefault(
    request.state_key,
    "state_key",
    CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
  );
  const resetToken = requiredString(request.reset_token, "reset_token").trim();
  const identitySignature = requiredString(
    request.identity_signature,
    "identity_signature",
  ).trim();
  const progressionIndex = requiredInteger(
    request.progression_index,
    "progression_index",
  );
  const progressionMinutes = positiveIntegerList(
    request.progression_minutes,
    "progression_minutes",
  );
  if (progressionIndex < 0 || progressionIndex >= progressionMinutes.length) {
    throw new EffectRuntimeRequestError("progression_index must refer to progression_minutes");
  }
  const generatedAt = requiredString(request.generated_at, "generated_at").trim();
  const execute = request.execute === undefined
    ? true
    : requiredBoolean(request.execute, "execute");
  const ackNeeded = optionalBoolean(request.ack_needed, "ack_needed");
  const hostMatchObserved = request.host_match_observed === undefined
    ? false
    : requiredBoolean(request.host_match_observed, "host_match_observed");
  const source = textOrDefault(request.source, "source", "quota_scheduler_ack");
  const staleToleranceMinutes = request.stale_tolerance_minutes === undefined
    ? SCHEDULER_ACK_STALE_HINT_TOLERANCE_MINUTES
    : requiredInteger(request.stale_tolerance_minutes, "stale_tolerance_minutes");
  if (staleToleranceMinutes < 0) {
    throw new EffectRuntimeRequestError("stale_tolerance_minutes must not be negative");
  }

  const derivedRrule = rruleForMinutes(progressionMinutes[progressionIndex]);
  const expectedRrule = normalizeSchedulerRrule(
    request.expected_rrule ?? request.target_rrule ?? derivedRrule,
  );
  if (!expectedRrule) throw new EffectRuntimeRequestError("expected_rrule must not be empty");
  const appliedRrule = normalizeSchedulerRrule(
    request.applied_rrule ?? request.acknowledged_rrule ?? "",
  );
  const observedHostRrule = normalizeSchedulerRrule(
    request.observed_host_rrule ?? request.observed_rrule ?? "",
  );
  const cadenceClass = textOrDefault(
    request.cadence_class,
    "cadence_class",
    "default",
  );
  const failureKind = request.failure_kind === undefined ||
      request.failure_kind === null || request.failure_kind === ""
    ? null
    : requiredString(request.failure_kind, "failure_kind").trim();
  const priorHostUpdateFailures = optionalFailureList(
    request.prior_host_update_failures,
  );
  return {
    schema_version: SCHEDULER_HEARTBEAT_COMMIT_REQUEST_SCHEMA,
    operation,
    effect_id: effectId,
    runtime_root: runtimeRoot,
    scope: { goalId, agentId, surface, stateKey },
    reset_token: resetToken,
    identity_signature: identitySignature,
    progression_index: progressionIndex,
    progression_minutes: progressionMinutes,
    expected_rrule: expectedRrule,
    applied_rrule: appliedRrule,
    cadence_class: cadenceClass,
    stale_tolerance_minutes: staleToleranceMinutes,
    generated_at: generatedAt,
    expected_state_digest: optionalDigest(request.expected_state_digest),
    execute,
    ack_needed: ackNeeded,
    apply_needed: optionalBoolean(request.apply_needed, "apply_needed"),
    source,
    host_match_observed: hostMatchObserved,
    failure_kind: failureKind,
    observed_host_rrule: observedHostRrule,
    prior_host_update_failures: priorHostUpdateFailures,
  };
}

function commitMetadata(state: JsonObject | null): CommitMetadata | null {
  if (!state) return null;
  const value = state.heartbeat_commit;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const metadata = value as Record<string, unknown>;
  if (
    metadata.schema_version !== SCHEDULER_HEARTBEAT_COMMIT_RECEIPT_SCHEMA ||
    typeof metadata.effect_id !== "string" ||
    typeof metadata.request_digest !== "string" ||
    (metadata.operation !== "ack" && metadata.operation !== "host_failure")
  ) return null;
  return {
    schema_version: SCHEDULER_HEARTBEAT_COMMIT_RECEIPT_SCHEMA,
    effect_id: metadata.effect_id,
    request_digest: metadata.request_digest,
    operation: metadata.operation,
  };
}

function withCommitMetadata(
  state: JsonObject,
  request: SchedulerHeartbeatCommitRequest,
  digest: string,
): JsonObject {
  return {
    ...state,
    heartbeat_commit: {
      schema_version: SCHEDULER_HEARTBEAT_COMMIT_RECEIPT_SCHEMA,
      effect_id: request.effect_id,
      request_digest: digest,
      operation: request.operation,
    },
  };
}

function result(
  request: SchedulerHeartbeatCommitRequest,
  path: string,
  status: SchedulerHeartbeatCommitStatus,
  state: JsonObject | null,
  reason: string,
  extra: Partial<SchedulerHeartbeatCommitResult> = {},
): SchedulerHeartbeatCommitResult {
  const actualDigest = schedulerHeartbeatCommitStateDigest(state);
  return {
    schema_version: SCHEDULER_HEARTBEAT_COMMIT_RESULT_SCHEMA,
    operation: request.operation,
    effect_id: request.effect_id,
    status,
    written: status === "written",
    replayed: status === "replayed",
    conflict: status === "conflict",
    already_applied: status === "skipped",
    path,
    state,
    expected_state_digest: request.expected_state_digest,
    actual_state_digest: actualDigest,
    state_digest: actualDigest,
    reason,
    ...extra,
  };
}

function stateForScope(
  value: unknown,
  scope: SchedulerScope,
): JsonObject | null {
  return normalizeSchedulerState(value, scope);
}

function priorFailuresForRequest(
  request: SchedulerHeartbeatCommitRequest,
  existing: JsonObject | null,
): JsonObject[] {
  if (existing !== null) {
    return normalizeSchedulerHostUpdateFailures(
      existing.host_update_failures,
      existing.host_update_failure,
    );
  }
  return request.prior_host_update_failures;
}

async function readStateUnderLock(
  path: string,
  scope: SchedulerScope,
): Promise<JsonObject | null> {
  try {
    const parsed: unknown = JSON.parse(await readFile(path, "utf8"));
    const state = stateForScope(parsed, scope);
    if (!state) throw new Error("persisted scheduler state is invalid");
    return state;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if (error instanceof SyntaxError) {
      throw new Error("persisted scheduler state is not valid JSON");
    }
    throw error;
  }
}

function transitionAllowsStaleAck(
  request: SchedulerHeartbeatCommitRequest,
  existing: JsonObject | null,
): boolean {
  if (request.cadence_class !== "monitor_wait") return false;
  const appliedMinutes = schedulerRruleIntervalMinutes(request.applied_rrule);
  const expectedMinutes = schedulerRruleIntervalMinutes(request.expected_rrule);
  if (
    appliedMinutes === null ||
    expectedMinutes === null ||
    appliedMinutes < expectedMinutes ||
    appliedMinutes - expectedMinutes > request.stale_tolerance_minutes
  ) return false;
  // The transition kernel owns the monitor tolerance calculation. The caller's
  // identity proof remains explicit below and is never inferred from prose.
  const syntheticState: JsonObject = {
    ...(existing ?? {}),
    progression_index: request.progression_index,
    progression_minutes: request.progression_minutes,
    last_applied_rrule: request.applied_rrule,
    reset_token: request.reset_token,
    identity_signature: request.identity_signature,
    updated_at: request.generated_at,
  };
  const transition = evaluateSchedulerStateTransition({
    schema_version: "loopx_scheduler_state_transition_request_v0",
    operation: "backoff",
    progression_minutes: request.progression_minutes,
    scheduler_state: syntheticState,
    reset_token: request.reset_token,
    identity_signature: request.identity_signature,
    advance_same_identity: true,
    current_time: request.generated_at,
    observed_host_rrule: "",
    cadence_class: request.cadence_class,
    stale_tolerance_minutes: request.stale_tolerance_minutes,
  });
  if (
    transition.current_rrule !== request.expected_rrule ||
    !transition.current_rrule_already_applied
  ) return false;
  const proofMatchesExisting = existing !== null &&
    existing.reset_token === request.reset_token &&
    existing.identity_signature === request.identity_signature;
  return proofMatchesExisting || existing === null;
}

function isStaleMonitorAck(
  request: SchedulerHeartbeatCommitRequest,
): boolean {
  return request.operation === "ack" &&
    request.cadence_class === "monitor_wait" &&
    request.applied_rrule !== request.expected_rrule;
}

function buildAckState(
  request: SchedulerHeartbeatCommitRequest,
  existing: JsonObject | null,
  path: string,
  fingerprint: string,
): { state: JsonObject; extra: Partial<SchedulerHeartbeatCommitResult> } |
  SchedulerHeartbeatCommitResult {
  if (request.ack_needed === false && request.apply_needed === false) {
    return result(
      request,
      path,
      "skipped",
      existing,
      "scheduler RRULE already applied; no ack write needed",
    );
  }
  const derivedRrule = rruleForMinutes(
    request.progression_minutes[request.progression_index],
  );
  if (request.expected_rrule !== derivedRrule) {
    return result(
      request,
      path,
      "conflict",
      existing,
      "expected_rrule does not match the progression target",
      {
        reason_code: "target_rrule_conflict",
        expected_rrule: derivedRrule,
        applied_rrule: request.applied_rrule,
      },
    );
  }
  const exact = request.applied_rrule === request.expected_rrule;
  if (
    !exact &&
    request.cadence_class === "monitor_wait" &&
    existing !== null &&
    (existing.reset_token !== request.reset_token ||
      existing.identity_signature !== request.identity_signature)
  ) {
    return result(
      request,
      path,
      "conflict",
      existing,
      "stale monitor ACK identity does not match persisted scheduler state",
      { reason_code: "identity_conflict" },
    );
  }
  if (!exact && !transitionAllowsStaleAck(request, existing)) {
    return result(
      request,
      path,
      "conflict",
      existing,
      "applied_rrule does not match the scheduler target",
      {
        reason_code: "rrule_mismatch",
        expected_rrule: request.expected_rrule,
        applied_rrule: request.applied_rrule,
      },
    );
  }
  if (!request.applied_rrule) {
    return result(
      request,
      path,
      "conflict",
      existing,
      "ack requires applied_rrule",
      { reason_code: "missing_applied_rrule" },
    );
  }
  const priorFailures = retainedSchedulerHostUpdateFailures(
    priorFailuresForRequest(request, existing),
    request.generated_at,
    request.applied_rrule,
  ).filter((failure) =>
    normalizeSchedulerRrule(failure.target_rrule) !== request.applied_rrule
  );
  let state = buildSchedulerState({
    goal_id: request.scope.goalId,
    agent_id: request.scope.agentId,
    surface: request.scope.surface,
    state_key: request.scope.stateKey,
    reset_token: request.reset_token,
    identity_signature: request.identity_signature,
    progression_index: request.progression_index,
    progression_minutes: request.progression_minutes,
    last_applied_rrule: request.applied_rrule,
    updated_at: request.generated_at,
    source: request.source,
    host_update_failures: priorFailures.length ? priorFailures : null,
  });
  state = withCommitMetadata(state, request, fingerprint);
  return {
    state,
    extra: {
      expected_rrule: request.expected_rrule,
      applied_rrule: request.applied_rrule,
      stale_hint_accepted: !exact,
      stale_hint_tolerance_minutes: request.stale_tolerance_minutes,
    },
  };
}

function buildHostFailureState(
  request: SchedulerHeartbeatCommitRequest,
  existing: JsonObject | null,
  path: string,
  fingerprint: string,
): { state: JsonObject; extra: Partial<SchedulerHeartbeatCommitResult> } |
  SchedulerHeartbeatCommitResult {
  if (request.apply_needed !== true) {
    return result(
      request,
      path,
      "conflict",
      existing,
      "scheduler host update failure is not recordable because no host update is needed",
      { reason_code: "host_update_not_needed" },
    );
  }
  const derivedRrule = rruleForMinutes(
    request.progression_minutes[request.progression_index],
  );
  if (!request.expected_rrule || request.expected_rrule !== derivedRrule) {
    return result(
      request,
      path,
      "conflict",
      existing,
      "target_rrule does not match the progression target",
      { reason_code: "target_rrule_conflict", expected_rrule: derivedRrule },
    );
  }
  const targetRrule = request.expected_rrule;
  const observedHostRrule = request.observed_host_rrule;
  const priorFailures = retainedSchedulerHostUpdateFailures(
    priorFailuresForRequest(request, existing),
    request.generated_at,
    observedHostRrule,
  );
  const priorFailure = [...priorFailures].reverse().find((failure) =>
    normalizeSchedulerRrule(failure.target_rrule) === targetRrule
  );
  const priorCount = typeof priorFailure?.failure_count === "number"
    ? priorFailure.failure_count
    : 0;
  const failure = {
    schema_version: "scheduler_host_update_failure_v0",
    target_rrule: targetRrule,
    observed_host_rrule: observedHostRrule,
    failure_kind: request.failure_kind || "host_tool_failure",
    failure_count: priorCount + 1,
    failed_at: request.generated_at,
  } satisfies JsonObject;
  const failures = mergeSchedulerHostUpdateFailure(
    priorFailures,
    failure,
    request.generated_at,
  );
  let state = buildSchedulerState({
    goal_id: request.scope.goalId,
    agent_id: request.scope.agentId,
    surface: request.scope.surface,
    state_key: request.scope.stateKey,
    reset_token: request.reset_token,
    identity_signature: request.identity_signature,
    progression_index: request.progression_index,
    progression_minutes: request.progression_minutes,
    last_applied_rrule: observedHostRrule,
    updated_at: request.generated_at,
    source: request.source,
    host_update_failure: failure,
    host_update_failures: failures,
  });
  state = withCommitMetadata(state, request, fingerprint);
  return {
    state,
    extra: {
      target_rrule: targetRrule,
      observed_host_rrule: observedHostRrule,
      failure_count: priorCount + 1,
    },
  };
}

export async function evaluateSchedulerHeartbeatCommit(
  value: unknown,
): Promise<SchedulerHeartbeatCommitResult> {
  const request = requestObject(value);
  const path = schedulerStatePath(request.runtime_root, request.scope);
  const fingerprint = requestDigest(request);
  // Execute mode migrates the legacy layout before taking the canonical lock.
  // Preview mode asks the state store for a read-only legacy fallback so a
  // dry-run cannot create or delete the canonical/legacy files.
  const loaded = await loadSchedulerState({
    schema_version: SCHEDULER_STATE_STORE_REQUEST_SCHEMA,
    runtime_root: request.runtime_root,
    goal_id: request.scope.goalId,
    agent_id: request.scope.agentId,
    surface: request.scope.surface,
    state_key: request.scope.stateKey,
    migrate_legacy: request.execute,
  });
  return await withFileMutationLock(path, async () => {
    const canonical = await readStateUnderLock(path, request.scope);
    const existing = canonical ?? (!request.execute ? loaded.state : null);
    const existingDigest = schedulerHeartbeatCommitStateDigest(existing);
    const metadata = commitMetadata(existing);
    if (metadata?.effect_id === request.effect_id) {
      if (
        metadata.operation === request.operation &&
        metadata.request_digest === fingerprint
      ) {
        return result(
          request,
          path,
          "replayed",
          existing,
          "scheduler heartbeat commit replayed",
        );
      }
      return result(
        request,
        path,
        "conflict",
        existing,
        "effect_id is already bound to a different scheduler heartbeat commit",
        { reason_code: "effect_id_conflict" },
      );
    }
    if (request.expected_state_digest !== existingDigest) {
      return result(
        request,
        path,
        "conflict",
        existing,
        "scheduler state compare-and-swap precondition failed",
        { reason_code: "state_digest_conflict" },
      );
    }
    const identityMatches = existing === null || (
      existing.reset_token === request.reset_token &&
      existing.identity_signature === request.identity_signature
    );
    // A changed scheduler identity starts a fresh progression. Initial and
    // identity-reset commits must begin at index zero; a stale monitor ACK is
    // the exception to the identity-reset path, not to the initial index rule.
    const identityReset = existing !== null && !identityMatches &&
      !request.host_match_observed && !isStaleMonitorAck(request);
    if (existing !== null && !identityMatches && !identityReset) {
      return result(
        request,
        path,
        "conflict",
        existing,
        "scheduler heartbeat identity does not match persisted state",
        { reason_code: "identity_conflict" },
      );
    }
    if (
      (existing === null || identityReset) &&
      request.progression_index !== 0
    ) {
      return result(
        request,
        path,
        "conflict",
        existing,
        "scheduler heartbeat initial or identity-reset progression must start at index zero",
        { reason_code: "initial_progression_index_conflict" },
      );
    }
    if (
      existing !== null &&
      identityMatches &&
      typeof existing.progression_index === "number" &&
      request.progression_index < existing.progression_index
    ) {
      return result(
        request,
        path,
        "conflict",
        existing,
        "scheduler heartbeat progression would move backwards",
        { reason_code: "progression_regression" },
      );
    }
    if (
      existing !== null &&
      identityMatches &&
      typeof existing.progression_index === "number" &&
      request.progression_index > existing.progression_index + 1
    ) {
      return result(
        request,
        path,
        "conflict",
        existing,
        "scheduler heartbeat progression cannot skip a cadence stage",
        { reason_code: "progression_skip_conflict" },
      );
    }
    const built = request.operation === "ack"
      ? buildAckState(request, existing, path, fingerprint)
      : buildHostFailureState(request, existing, path, fingerprint);
    if ("status" in built) return built;
    if (!request.execute) {
      return result(
        request,
        path,
        "preview",
        built.state,
        "scheduler heartbeat commit preview",
        built.extra,
      );
    }
    await atomicWriteJson(path, stableValue(built.state) as JsonObject);
    return result(
      request,
      path,
      "written",
      built.state,
      "scheduler heartbeat commit written",
      built.extra,
    );
  });
}

import { isAbsolute, join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { requireJsonObject } from "../runtime_decode.ts";
import type {
  AuthorityStore,
  AuthorityStoreCommittedTransaction,
  AuthorityStoreReceiptResult,
} from "./authority_store.ts";
import {
  canonicalAuthorityBytes,
  canonicalAuthorityObject,
  canonicalAuthoritySha256,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";
import { indexCoordinationProjectionTodos } from "./coordination_projection.ts";
import { FileAuthorityStore } from "./file_authority_store.ts";

export const COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_commit_v0";
export const COORDINATION_RUNTIME_SHADOW_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_result_v0";
export const COORDINATION_RUNTIME_SHADOW_RECEIPT_SCHEMA =
  "loopx_coordination_runtime_shadow_receipt_v0";
export const COORDINATION_RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_inspect_v0";
export const COORDINATION_RUNTIME_SHADOW_INSPECT_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_inspection_v0";
export const COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_bootstrap_v0";
export const COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_bootstrap_result_v0";
export const COORDINATION_RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_rollback_v0";
export const COORDINATION_RUNTIME_SHADOW_ROLLBACK_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_rollback_result_v0";
export const COORDINATION_RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_qualify_v0";
export const COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_qualification_v0";
export const COORDINATION_RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_todo_read_v0";
export const COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_todo_read_result_v0";

interface RuntimeShadowRequest {
  runtime_root: string;
  goal_id: string;
  operation_id: string;
  event_kind: string;
  source_version: string;
  projection: JsonObject;
}

interface RuntimeShadowDependencies {
  createStore?: (directory: string, goalId: string) => AuthorityStore;
  createFileStore?: (directory: string, goalId: string) => FileAuthorityStore;
}

interface RuntimeShadowInspectionRequest {
  runtime_root: string;
  goal_id: string;
  projection: JsonObject;
}

interface RuntimeShadowBootstrapRequest {
  runtime_root: string;
  goal_id: string;
  operation_id: string;
  source_version: string;
  projection: JsonObject;
}

interface RuntimeShadowRollbackRequest {
  runtime_root: string;
  goal_id: string;
  operation_id: string;
  expected_provider_revision: string;
}

interface RuntimeShadowQualificationRequest {
  runtime_root: string;
  goal_id: string;
  projection: JsonObject;
  minimum_operations: number;
  required_event_kinds: string[];
}

interface RuntimeShadowTodoReadRequest {
  runtime_root: string;
  goal_id: string;
  todo_id: string;
  projection: JsonObject;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() !== value || value.length === 0) {
    throw new Error(`${label} must be a non-empty trimmed string`);
  }
  return value;
}

function requiredPositiveSafeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1 || Number(value) > 10_000) {
    throw new Error(`${label} must be a positive safe integer no greater than 10000`);
  }
  return Number(value);
}

function requiredUniqueStrings(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  if (value.length > 32) throw new Error(`${label} must contain at most 32 entries`);
  const normalized = value.map((entry, index) =>
    requiredString(entry, `${label}[${index}]`)
  );
  if (new Set(normalized).size !== normalized.length) {
    throw new Error(`${label} must not contain duplicates`);
  }
  return normalized;
}

function decodeRequest(value: unknown): RuntimeShadowRequest {
  const input = requireJsonObject(value, "coordination runtime shadow request");
  if (input.schema_version !== COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA) {
    throw new Error("coordination runtime shadow request schema mismatch");
  }
  const runtimeRoot = requiredString(input.runtime_root, "runtime_root");
  if (!isAbsolute(runtimeRoot)) {
    throw new Error("runtime_root must be absolute");
  }
  return {
    runtime_root: runtimeRoot,
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    operation_id: requireAuthorityStoreId(input.operation_id, "operation id"),
    event_kind: requiredString(input.event_kind, "event_kind"),
    source_version: requiredString(input.source_version, "source_version"),
    projection: canonicalAuthorityObject(input.projection, "projection"),
  };
}

function decodeInspectionRequest(value: unknown): RuntimeShadowInspectionRequest {
  const input = requireJsonObject(value, "coordination runtime shadow inspection request");
  if (input.schema_version !== COORDINATION_RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA) {
    throw new Error("coordination runtime shadow inspection request schema mismatch");
  }
  const runtimeRoot = requiredString(input.runtime_root, "runtime_root");
  if (!isAbsolute(runtimeRoot)) {
    throw new Error("runtime_root must be absolute");
  }
  return {
    runtime_root: runtimeRoot,
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    projection: canonicalAuthorityObject(input.projection, "projection"),
  };
}

function decodeBootstrapRequest(value: unknown): RuntimeShadowBootstrapRequest {
  const input = requireJsonObject(value, "coordination runtime shadow bootstrap request");
  if (input.schema_version !== COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA) {
    throw new Error("coordination runtime shadow bootstrap request schema mismatch");
  }
  const runtimeRoot = requiredString(input.runtime_root, "runtime_root");
  if (!isAbsolute(runtimeRoot)) {
    throw new Error("runtime_root must be absolute");
  }
  return {
    runtime_root: runtimeRoot,
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    operation_id: requireAuthorityStoreId(input.operation_id, "operation id"),
    source_version: requiredString(input.source_version, "source_version"),
    projection: canonicalAuthorityObject(input.projection, "projection"),
  };
}

function decodeRollbackRequest(value: unknown): RuntimeShadowRollbackRequest {
  const input = requireJsonObject(value, "coordination runtime shadow rollback request");
  if (input.schema_version !== COORDINATION_RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA) {
    throw new Error("coordination runtime shadow rollback request schema mismatch");
  }
  const runtimeRoot = requiredString(input.runtime_root, "runtime_root");
  if (!isAbsolute(runtimeRoot)) {
    throw new Error("runtime_root must be absolute");
  }
  return {
    runtime_root: runtimeRoot,
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    operation_id: requireAuthorityStoreId(input.operation_id, "operation id"),
    expected_provider_revision: requireAuthorityStoreId(
      input.expected_provider_revision,
      "expected provider revision",
    ),
  };
}

function decodeQualificationRequest(value: unknown): RuntimeShadowQualificationRequest {
  const input = requireJsonObject(value, "coordination runtime shadow qualification request");
  if (input.schema_version !== COORDINATION_RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA) {
    throw new Error("coordination runtime shadow qualification request schema mismatch");
  }
  const runtimeRoot = requiredString(input.runtime_root, "runtime_root");
  if (!isAbsolute(runtimeRoot)) throw new Error("runtime_root must be absolute");
  return {
    runtime_root: runtimeRoot,
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    projection: canonicalAuthorityObject(input.projection, "projection"),
    minimum_operations: requiredPositiveSafeInteger(
      input.minimum_operations,
      "minimum_operations",
    ),
    required_event_kinds: requiredUniqueStrings(
      input.required_event_kinds,
      "required_event_kinds",
    ),
  };
}

function decodeTodoReadRequest(value: unknown): RuntimeShadowTodoReadRequest {
  const input = requireJsonObject(value, "coordination runtime shadow Todo read request");
  if (input.schema_version !== COORDINATION_RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA) {
    throw new Error("coordination runtime shadow Todo read request schema mismatch");
  }
  const runtimeRoot = requiredString(input.runtime_root, "runtime_root");
  if (!isAbsolute(runtimeRoot)) throw new Error("runtime_root must be absolute");
  return {
    runtime_root: runtimeRoot,
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    todo_id: requireAuthorityStoreId(input.todo_id, "todo id"),
    projection: canonicalAuthorityObject(input.projection, "projection"),
  };
}

function bootstrapEvent(request: RuntimeShadowBootstrapRequest): JsonObject {
  return {
    schema_version: "loopx_coordination_runtime_shadow_bootstrap_event_v0",
    operation_id: request.operation_id,
    source_version: request.source_version,
    source_projection_sha256: canonicalAuthoritySha256(request.projection),
    mode_declaration: "legacy_canonical_shadow",
  };
}

async function bootstrapReadback(
  store: AuthorityStore,
  request: RuntimeShadowBootstrapRequest,
): Promise<{
  matched: boolean;
  cursor?: string;
  provider_revision?: string;
  reason_code?: string;
}> {
  const head = await store.loadAuthority();
  if (head.status !== "loaded") {
    return {
      matched: false,
      reason_code: head.status === "missing" ? "shadow_bootstrap_missing" : head.reason_code,
    };
  }
  const history = await store.scanCommitted(null, 1);
  if (history.status !== "page" || history.transactions.length !== 1) {
    return {
      matched: false,
      reason_code: history.status === "page"
        ? "shadow_bootstrap_history_missing"
        : history.reason_code,
    };
  }
  const first = history.transactions[0]!;
  const matches = first.cursor === "1" &&
    first.operation_id === request.operation_id &&
    first.receipts.length === 0 &&
    canonicalAuthorityBytes(first.events).equals(
      canonicalAuthorityBytes([bootstrapEvent(request)]),
    ) &&
    canonicalAuthorityBytes(first.projection).equals(
      canonicalAuthorityBytes(request.projection),
    );
  return {
    matched: matches,
    cursor: head.cursor,
    provider_revision: head.provider_revision,
    ...(matches ? {} : { reason_code: "shadow_bootstrap_identity_mismatch" }),
  };
}

function bootstrapResult(
  request: RuntimeShadowBootstrapRequest,
  status: "applied" | "replayed" | "recovered",
  readback: Awaited<ReturnType<typeof bootstrapReadback>>,
): JsonObject {
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
    status,
    operation_id: request.operation_id,
    source_version: request.source_version,
    source_projection_sha256: canonicalAuthoritySha256(request.projection),
    mode_declaration: "legacy_canonical_shadow",
    cursor: readback.cursor,
    provider_revision: readback.provider_revision,
    bootstrap_receipts_empty: true,
    primary_writeback_preserved: true,
    decision_read_from_shadow: false,
  };
}

/**
 * Install the existing legacy coordination projection as the first file-shadow
 * head. This is an administrative import seam, not an agent mutation: it only
 * succeeds against an uninitialized store and intentionally creates no
 * operation receipt. The source digest and mode declaration live in the first
 * committed event so restart can distinguish migration from missing state.
 */
export async function bootstrapCoordinationRuntimeShadow(
  value: unknown,
  dependencies: RuntimeShadowDependencies = {},
): Promise<JsonObject> {
  let request: RuntimeShadowBootstrapRequest;
  try {
    request = decodeBootstrapRequest(value);
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_shadow_bootstrap_request",
      reason: error instanceof Error ? error.message : "invalid bootstrap request",
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }

  const directory = join(request.runtime_root, "authority-shadow", "file-v0");
  const store = dependencies.createStore?.(directory, request.goal_id) ??
    new FileAuthorityStore(directory, request.goal_id);
  try {
    const existing = await store.loadAuthority();
    if (existing.status === "loaded") {
      const readback = await bootstrapReadback(store, request);
      return readback.matched
        ? bootstrapResult(request, "replayed", readback)
        : {
          schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
          status: "failed",
          reason_code: readback.reason_code ?? "shadow_already_initialized",
          reason: "shadow store is already initialized by different content",
          current_provider_revision: existing.provider_revision,
          current_cursor: existing.cursor,
          primary_writeback_preserved: true,
          decision_read_from_shadow: false,
        };
    }
    if (existing.status !== "missing") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
        status: "failed",
        reason_code: existing.reason_code,
        reason: existing.reason,
        primary_writeback_preserved: true,
        decision_read_from_shadow: false,
      };
    }

    const result = await store.commitAuthority({
      expected_provider_revision: null,
      operation_id: request.operation_id,
      events: [bootstrapEvent(request)],
      next_projection: request.projection,
      receipts: [],
    });
    if (result.status === "applied") {
      const readback = await bootstrapReadback(store, request);
      if (!readback.matched) {
        return {
          schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
          status: "failed",
          reason_code: readback.reason_code ?? "shadow_bootstrap_readback_mismatch",
          reason: "bootstrap commit did not produce the expected initial lineage",
          primary_writeback_preserved: true,
          decision_read_from_shadow: false,
        };
      }
      return bootstrapResult(request, "applied", readback);
    }
    if (result.status === "ambiguous") {
      const readback = await bootstrapReadback(store, request);
      if (readback.matched) return bootstrapResult(request, "recovered", readback);
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
        status: "ambiguous",
        operation_id: request.operation_id,
        reason_code: result.reason_code,
        reason: result.reason,
        reconciliation_required: true,
        primary_writeback_preserved: true,
        decision_read_from_shadow: false,
      };
    }
    if (result.status === "conflict") {
      const readback = await bootstrapReadback(store, request);
      if (readback.matched) return bootstrapResult(request, "replayed", readback);
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
        status: "failed",
        reason_code: "shadow_already_initialized",
        reason: result.conflict_kind,
        current_provider_revision: result.current_provider_revision,
        current_cursor: result.current_cursor,
        primary_writeback_preserved: true,
        decision_read_from_shadow: false,
      };
    }
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
      status: "failed",
      reason_code: result.reason_code,
      reason: result.reason,
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_RESULT_SCHEMA,
      status: "failed",
      reason_code: "shadow_bootstrap_unavailable",
      reason: error instanceof Error ? error.message : "bootstrap unavailable",
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }
}

/**
 * Remove one exact file-shadow lineage from the active path while retaining a
 * durable quarantine copy. Legacy Todo/task-lease state remains canonical, so
 * this pre-promotion rollback never changes a runtime decision and may be
 * followed by a fresh bootstrap from that legacy source.
 */
export async function rollbackCoordinationRuntimeShadow(
  value: unknown,
  dependencies: RuntimeShadowDependencies = {},
): Promise<JsonObject> {
  let request: RuntimeShadowRollbackRequest;
  try {
    request = decodeRollbackRequest(value);
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_shadow_rollback_request",
      reason: error instanceof Error ? error.message : "invalid rollback request",
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }

  const directory = join(request.runtime_root, "authority-shadow", "file-v0");
  const store = dependencies.createFileStore?.(directory, request.goal_id) ??
    new FileAuthorityStore(directory, request.goal_id);
  const result = await store.archiveAuthorityDocument(
    request.expected_provider_revision,
    request.operation_id,
  );
  if (result.status === "applied" || result.status === "replayed") {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_RESULT_SCHEMA,
      ...result,
      operation_id: request.operation_id,
      expected_provider_revision: request.expected_provider_revision,
      active_shadow_removed: true,
      archive_retained: true,
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }
  if (result.status === "ambiguous") {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_RESULT_SCHEMA,
      ...result,
      operation_id: request.operation_id,
      expected_provider_revision: request.expected_provider_revision,
      reconciliation_required: true,
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }
  let reasonCode: string;
  let reason: string;
  if (result.status === "missing") {
    reasonCode = "shadow_rollback_source_missing";
    reason = "active shadow lineage is missing";
  } else if (result.status === "conflict") {
    reasonCode = result.conflict_kind;
    reason = result.conflict_kind;
  } else {
    reasonCode = result.reason_code;
    reason = result.reason;
  }
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_RESULT_SCHEMA,
    ...result,
    status: "failed",
    reason_code: reasonCode,
    reason,
    operation_id: request.operation_id,
    expected_provider_revision: request.expected_provider_revision,
    primary_writeback_preserved: true,
    decision_read_from_shadow: false,
  };
}

function expectedReceipt(request: RuntimeShadowRequest): JsonObject {
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_RECEIPT_SCHEMA,
    operation_id: request.operation_id,
    event_kind: request.event_kind,
    source_version: request.source_version,
    projection_sha256: canonicalAuthoritySha256(request.projection),
  };
}

function failed(
  reasonCode: string,
  reason: string,
  extra: JsonObject = {},
): JsonObject {
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_RESULT_SCHEMA,
    status: "failed",
    reason_code: reasonCode,
    reason,
    primary_writeback_preserved: true,
    decision_read_from_shadow: false,
    ...extra,
  };
}

function receiptMatches(
  readback: AuthorityStoreReceiptResult,
  receipt: JsonObject,
): boolean {
  if (readback.status !== "found") return false;
  const expected = canonicalAuthorityBytes(receipt);
  return readback.receipts.some((candidate) =>
    canonicalAuthorityBytes(candidate).equals(expected)
  );
}

function receiptResult(
  request: RuntimeShadowRequest,
  readback: AuthorityStoreReceiptResult,
  receipt: JsonObject,
  status: "replayed" | "recovered",
): JsonObject {
  if (readback.status !== "found") {
    return failed(
      "shadow_receipt_missing",
      "shadow operation has no durable receipt",
      { operation_id: request.operation_id },
    );
  }
  if (!receiptMatches(readback, receipt)) {
    return failed(
      "shadow_operation_identity_mismatch",
      "shadow operation id is already bound to different committed content",
      {
        operation_id: request.operation_id,
        cursor: readback.cursor,
        provider_revision: readback.provider_revision,
      },
    );
  }
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_RESULT_SCHEMA,
    status,
    operation_id: request.operation_id,
    cursor: readback.cursor,
    provider_revision: readback.provider_revision,
    parity: {
      schema_version: "loopx_coordination_runtime_shadow_parity_v0",
      receipt_matches: true,
      projection_sha256: receipt.projection_sha256,
    },
    primary_writeback_preserved: true,
    decision_read_from_shadow: false,
  };
}

async function verifyAppliedProjection(
  store: AuthorityStore,
  request: RuntimeShadowRequest,
  providerRevision: string,
): Promise<JsonObject> {
  const head = await store.loadAuthority();
  if (head.status !== "loaded") {
    return {
      verified: false,
      status: head.status,
      projection_matches: false,
    };
  }
  if (head.provider_revision !== providerRevision) {
    return {
      verified: false,
      status: "superseded_before_readback",
      projection_matches: null,
      current_provider_revision: head.provider_revision,
    };
  }
  const projectionMatches = canonicalAuthoritySha256(head.head) ===
    canonicalAuthoritySha256(request.projection);
  return {
    verified: projectionMatches,
    status: projectionMatches ? "matched_current_head" : "projection_mismatch",
    projection_matches: projectionMatches,
    provider_revision: head.provider_revision,
  };
}

/**
 * Compare the current legacy coordination projection with the file shadow.
 * This is an evidence-only read for Stage 2C migration/parity qualification;
 * callers must never use it to make a runtime coordination decision.
 */
export async function inspectCoordinationRuntimeShadow(
  value: unknown,
  dependencies: RuntimeShadowDependencies = {},
): Promise<JsonObject> {
  let request: RuntimeShadowInspectionRequest;
  try {
    request = decodeInspectionRequest(value);
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_INSPECT_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_shadow_inspection_request",
      reason: error instanceof Error ? error.message : "invalid shadow inspection request",
      parity_matches: false,
      bootstrap_required: false,
      decision_read_from_shadow: false,
    };
  }

  const directory = join(request.runtime_root, "authority-shadow", "file-v0");
  const store = dependencies.createStore?.(directory, request.goal_id) ??
    new FileAuthorityStore(directory, request.goal_id);
  const expectedProjectionSha256 = canonicalAuthoritySha256(request.projection);
  try {
    const head = await store.loadAuthority();
    if (head.status === "missing") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_INSPECT_RESULT_SCHEMA,
        status: "missing",
        expected_projection_sha256: expectedProjectionSha256,
        parity_matches: false,
        bootstrap_required: true,
        decision_read_from_shadow: false,
      };
    }
    if (head.status !== "loaded") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_INSPECT_RESULT_SCHEMA,
        status: "failed",
        reason_code: head.reason_code,
        reason: head.reason,
        expected_projection_sha256: expectedProjectionSha256,
        parity_matches: false,
        bootstrap_required: false,
        decision_read_from_shadow: false,
      };
    }
    const observedProjectionSha256 = canonicalAuthoritySha256(head.head);
    const parityMatches = observedProjectionSha256 === expectedProjectionSha256;
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_INSPECT_RESULT_SCHEMA,
      status: parityMatches ? "matched" : "drifted",
      expected_projection_sha256: expectedProjectionSha256,
      observed_projection_sha256: observedProjectionSha256,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      parity_matches: parityMatches,
      bootstrap_required: false,
      decision_read_from_shadow: false,
    };
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_INSPECT_RESULT_SCHEMA,
      status: "failed",
      reason_code: "shadow_read_unavailable",
      reason: error instanceof Error ? error.message : "shadow read unavailable",
      expected_projection_sha256: expectedProjectionSha256,
      parity_matches: false,
      bootstrap_required: false,
      decision_read_from_shadow: false,
    };
  }
}

/**
 * Exercise the first provider-read seam without promoting it to decision
 * authority. The file head is eligible as a read candidate only when it
 * matches the current legacy projection byte-for-byte; missing, drifted, or
 * malformed provider state fails closed and never falls back silently.
 */
export async function readCoordinationRuntimeShadowTodoCandidate(
  value: unknown,
  dependencies: RuntimeShadowDependencies = {},
): Promise<JsonObject> {
  let request: RuntimeShadowTodoReadRequest;
  try {
    request = decodeTodoReadRequest(value);
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_shadow_todo_read_request",
      reason: error instanceof Error ? error.message : "invalid Todo read request",
      read_candidate_qualified: false,
      decision_read_from_shadow: false,
    };
  }

  const directory = join(request.runtime_root, "authority-shadow", "file-v0");
  const store = dependencies.createStore?.(directory, request.goal_id) ??
    new FileAuthorityStore(directory, request.goal_id);
  const expectedProjectionSha256 = canonicalAuthoritySha256(request.projection);
  try {
    const head = await store.loadAuthority();
    if (head.status === "missing") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
        status: "missing",
        reason_code: "shadow_todo_read_store_missing",
        expected_projection_sha256: expectedProjectionSha256,
        read_candidate_qualified: false,
        bootstrap_required: true,
        decision_read_from_shadow: false,
      };
    }
    if (head.status !== "loaded") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
        status: "failed",
        reason_code: head.reason_code,
        reason: head.reason,
        expected_projection_sha256: expectedProjectionSha256,
        read_candidate_qualified: false,
        decision_read_from_shadow: false,
      };
    }
    const observedProjectionSha256 = canonicalAuthoritySha256(head.head);
    if (observedProjectionSha256 !== expectedProjectionSha256) {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
        status: "drifted",
        reason_code: "shadow_todo_read_projection_drift",
        expected_projection_sha256: expectedProjectionSha256,
        observed_projection_sha256: observedProjectionSha256,
        provider_revision: head.provider_revision,
        cursor: head.cursor,
        parity_matches: false,
        read_candidate_qualified: false,
        decision_read_from_shadow: false,
      };
    }
    const projection = indexCoordinationProjectionTodos(head.head, request.goal_id);
    const todo = projection.todos.get(request.todo_id);
    if (todo === undefined) {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
        status: "todo_missing",
        reason_code: "shadow_todo_read_todo_missing",
        todo_id: request.todo_id,
        todo_ids: projection.todo_ids,
        expected_projection_sha256: expectedProjectionSha256,
        observed_projection_sha256: observedProjectionSha256,
        provider_revision: head.provider_revision,
        cursor: head.cursor,
        parity_matches: true,
        read_candidate_qualified: false,
        decision_read_from_shadow: false,
      };
    }
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
      status: "matched",
      todo_id: request.todo_id,
      todo,
      todo_ids: projection.todo_ids,
      expected_projection_sha256: expectedProjectionSha256,
      observed_projection_sha256: observedProjectionSha256,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      parity_matches: true,
      read_candidate_qualified: true,
      source: "file_v0",
      decision_read_from_shadow: false,
    };
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_RESULT_SCHEMA,
      status: "failed",
      reason_code: "shadow_todo_read_unavailable",
      reason: error instanceof Error ? error.message : "Todo read unavailable",
      expected_projection_sha256: expectedProjectionSha256,
      read_candidate_qualified: false,
      decision_read_from_shadow: false,
    };
  }
}

function validateBootstrapTransaction(
  transaction: AuthorityStoreCommittedTransaction,
): string | null {
  if (transaction.cursor !== "1" || transaction.events.length !== 1) {
    return "shadow_qualification_bootstrap_shape_invalid";
  }
  const event = transaction.events[0]!;
  if (
    event.schema_version !== "loopx_coordination_runtime_shadow_bootstrap_event_v0" ||
    event.operation_id !== transaction.operation_id ||
    event.mode_declaration !== "legacy_canonical_shadow" ||
    event.source_projection_sha256 !== canonicalAuthoritySha256(transaction.projection) ||
    transaction.receipts.length !== 0
  ) {
    return "shadow_qualification_bootstrap_identity_invalid";
  }
  return null;
}

function validateMirroredTransaction(
  transaction: AuthorityStoreCommittedTransaction,
): { reason_code: string | null; event_kind: string | null } {
  if (transaction.events.length !== 1 || transaction.receipts.length !== 1) {
    return {
      reason_code: "shadow_qualification_transaction_shape_invalid",
      event_kind: null,
    };
  }
  const event = transaction.events[0]!;
  const receipt = transaction.receipts[0]!;
  const eventKind = typeof event.event_kind === "string" ? event.event_kind : null;
  if (
    event.schema_version !== "loopx_coordination_runtime_shadow_event_v0" ||
    receipt.schema_version !== COORDINATION_RUNTIME_SHADOW_RECEIPT_SCHEMA ||
    event.operation_id !== transaction.operation_id ||
    receipt.operation_id !== transaction.operation_id ||
    eventKind === null ||
    receipt.event_kind !== eventKind ||
    typeof event.source_version !== "string" ||
    receipt.source_version !== event.source_version ||
    typeof event.projection_sha256 !== "string" ||
    receipt.projection_sha256 !== event.projection_sha256 ||
    event.projection_sha256 !== canonicalAuthoritySha256(transaction.projection)
  ) {
    return {
      reason_code: "shadow_qualification_transaction_identity_invalid",
      event_kind: eventKind,
    };
  }
  return { reason_code: null, event_kind: eventKind };
}

async function scanShadowLineage(
  store: AuthorityStore,
): Promise<
  | { status: "loaded"; transactions: AuthorityStoreCommittedTransaction[] }
  | { status: "failed"; reason_code: string; reason: string }
> {
  const transactions: AuthorityStoreCommittedTransaction[] = [];
  let cursor: string | null = null;
  for (;;) {
    const page = await store.scanCommitted(cursor, 256);
    if (page.status !== "page") {
      return {
        status: "failed",
        reason_code: page.reason_code,
        reason: page.reason,
      };
    }
    transactions.push(...page.transactions.map((entry) => structuredClone(entry)));
    if (transactions.length > 10_000) {
      return {
        status: "failed",
        reason_code: "shadow_qualification_history_too_large",
        reason: "shadow qualification history exceeds the bounded 10000 transaction limit",
      };
    }
    if (!page.has_more) return { status: "loaded", transactions };
    if (page.next_cursor === null || page.next_cursor === cursor) {
      return {
        status: "failed",
        reason_code: "shadow_qualification_cursor_stalled",
        reason: "shadow qualification scan did not advance its cursor",
      };
    }
    cursor = page.next_cursor;
  }
}

/**
 * Produce promotion evidence across a lineage of distinct mirrored operations.
 * The policy is coverage-based rather than time-based: the caller selects a
 * minimum operation count and the mutation kinds that must have been observed.
 * This remains an evidence-only read and cannot promote or serve the shadow.
 */
export async function qualifyCoordinationRuntimeShadow(
  value: unknown,
  dependencies: RuntimeShadowDependencies = {},
): Promise<JsonObject> {
  let request: RuntimeShadowQualificationRequest;
  try {
    request = decodeQualificationRequest(value);
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_shadow_qualification_request",
      reason: error instanceof Error ? error.message : "invalid qualification request",
      qualified: false,
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }

  const directory = join(request.runtime_root, "authority-shadow", "file-v0");
  const store = dependencies.createStore?.(directory, request.goal_id) ??
    new FileAuthorityStore(directory, request.goal_id);
  const policy = {
    schema_version: "loopx_coordination_runtime_shadow_parity_policy_v0",
    minimum_operations: request.minimum_operations,
    required_event_kinds: request.required_event_kinds,
  };
  try {
    const head = await store.loadAuthority();
    if (head.status === "missing") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA,
        status: "missing",
        policy,
        qualified: false,
        bootstrap_required: true,
        primary_writeback_preserved: true,
        decision_read_from_shadow: false,
      };
    }
    if (head.status !== "loaded") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA,
        status: "failed",
        reason_code: head.reason_code,
        reason: head.reason,
        policy,
        qualified: false,
        primary_writeback_preserved: true,
        decision_read_from_shadow: false,
      };
    }
    const expectedProjectionSha256 = canonicalAuthoritySha256(request.projection);
    const observedProjectionSha256 = canonicalAuthoritySha256(head.head);
    const lineage = await scanShadowLineage(store);
    if (lineage.status === "failed") {
      return {
        schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA,
        status: "failed",
        reason_code: lineage.reason_code,
        reason: lineage.reason,
        policy,
        qualified: false,
        primary_writeback_preserved: true,
        decision_read_from_shadow: false,
      };
    }
    const bootstrap = lineage.transactions[0];
    const bootstrapFailure = bootstrap === undefined
      ? "shadow_qualification_bootstrap_missing"
      : validateBootstrapTransaction(bootstrap);
    const eventKinds = new Set<string>();
    let transactionFailure: string | null = bootstrapFailure;
    for (const transaction of lineage.transactions.slice(1)) {
      const validation = validateMirroredTransaction(transaction);
      if (validation.event_kind !== null) eventKinds.add(validation.event_kind);
      transactionFailure ??= validation.reason_code;
    }
    const observedEventKinds = [...eventKinds].sort();
    const missingRequiredEventKinds = request.required_event_kinds.filter(
      (eventKind) => !eventKinds.has(eventKind),
    );
    const operationCount = Math.max(0, lineage.transactions.length - 1);
    const currentHeadMatches = expectedProjectionSha256 === observedProjectionSha256;
    const enoughOperations = operationCount >= request.minimum_operations;
    const coverageComplete = missingRequiredEventKinds.length === 0;
    const qualified = currentHeadMatches && transactionFailure === null &&
      enoughOperations && coverageComplete;
    let status: "qualified" | "insufficient_evidence" | "drifted";
    if (!currentHeadMatches || transactionFailure !== null) status = "drifted";
    else status = qualified ? "qualified" : "insufficient_evidence";
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA,
      status,
      policy,
      qualified,
      parity_matches: currentHeadMatches,
      expected_projection_sha256: expectedProjectionSha256,
      observed_projection_sha256: observedProjectionSha256,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      evidence: {
        schema_version: "loopx_coordination_runtime_shadow_parity_evidence_v0",
        bootstrap_verified: bootstrapFailure === null,
        transaction_lineage_verified: transactionFailure === null,
        operation_count: operationCount,
        observed_event_kinds: observedEventKinds,
        missing_required_event_kinds: missingRequiredEventKinds,
        enough_operations: enoughOperations,
        coverage_complete: coverageComplete,
        ...(transactionFailure === null ? {} : { reason_code: transactionFailure }),
      },
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  } catch (error) {
    return {
      schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_RESULT_SCHEMA,
      status: "failed",
      reason_code: "shadow_qualification_unavailable",
      reason: error instanceof Error ? error.message : "qualification unavailable",
      policy,
      qualified: false,
      primary_writeback_preserved: true,
      decision_read_from_shadow: false,
    };
  }
}

/**
 * Mirror one already-committed legacy coordination mutation into the Stage 2C
 * file shadow. The result is evidence only: it never authorizes, rejects, or
 * rolls back the primary mutation and no runtime decision reads this store.
 */
export async function commitCoordinationRuntimeShadow(
  value: unknown,
  dependencies: RuntimeShadowDependencies = {},
): Promise<JsonObject> {
  let request: RuntimeShadowRequest;
  try {
    request = decodeRequest(value);
  } catch (error) {
    return failed(
      "invalid_shadow_request",
      error instanceof Error ? error.message : "invalid shadow request",
    );
  }

  const directory = join(
    request.runtime_root,
    "authority-shadow",
    "file-v0",
  );
  const store = dependencies.createStore?.(directory, request.goal_id) ??
    new FileAuthorityStore(directory, request.goal_id);
  const receipt = expectedReceipt(request);

  try {
    const existing = await store.readReceipt(request.operation_id);
    if (existing.status === "found") {
      return receiptResult(request, existing, receipt, "replayed");
    }
    if (existing.status !== "missing") {
      return failed(existing.reason_code, existing.reason, {
        operation_id: request.operation_id,
      });
    }

    for (let attempt = 0; attempt < 2; attempt += 1) {
      const head = await store.loadAuthority();
      if (head.status !== "loaded" && head.status !== "missing") {
        return failed(head.reason_code, head.reason, {
          operation_id: request.operation_id,
        });
      }
      const result = await store.commitAuthority({
        expected_provider_revision: head.status === "loaded"
          ? head.provider_revision
          : null,
        operation_id: request.operation_id,
        events: [{
          schema_version: "loopx_coordination_runtime_shadow_event_v0",
          operation_id: request.operation_id,
          event_kind: request.event_kind,
          source_version: request.source_version,
          projection_sha256: receipt.projection_sha256,
        }],
        next_projection: request.projection,
        receipts: [receipt],
      });
      if (result.status === "applied") {
        const readback = await store.readReceipt(request.operation_id);
        if (!receiptMatches(readback, receipt) || readback.status !== "found") {
          return failed(
            "shadow_commit_readback_mismatch",
            "shadow commit did not produce its exact durable receipt",
            { operation_id: request.operation_id },
          );
        }
        const projectionReadback = await verifyAppliedProjection(
          store,
          request,
          readback.provider_revision,
        );
        if (projectionReadback.status === "projection_mismatch") {
          return failed(
            "shadow_commit_projection_mismatch",
            "shadow commit receipt exists but current projection differs",
            {
              operation_id: request.operation_id,
              provider_revision: readback.provider_revision,
            },
          );
        }
        return {
          schema_version: COORDINATION_RUNTIME_SHADOW_RESULT_SCHEMA,
          status: "applied",
          operation_id: request.operation_id,
          cursor: readback.cursor,
          provider_revision: readback.provider_revision,
          parity: {
            schema_version: "loopx_coordination_runtime_shadow_parity_v0",
            receipt_matches: true,
            projection_sha256: receipt.projection_sha256,
            projection_readback: projectionReadback,
          },
          primary_writeback_preserved: true,
          decision_read_from_shadow: false,
        };
      }
      if (result.status === "ambiguous") {
        const readback = await store.readReceipt(request.operation_id);
        if (readback.status === "found") {
          return receiptResult(request, readback, receipt, "recovered");
        }
        return {
          schema_version: COORDINATION_RUNTIME_SHADOW_RESULT_SCHEMA,
          status: "ambiguous",
          operation_id: request.operation_id,
          reason_code: result.reason_code,
          reason: result.reason,
          reconciliation_required: true,
          primary_writeback_preserved: true,
          decision_read_from_shadow: false,
        };
      }
      if (
        result.status === "conflict" &&
        result.conflict_kind === "operation_id_exists"
      ) {
        return receiptResult(
          request,
          await store.readReceipt(request.operation_id),
          receipt,
          "replayed",
        );
      }
      if (
        result.status === "conflict" &&
        result.conflict_kind === "provider_revision_mismatch" &&
        attempt === 0
      ) {
        continue;
      }
      if (result.status === "conflict") {
        return failed("shadow_provider_conflict", result.conflict_kind, {
          operation_id: request.operation_id,
          current_provider_revision: result.current_provider_revision,
          current_cursor: result.current_cursor,
        });
      }
      return failed(result.reason_code, result.reason, {
        operation_id: request.operation_id,
      });
    }
    return failed(
      "shadow_provider_conflict",
      "shadow provider revision changed during bounded retry",
      { operation_id: request.operation_id },
    );
  } catch (error) {
    return failed(
      "shadow_write_unavailable",
      error instanceof Error ? error.message : "shadow write unavailable",
      { operation_id: request.operation_id },
    );
  }
}

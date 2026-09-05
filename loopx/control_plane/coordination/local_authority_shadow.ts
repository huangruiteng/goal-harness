import { createHash } from "node:crypto";
import { join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  requireInteger,
  requireJsonObject,
  requireNonEmptyString,
  requireStringLiteral,
} from "../runtime_decode.ts";
import type {
  AuthorityStore,
  AuthorityStoreCommitResult,
  AuthorityStoreCommittedTransaction,
  AuthorityStoreLoadResult,
  AuthorityStoreReceiptResult,
} from "./authority_store.ts";
import { authorityUnicodeCompare, canonicalAuthorityBytes } from "./authority_store_codec.ts";
import {
  TODO_CANONICAL_READ_RECORD_FIELDS,
} from "./coordination_projection.ts";
import { FileAuthorityStore } from "./file_authority_store.ts";
import {
  LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_EVENT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OBSERVATION_RECEIPT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_TRANSACTION_PROJECTION_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_TRANSACTION_RECEIPT_SCHEMA,
} from "./coordination_state_contract.generated.ts";

export {
  LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OBSERVATION_RECEIPT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA,
};

const REQUEST_FIELDS = new Set([
  "schema_version",
  "mode",
  "runtime_root",
  "goal_id",
  "observation_id",
  "observation_trigger",
  "source_digest",
  "source_projection",
]);
export type LocalAuthorityShadowOutcome =
  | "captured"
  | "replayed"
  | "ambiguous_reconciled"
  | "ambiguous_unproved"
  | "unavailable"
  | "failed"
  | "protocol_mismatch"
  | "conflict_retry_required";

export interface LocalAuthorityShadowEvidence extends JsonObject {
  schema_version: typeof LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA;
  outcome: LocalAuthorityShadowOutcome;
  reason_code: string | null;
  goal_id: string;
  observation_id: string;
  source_digest: string;
  capture_kind: "post_commit_snapshot";
  source_transaction_correlated: false;
  durable_source_outbox: false;
  source_candidate_compared: false;
  parity_verdict: "not_evaluated";
  primary_authority: "legacy_local";
  candidate_provider: "file";
  candidate_read_for_decision: false;
  provider_to_local_writes: false;
  primary_writeback_preserved: true;
  store_identity: string | null;
  provider_revision: string | null;
  cursor: string | null;
}

interface LocalAuthorityShadowRequest {
  mode: "file_one_way";
  runtime_root: string;
  goal_id: string;
  observation_id: string;
  observation_trigger: string;
  source_digest: string;
  source_projection: JsonObject;
}

export interface LocalAuthorityShadowDependencies {
  openStore?: (directory: string, goalId: string) => AuthorityStore;
}

function decodeRequest(value: unknown): LocalAuthorityShadowRequest {
  const request = requireJsonObject(value, "local authority shadow request");
  const unexpected = Object.keys(request).filter((field) => !REQUEST_FIELDS.has(field));
  if (unexpected.length > 0) {
    const listed = [...unexpected].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
    throw new EffectRuntimeRequestError(
      `Local authority shadow request has unsupported fields: ${listed.join(", ")}`,
    );
  }
  if (request.schema_version !== LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA) {
    throw new EffectRuntimeRequestError("Local authority shadow request schema mismatch");
  }
  if (request.mode !== "file_one_way") {
    throw new EffectRuntimeRequestError("Local authority shadow mode must be file_one_way");
  }
  const goalId = requireNonEmptyString(request.goal_id, "goal_id");
  if (goalId === "." || goalId === ".." || goalId.includes("/") || goalId.includes("\\")) {
    throw new EffectRuntimeRequestError(
      "Local authority shadow goal id must be a single path segment",
    );
  }
  const projection = requireJsonObject(request.source_projection, "source_projection");
  if (
    projection.schema_version !== LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA ||
    projection.goal_id !== goalId
  ) {
    throw new EffectRuntimeRequestError(
      "Local authority shadow projection schema or goal identity mismatch",
    );
  }
  const sourceDigest = requireNonEmptyString(request.source_digest, "source_digest");
  if (!/^sha256:[a-f0-9]{64}$/u.test(sourceDigest)) {
    throw new EffectRuntimeRequestError("source_digest must be sha256:<64 lowercase hex>");
  }
  return {
    mode: "file_one_way",
    runtime_root: requireNonEmptyString(request.runtime_root, "runtime_root"),
    goal_id: goalId,
    observation_id: requireNonEmptyString(request.observation_id, "observation_id"),
    observation_trigger: requireNonEmptyString(
      request.observation_trigger,
      "observation_trigger",
    ),
    source_digest: sourceDigest,
    source_projection: structuredClone(projection),
  };
}

function evidence(
  request: LocalAuthorityShadowRequest,
  outcome: LocalAuthorityShadowOutcome,
  options: {
    reasonCode?: string | null;
    storeIdentity?: string | null;
    providerRevision?: string | null;
    cursor?: string | null;
  } = {},
): LocalAuthorityShadowEvidence {
  return {
    schema_version: LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA,
    outcome,
    reason_code: options.reasonCode ?? null,
    goal_id: request.goal_id,
    observation_id: request.observation_id,
    source_digest: request.source_digest,
    capture_kind: "post_commit_snapshot",
    source_transaction_correlated: false,
    durable_source_outbox: false,
    source_candidate_compared: false,
    parity_verdict: "not_evaluated",
    primary_authority: "legacy_local",
    candidate_provider: "file",
    candidate_read_for_decision: false,
    provider_to_local_writes: false,
    primary_writeback_preserved: true,
    store_identity: options.storeIdentity ?? null,
    provider_revision: options.providerRevision ?? null,
    cursor: options.cursor ?? null,
  };
}

function readFailureEvidence(
  request: LocalAuthorityShadowRequest,
  result: Extract<AuthorityStoreLoadResult, { status: "unavailable" | "failed" }>,
  storeIdentity: string | null,
): LocalAuthorityShadowEvidence {
  return evidence(request, result.status, {
    reasonCode: result.reason_code,
    storeIdentity,
  });
}

function receiptMatches(
  request: LocalAuthorityShadowRequest,
  result: Extract<AuthorityStoreReceiptResult, { status: "found" }>,
): boolean {
  return result.receipts.some((raw) => {
    const receipt = raw as Record<string, unknown>;
    return receipt.schema_version === LOCAL_AUTHORITY_SHADOW_OBSERVATION_RECEIPT_SCHEMA &&
      receipt.observation_id === request.observation_id &&
      receipt.source_digest === request.source_digest &&
      receipt.primary_authority === "legacy_local" &&
      receipt.provider_to_local_writes === false;
  });
}

async function reconcileReceipt(
  store: AuthorityStore,
  request: LocalAuthorityShadowRequest,
  storeIdentity: string,
  reconciledOutcome: "replayed" | "ambiguous_reconciled",
): Promise<LocalAuthorityShadowEvidence> {
  const result = await store.readReceipt(request.observation_id);
  if (result.status === "found" && receiptMatches(request, result)) {
    return evidence(request, reconciledOutcome, {
      storeIdentity,
      providerRevision: result.provider_revision,
      cursor: result.cursor,
    });
  }
  if (result.status === "unavailable") {
    return evidence(request, "unavailable", {
      reasonCode: result.reason_code,
      storeIdentity,
    });
  }
  if (result.status === "failed") {
    return evidence(request, "failed", {
      reasonCode: result.reason_code,
      storeIdentity,
    });
  }
  return evidence(
    request,
    reconciledOutcome === "ambiguous_reconciled"
      ? "ambiguous_unproved"
      : "protocol_mismatch",
    {
      reasonCode: result.status === "missing"
        ? "observation_receipt_missing"
        : "observation_receipt_mismatch",
      storeIdentity,
    },
  );
}

/**
 * Record a post-commit observation in a candidate AuthorityStore.
 *
 * The legacy local writers remain the only decision authority. This function
 * receives a completed source projection and has no route back to those files.
 */
export async function recordLocalAuthorityShadow(
  value: unknown,
  dependencies: LocalAuthorityShadowDependencies = {},
): Promise<LocalAuthorityShadowEvidence> {
  const request = decodeRequest(value);
  let store: AuthorityStore;
  try {
    const providerDirectory = join(
      request.runtime_root,
      "authority-shadow",
      "file",
      request.goal_id,
    );
    store = (dependencies.openStore ?? ((directory, goalId) =>
      new FileAuthorityStore(directory, goalId)))(
        providerDirectory,
        request.goal_id,
      );
  } catch {
    return evidence(request, "unavailable", {
      reasonCode: "provider_construction_failed",
    });
  }

  try {
    const identity = await store.storeIdentity();
    if (identity.status !== "available") {
      return evidence(request, identity.status, { reasonCode: identity.reason_code });
    }
    const storeIdentity = identity.store_identity;
    const receipt = {
      schema_version: LOCAL_AUTHORITY_SHADOW_OBSERVATION_RECEIPT_SCHEMA,
      observation_id: request.observation_id,
      source_digest: request.source_digest,
      observation_trigger: request.observation_trigger,
      source_transaction_correlated: false,
      parity_verdict: "not_evaluated",
      primary_authority: "legacy_local",
      candidate_read_for_decision: false,
      provider_to_local_writes: false,
    };
    const event = {
      schema_version: "loopx_local_authority_shadow_event_v0",
      kind: "post_commit_snapshot_captured",
      observation_id: request.observation_id,
      observation_trigger: request.observation_trigger,
      source_digest: request.source_digest,
    };

    const loaded = await store.loadAuthority();
    if (loaded.status === "unavailable" || loaded.status === "failed") {
      return readFailureEvidence(request, loaded, storeIdentity);
    }
    const committed = await store.commitAuthority({
      expected_provider_revision:
        loaded.status === "loaded" ? loaded.provider_revision : null,
      operation_id: request.observation_id,
      events: [event],
      next_projection: request.source_projection,
      receipts: [receipt],
    });
    if (committed.status === "applied") {
      return evidence(request, "captured", {
        storeIdentity,
        providerRevision: committed.provider_revision,
        cursor: committed.cursor,
      });
    }
    if (committed.status === "ambiguous") {
      return await reconcileReceipt(
        store,
        request,
        storeIdentity,
        "ambiguous_reconciled",
      );
    }
    if (committed.status === "failed") {
      return evidence(request, "failed", {
        reasonCode: committed.reason_code,
        storeIdentity,
      });
    }
    if (committed.conflict_kind === "operation_id_exists") {
      return await reconcileReceipt(store, request, storeIdentity, "replayed");
    }
    return evidence(request, "conflict_retry_required", {
      reasonCode: "provider_revision_mismatch",
      storeIdentity,
      providerRevision: committed.current_provider_revision,
      cursor: committed.current_cursor,
    });
  } catch {
    return evidence(request, "unavailable", {
      reasonCode: "provider_call_failed",
    });
  }
}

// ---------------------------------------------------------------------------
// Transaction-bound entries (Stage 2C second half).
//
// A drained outbox entry becomes exactly one candidate transaction whose
// operation_id is the entry id, so a receipt names the primary transaction it
// records instead of a post-commit snapshot that may include other writers.
// ---------------------------------------------------------------------------

export const LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V1 =
  LOCAL_AUTHORITY_SHADOW_TRANSACTION_PROJECTION_SCHEMA;
export { LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA };
export { LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA };
export { LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA };
export { LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA };
export const LOCAL_AUTHORITY_SHADOW_EVENT_SCHEMA_V1 = LOCAL_AUTHORITY_SHADOW_EVENT_SCHEMA;
export { LOCAL_AUTHORITY_SHADOW_TRANSACTION_RECEIPT_SCHEMA };

const SHADOW_PARTITIONS = ["todos", "leases"] as const;
const ENTRY_RESOLUTIONS = [
  "committed",
  "committed_proven_by_readback",
  "abandoned",
  "unproved",
  "seed",
] as const;
const NO_OP_RESOLUTIONS = new Set<string>(["abandoned", "unproved"]);
const SOURCE_KINDS = ["markdown_active_state", "state_event_log", "task_lease_record"] as const;
const WRITER_RUNTIMES = ["python", "typescript"] as const;
const COMMIT_ENTRY_REQUEST_FIELDS = new Set([
  "schema_version",
  "runtime_root",
  "goal_id",
  "entry",
  "partition_projection",
  "partition_digest",
]);
const ENTRY_FIELDS = new Set([
  "entry_id",
  "partition",
  "seq",
  "writer",
  "source",
  "source_root_digest",
  "prepared_at",
  "committed_at",
  "resolution",
]);
const READ_REQUEST_FIELDS = new Set([
  "schema_version",
  "runtime_root",
  "goal_id",
  "store_kind",
  "scan_after_cursor",
  "scan_limit",
]);
const ENTRY_ID_PATTERN = /^local-shadow-tx-[0-9a-f]{64}$/u;
const DIGEST_PATTERN = /^sha256:[a-f0-9]{64}$/u;
const MAX_SCAN_LIMIT = 1000;
const REVISION_RETRY_ATTEMPTS = 3;

export type ShadowPartition = (typeof SHADOW_PARTITIONS)[number];
export type ShadowEntryResolution = (typeof ENTRY_RESOLUTIONS)[number];
export type LocalAuthorityShadowCommitEntryOutcome =
  | "delivered"
  | "replayed"
  | "ambiguous_reconciled"
  | "ambiguous_unproved"
  | "unavailable"
  | "failed"
  | "protocol_mismatch"
  | "conflict_retry_required";

interface ShadowEntryWriter {
  runtime: (typeof WRITER_RUNTIMES)[number];
  write_class: string;
  operation_id: string | null;
}

interface ShadowEntrySource {
  kind: (typeof SOURCE_KINDS)[number];
  previous_bytes_digest: string | null;
  bytes_digest: string | null;
  lease: JsonObject | null;
  event_id: string | null;
}

interface ShadowEntry {
  entry_id: string;
  partition: ShadowPartition;
  seq: number;
  writer: ShadowEntryWriter;
  source: ShadowEntrySource;
  source_root_digest: string;
  prepared_at: string;
  committed_at: string | null;
  resolution: ShadowEntryResolution;
}

interface CommitEntryRequest {
  runtime_root: string;
  goal_id: string;
  entry: ShadowEntry;
  partition_projection: JsonObject | null;
  partition_digest: string | null;
}

export interface LocalAuthorityShadowCommitEntryResult extends JsonObject {
  schema_version: typeof LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA;
  outcome: LocalAuthorityShadowCommitEntryOutcome;
  reason_code: string | null;
  goal_id: string;
  entry_id: string;
  partition: ShadowPartition;
  seq: number;
  no_op: boolean;
  store_identity: string | null;
  provider_revision: string | null;
  cursor: string | null;
  head_digest: string | null;
}

interface ReadRequest {
  runtime_root: string;
  goal_id: string;
  store_kind: "runtime_shadow" | "legacy_observation";
  scan_after_cursor: string | null;
  scan_limit: number;
}

function requireGoalId(value: unknown): string {
  const goalId = requireNonEmptyString(value, "goal_id");
  if (goalId === "." || goalId === ".." || goalId.includes("/") || goalId.includes("\\")) {
    throw new EffectRuntimeRequestError(
      "Local authority shadow goal id must be a single path segment",
    );
  }
  return goalId;
}

function rejectUnexpectedFields(
  record: JsonObject,
  allowed: Set<string>,
  label: string,
): void {
  const unexpected = Object.keys(record).filter((field) => !allowed.has(field));
  if (unexpected.length > 0) {
    unexpected.sort(authorityUnicodeCompare);
    throw new EffectRuntimeRequestError(
      `${label} has unsupported fields: ${unexpected.join(", ")}`,
    );
  }
}

function optionalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return requireNonEmptyString(value, label);
}

function optionalDigest(value: unknown, label: string): string | null {
  const digest = optionalString(value, label);
  if (digest !== null && !DIGEST_PATTERN.test(digest)) {
    throw new EffectRuntimeRequestError(`${label} must be sha256:<64 lowercase hex>`);
  }
  return digest;
}

function decodeEntry(value: unknown): ShadowEntry {
  const raw = requireJsonObject(value, "entry");
  rejectUnexpectedFields(raw, ENTRY_FIELDS, "Local authority shadow entry");
  const entryId = requireNonEmptyString(raw.entry_id, "entry.entry_id");
  if (!ENTRY_ID_PATTERN.test(entryId)) {
    throw new EffectRuntimeRequestError("entry.entry_id must be local-shadow-tx-<64 lowercase hex>");
  }
  const seq = requireInteger(raw.seq, "entry.seq");
  if (seq < 1) {
    throw new EffectRuntimeRequestError("entry.seq must be a positive integer");
  }
  const writer = requireJsonObject(raw.writer, "entry.writer");
  const source = requireJsonObject(raw.source, "entry.source");
  const lease = source.lease === null || source.lease === undefined
    ? null
    : requireJsonObject(source.lease, "entry.source.lease");
  return {
    entry_id: entryId,
    partition: requireStringLiteral(raw.partition, SHADOW_PARTITIONS, "entry.partition"),
    seq,
    writer: {
      runtime: requireStringLiteral(writer.runtime, WRITER_RUNTIMES, "entry.writer.runtime"),
      write_class: requireNonEmptyString(writer.write_class, "entry.writer.write_class"),
      operation_id: optionalString(writer.operation_id, "entry.writer.operation_id"),
    },
    source: {
      kind: requireStringLiteral(source.kind, SOURCE_KINDS, "entry.source.kind"),
      previous_bytes_digest: optionalDigest(
        source.previous_bytes_digest,
        "entry.source.previous_bytes_digest",
      ),
      bytes_digest: optionalDigest(source.bytes_digest, "entry.source.bytes_digest"),
      lease: lease === null ? null : structuredClone(lease),
      event_id: optionalString(source.event_id, "entry.source.event_id"),
    },
    source_root_digest: requireNonEmptyString(raw.source_root_digest, "entry.source_root_digest"),
    prepared_at: requireNonEmptyString(raw.prepared_at, "entry.prepared_at"),
    committed_at: optionalString(raw.committed_at, "entry.committed_at"),
    resolution: requireStringLiteral(raw.resolution, ENTRY_RESOLUTIONS, "entry.resolution"),
  };
}

function decodePartitionProjection(
  value: unknown,
  partition: ShadowPartition,
): JsonObject | null {
  if (value === null || value === undefined) return null;
  const projection = requireJsonObject(value, "partition_projection");
  if (partition === "todos") {
    if (
      Object.keys(projection).length !== 2 ||
      typeof projection.handoff_mode !== "string" ||
      !Array.isArray(projection.todos)
    ) {
      throw new EffectRuntimeRequestError(
        "todos partition projection must be exactly {handoff_mode, todos[]}",
      );
    }
  } else if (Object.keys(projection).length !== 1 || !Array.isArray(projection.leases)) {
    throw new EffectRuntimeRequestError("leases partition projection must be exactly {leases[]}");
  }
  return structuredClone(projection);
}

function decodeCommitEntryRequest(value: unknown): CommitEntryRequest {
  const request = requireJsonObject(value, "local authority shadow commit entry request");
  rejectUnexpectedFields(
    request,
    COMMIT_ENTRY_REQUEST_FIELDS,
    "Local authority shadow commit entry request",
  );
  if (request.schema_version !== LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA) {
    throw new EffectRuntimeRequestError(
      "Local authority shadow commit entry request schema mismatch",
    );
  }
  const entry = decodeEntry(request.entry);
  const projection = decodePartitionProjection(request.partition_projection, entry.partition);
  const digest = optionalDigest(request.partition_digest, "partition_digest");
  const noOp = NO_OP_RESOLUTIONS.has(entry.resolution);
  if (noOp && (projection !== null || digest !== null)) {
    throw new EffectRuntimeRequestError(
      `entry resolution ${entry.resolution} must not carry a partition projection`,
    );
  }
  if (!noOp && (projection === null || digest === null)) {
    throw new EffectRuntimeRequestError(
      `entry resolution ${entry.resolution} requires partition_projection and partition_digest`,
    );
  }
  return {
    runtime_root: requireNonEmptyString(request.runtime_root, "runtime_root"),
    goal_id: requireGoalId(request.goal_id),
    entry,
    partition_projection: projection,
    partition_digest: digest,
  };
}

function decodeReadRequest(value: unknown): ReadRequest {
  const request = requireJsonObject(value, "local authority shadow read request");
  rejectUnexpectedFields(request, READ_REQUEST_FIELDS, "Local authority shadow read request");
  if (request.schema_version !== LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA) {
    throw new EffectRuntimeRequestError("Local authority shadow read request schema mismatch");
  }
  const limit = request.scan_limit === undefined ? 0 : requireInteger(request.scan_limit, "scan_limit");
  if (limit < 0 || limit > MAX_SCAN_LIMIT) {
    throw new EffectRuntimeRequestError(`scan_limit must be between 0 and ${MAX_SCAN_LIMIT}`);
  }
  return {
    runtime_root: requireNonEmptyString(request.runtime_root, "runtime_root"),
    goal_id: requireGoalId(request.goal_id),
    store_kind: request.store_kind === undefined || request.store_kind === "runtime_shadow"
      ? "runtime_shadow"
      : request.store_kind === "legacy_observation"
        ? "legacy_observation"
        : (() => {
            throw new EffectRuntimeRequestError(
              "Local authority shadow read store_kind must be runtime_shadow or legacy_observation",
            );
          })(),
    scan_after_cursor: optionalString(request.scan_after_cursor, "scan_after_cursor"),
    scan_limit: limit,
  };
}

/** Digest of the fields parity compares; must match Python `head_digest`. */
export function localAuthorityShadowHeadDigest(head: JsonObject): string {
  const view = {
    handoff_mode: head.handoff_mode ?? null,
    todos: head.todos ?? null,
    leases: head.leases ?? null,
  };
  return `sha256:${createHash("sha256").update(canonicalAuthorityBytes(view)).digest("hex")}`;
}

function partitionsOf(head: JsonObject | null): JsonObject {
  const raw = head?.partitions;
  const partitions: JsonObject = { todos: null, leases: null };
  if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
    for (const partition of SHADOW_PARTITIONS) {
      const marker = (raw as JsonObject)[partition];
      if (marker !== null && typeof marker === "object" && !Array.isArray(marker)) {
        partitions[partition] = structuredClone(marker);
      }
    }
  }
  return partitions;
}

function todoReadModel(todos: readonly JsonObject[]): JsonObject {
  return {
    schema_version: "loopx_todo_canonical_read_record_v0",
    todo_count: todos.length,
    records_sha256: createHash("sha256").update(canonicalAuthorityBytes(todos)).digest("hex"),
    contract_fields: [...TODO_CANONICAL_READ_RECORD_FIELDS],
  };
}

/**
 * Fold one partition into the candidate head. A v0 head (whole-snapshot
 * observation) is accepted as the starting point with no partition markers.
 */
export function composeLocalAuthorityShadowHead(
  current: JsonObject | null,
  goalId: string,
  entry: { partition: ShadowPartition; seq: number },
  projection: JsonObject | null,
  digest: string | null,
): JsonObject {
  const base = current ?? {};
  let handoffMode: string | null = typeof base.handoff_mode === "string" ? base.handoff_mode : null;
  let todos = Array.isArray(base.todos) ? structuredClone(base.todos) : [];
  let leases = Array.isArray(base.leases) ? structuredClone(base.leases) : [];
  const partitions = partitionsOf(current);
  if (projection !== null) {
    if (entry.partition === "todos") {
      handoffMode = String(projection.handoff_mode);
      todos = structuredClone(projection.todos as JsonObject[]);
    } else {
      leases = structuredClone(projection.leases as JsonObject[]);
    }
    partitions[entry.partition] = { seq: entry.seq, partition_digest: digest };
  }
  const next = {
    schema_version: LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V1,
    goal_id: goalId,
    source_authority: "legacy_markdown_and_task_lease",
    handoff_mode: handoffMode,
    todos,
    leases,
    todo_read_model: todoReadModel(todos),
    partitions,
  };
  return next;
}

function transactionReceipt(request: CommitEntryRequest, noOp: boolean): JsonObject {
  const { entry } = request;
  return {
    schema_version: LOCAL_AUTHORITY_SHADOW_TRANSACTION_RECEIPT_SCHEMA,
    entry_id: entry.entry_id,
    partition: entry.partition,
    seq: entry.seq,
    write_class: entry.writer.write_class,
    writer_runtime: entry.writer.runtime,
    writer_operation_id: entry.writer.operation_id,
    source_kind: entry.source.kind,
    source_bytes_digest: entry.source.bytes_digest,
    source_previous_bytes_digest: entry.source.previous_bytes_digest,
    source_event_id: entry.source.event_id,
    source_lease: entry.source.lease,
    source_root_digest: entry.source_root_digest,
    partition_digest: request.partition_digest,
    resolution: entry.resolution,
    no_op: noOp,
    prepared_at: entry.prepared_at,
    committed_at: entry.committed_at,
    drained_at: new Date().toISOString(),
    source_transaction_correlated: true,
    durable_source_outbox: true,
    parity_verdict: "not_evaluated",
    primary_authority: "legacy_local",
    candidate_read_for_decision: false,
    provider_to_local_writes: false,
  };
}

function transactionEvent(request: CommitEntryRequest, noOp: boolean): JsonObject {
  const { entry } = request;
  let kind = "source_transaction_delivered";
  if (entry.resolution === "seed") kind = "partition_seeded";
  else if (entry.resolution === "abandoned") kind = "source_transaction_abandoned";
  else if (entry.resolution === "unproved") kind = "source_transaction_unproved";
  return {
    schema_version: LOCAL_AUTHORITY_SHADOW_EVENT_SCHEMA_V1,
    kind,
    partition: entry.partition,
    seq: entry.seq,
    entry_id: entry.entry_id,
    write_class: entry.writer.write_class,
    partition_digest: request.partition_digest,
    no_op: noOp,
  };
}

function commitEntryResult(
  request: CommitEntryRequest,
  outcome: LocalAuthorityShadowCommitEntryOutcome,
  options: {
    reasonCode?: string | null;
    storeIdentity?: string | null;
    providerRevision?: string | null;
    cursor?: string | null;
    headDigest?: string | null;
  } = {},
): LocalAuthorityShadowCommitEntryResult {
  return {
    schema_version: LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA,
    outcome,
    reason_code: options.reasonCode ?? null,
    goal_id: request.goal_id,
    entry_id: request.entry.entry_id,
    partition: request.entry.partition,
    seq: request.entry.seq,
    no_op: NO_OP_RESOLUTIONS.has(request.entry.resolution),
    store_identity: options.storeIdentity ?? null,
    provider_revision: options.providerRevision ?? null,
    cursor: options.cursor ?? null,
    head_digest: options.headDigest ?? null,
  };
}

function transactionReceiptMatches(
  request: CommitEntryRequest,
  result: Extract<AuthorityStoreReceiptResult, { status: "found" }>,
): boolean {
  return result.receipts.some((raw) => {
    const receipt = raw as Record<string, unknown>;
    return receipt.schema_version === LOCAL_AUTHORITY_SHADOW_TRANSACTION_RECEIPT_SCHEMA &&
      receipt.entry_id === request.entry.entry_id &&
      receipt.partition === request.entry.partition &&
      receipt.seq === request.entry.seq &&
      (receipt.partition_digest ?? null) === request.partition_digest &&
      receipt.primary_authority === "legacy_local" &&
      receipt.provider_to_local_writes === false;
  });
}

async function reconcileTransactionReceipt(
  store: AuthorityStore,
  request: CommitEntryRequest,
  storeIdentity: string,
  reconciledOutcome: "replayed" | "ambiguous_reconciled",
): Promise<LocalAuthorityShadowCommitEntryResult> {
  const result = await store.readReceipt(request.entry.entry_id);
  if (result.status === "found" && transactionReceiptMatches(request, result)) {
    return commitEntryResult(request, reconciledOutcome, {
      storeIdentity,
      providerRevision: result.provider_revision,
      cursor: result.cursor,
    });
  }
  if (result.status === "unavailable" || result.status === "failed") {
    return commitEntryResult(request, result.status, {
      reasonCode: result.reason_code,
      storeIdentity,
    });
  }
  return commitEntryResult(
    request,
    reconciledOutcome === "ambiguous_reconciled" ? "ambiguous_unproved" : "protocol_mismatch",
    {
      reasonCode: result.status === "missing"
        ? "transaction_receipt_missing"
        : "transaction_receipt_mismatch",
      storeIdentity,
    },
  );
}

function openShadowStore(
  runtimeRoot: string,
  goalId: string,
  storeKind: ReadRequest["store_kind"],
  dependencies: LocalAuthorityShadowDependencies,
): AuthorityStore {
  const providerDirectory = storeKind === "legacy_observation"
    ? join(runtimeRoot, "authority-shadow", "file", goalId)
    : join(runtimeRoot, "authority-shadow", "file-v0");
  return (dependencies.openStore ?? ((directory, id) => new FileAuthorityStore(directory, id)))(
    providerDirectory,
    goalId,
  );
}

type CommitAttempt =
  | { kind: "final"; result: LocalAuthorityShadowCommitEntryResult }
  | { kind: "retry"; result: LocalAuthorityShadowCommitEntryResult };

async function settleCommitOutcome(
  store: AuthorityStore,
  request: CommitEntryRequest,
  storeIdentity: string,
  committed: AuthorityStoreCommitResult,
  headDigest: string,
): Promise<CommitAttempt> {
  if (committed.status === "applied") {
    return {
      kind: "final",
      result: commitEntryResult(request, "delivered", {
        storeIdentity,
        providerRevision: committed.provider_revision,
        cursor: committed.cursor,
        headDigest,
      }),
    };
  }
  if (committed.status === "ambiguous") {
    return {
      kind: "final",
      result: await reconcileTransactionReceipt(store, request, storeIdentity, "ambiguous_reconciled"),
    };
  }
  if (committed.status === "failed") {
    return {
      kind: "final",
      result: commitEntryResult(request, "failed", {
        reasonCode: committed.reason_code,
        storeIdentity,
      }),
    };
  }
  if (committed.conflict_kind === "operation_id_exists") {
    return {
      kind: "final",
      result: await reconcileTransactionReceipt(store, request, storeIdentity, "replayed"),
    };
  }
  return {
    kind: "retry",
    result: commitEntryResult(request, "conflict_retry_required", {
      reasonCode: "provider_revision_mismatch",
      storeIdentity,
      providerRevision: committed.current_provider_revision,
      cursor: committed.current_cursor,
    }),
  };
}

/** One load-compose-commit attempt against the current provider revision. */
async function attemptCommitEntry(
  store: AuthorityStore,
  request: CommitEntryRequest,
  storeIdentity: string,
  noOp: boolean,
): Promise<CommitAttempt> {
  const loaded = await store.loadAuthority();
  if (loaded.status === "unavailable" || loaded.status === "failed") {
    return {
      kind: "final",
      result: commitEntryResult(request, loaded.status, {
        reasonCode: loaded.reason_code,
        storeIdentity,
      }),
    };
  }
  const nextHead = composeLocalAuthorityShadowHead(
    loaded.status === "loaded" ? loaded.head : null,
    request.goal_id,
    request.entry,
    request.partition_projection,
    request.partition_digest,
  );
  const committed = await store.commitAuthority({
    expected_provider_revision: loaded.status === "loaded" ? loaded.provider_revision : null,
    operation_id: request.entry.entry_id,
    events: [transactionEvent(request, noOp)],
    next_projection: nextHead,
    receipts: [transactionReceipt(request, noOp)],
  });
  return await settleCommitOutcome(
    store,
    request,
    storeIdentity,
    committed,
    localAuthorityShadowHeadDigest(nextHead),
  );
}

/**
 * Commit one drained outbox entry as exactly one candidate transaction.
 *
 * `operation_id` is the entry id, so a retry after a lost response replays
 * onto the same transaction instead of recording the source write twice.
 * No-op resolutions (abandoned / unproved) keep the sequence chain auditable
 * without changing the compared head fields.
 */
export async function commitLocalAuthorityShadowEntry(
  value: unknown,
  dependencies: LocalAuthorityShadowDependencies = {},
): Promise<LocalAuthorityShadowCommitEntryResult> {
  const request = decodeCommitEntryRequest(value);
  const noOp = NO_OP_RESOLUTIONS.has(request.entry.resolution);
  let store: AuthorityStore;
  try {
    store = openShadowStore(
      request.runtime_root,
      request.goal_id,
      "runtime_shadow",
      dependencies,
    );
  } catch {
    return commitEntryResult(request, "unavailable", {
      reasonCode: "provider_construction_failed",
    });
  }
  try {
    const identity = await store.storeIdentity();
    if (identity.status !== "available") {
      return commitEntryResult(request, identity.status, { reasonCode: identity.reason_code });
    }
    let attempt: CommitAttempt | null = null;
    for (let index = 0; index < REVISION_RETRY_ATTEMPTS; index += 1) {
      attempt = await attemptCommitEntry(store, request, identity.store_identity, noOp);
      if (attempt.kind === "final") return attempt.result;
    }
    return (attempt as CommitAttempt).result;
  } catch {
    return commitEntryResult(request, "unavailable", { reasonCode: "provider_call_failed" });
  }
}

function readResultBase(goalId: string): JsonObject {
  return {
    schema_version: LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA,
    goal_id: goalId,
    status: "unavailable",
    reason_code: null,
    store_identity: null,
    provider_revision: null,
    cursor: null,
    head: null,
    head_digest: null,
    partitions: null,
    scan: null,
  };
}

function loadedReadResult(
  base: JsonObject,
  storeIdentity: string,
  loaded: Extract<AuthorityStoreLoadResult, { status: "loaded" | "missing" }>,
): JsonObject {
  const result: JsonObject = { ...base, status: loaded.status, store_identity: storeIdentity };
  if (loaded.status === "loaded") {
    result.provider_revision = loaded.provider_revision;
    result.cursor = loaded.cursor;
    result.head = structuredClone(loaded.head);
    result.head_digest = localAuthorityShadowHeadDigest(loaded.head);
    result.partitions = partitionsOf(loaded.head);
  }
  return result;
}

/** One committed transaction with its projection reduced to a digest. */
function scanTransactionView(transaction: AuthorityStoreCommittedTransaction): JsonObject {
  return {
    cursor: transaction.cursor,
    provider_revision: transaction.provider_revision,
    operation_id: transaction.operation_id,
    projection_digest: localAuthorityShadowHeadDigest(transaction.projection),
    projection_partitions: partitionsOf(transaction.projection),
    events: structuredClone(transaction.events) as JsonObject[],
    receipts: structuredClone(transaction.receipts) as JsonObject[],
  };
}

async function appendScanPage(
  store: AuthorityStore,
  request: ReadRequest,
  result: JsonObject,
): Promise<JsonObject> {
  const page = await store.scanCommitted(request.scan_after_cursor, request.scan_limit);
  if (page.status !== "page") {
    return { ...result, status: page.status, reason_code: page.reason_code };
  }
  return {
    ...result,
    scan: {
      transactions: page.transactions.map(scanTransactionView),
      next_cursor: page.next_cursor,
      has_more: page.has_more,
    },
  };
}

/**
 * Read-only view of the candidate store for drain readback and parity:
 * head, its comparison digest, and a page of committed transactions with the
 * projection reduced to its digest so responses stay bounded.
 */
export async function readLocalAuthorityShadow(
  value: unknown,
  dependencies: LocalAuthorityShadowDependencies = {},
): Promise<JsonObject> {
  const request = decodeReadRequest(value);
  const base = readResultBase(request.goal_id);
  let store: AuthorityStore;
  try {
    store = openShadowStore(
      request.runtime_root,
      request.goal_id,
      request.store_kind,
      dependencies,
    );
  } catch {
    return { ...base, reason_code: "provider_construction_failed" };
  }
  try {
    const identity = await store.storeIdentity();
    if (identity.status !== "available") {
      return { ...base, status: identity.status, reason_code: identity.reason_code };
    }
    const loaded = await store.loadAuthority();
    if (loaded.status === "unavailable" || loaded.status === "failed") {
      return {
        ...base,
        status: loaded.status,
        reason_code: loaded.reason_code,
        store_identity: identity.store_identity,
      };
    }
    const result = loadedReadResult(base, identity.store_identity, loaded);
    return request.scan_limit > 0 ? await appendScanPage(store, request, result) : result;
  } catch {
    return { ...base, reason_code: "provider_call_failed" };
  }
}

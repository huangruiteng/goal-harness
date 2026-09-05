import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { durableWriteJson } from "../effect_runtime_io.ts";
import { authorityUnicodeCompare, canonicalAuthorityBytes } from "./authority_store_codec.ts";
import {
  LOCAL_AUTHORITY_SHADOW_BINDING_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_DRAIN_CURSOR_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA,
} from "./coordination_state_contract.generated.ts";

/**
 * Lease-partition side of the local authority shadow outbox.
 *
 * The task-lease writers already hold the goal's lease lock when they persist
 * a record; this module lets them append a two-phase outbox entry for exactly
 * that partition inside the same lock. It never touches the candidate store,
 * never blocks, and never throws into the lease write: every failure is
 * returned on the capture object so the writer can attach typed evidence.
 */

export {
  LOCAL_AUTHORITY_SHADOW_BINDING_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_DRAIN_CURSOR_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA,
};
export const LEASE_PARTITION = "leases";
const ENTRY_FILE = /^(\d{10})-(local-shadow-tx-[0-9a-f]{64})\.(prepared|committed)\.json$/u;
const LEASE_FILE = /^[A-Za-z0-9_.-]+\.json$/u;
const LEASE_SOURCE_FIELDS = ["todo_id", "version", "lease_epoch", "status", "updated_at"] as const;

export interface LocalAuthorityShadowBinding {
  schema_version: typeof LOCAL_AUTHORITY_SHADOW_BINDING_SCHEMA;
  provider: "file_v0";
}

/** Decode the optional per-request binding; anything but the exact contract is "absent". */
export function decodeLocalAuthorityShadowBinding(
  value: unknown,
): LocalAuthorityShadowBinding | null {
  if (value === null || value === undefined || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  if (
    keys.length !== 2 ||
    record.schema_version !== LOCAL_AUTHORITY_SHADOW_BINDING_SCHEMA ||
    record.provider !== "file_v0"
  ) {
    return null;
  }
  return { schema_version: LOCAL_AUTHORITY_SHADOW_BINDING_SCHEMA, provider: "file_v0" };
}

export function sha256Digest(input: Uint8Array | string): string {
  return `sha256:${createHash("sha256").update(input).digest("hex")}`;
}

/** Digest of the exact bytes `atomicWriteJson` persists for a lease record. */
export function leaseRecordDigest(record: JsonObject): string {
  return sha256Digest(`${JSON.stringify(record, null, 2)}\n`);
}

/** Must stay byte-compatible with the Python `entry_identity` derivation. */
export function outboxEntryIdentity(
  goalId: string,
  partition: string,
  seq: number,
  sourceRef: string,
): string {
  const digest = createHash("sha256")
    .update(canonicalAuthorityBytes({
      goal_id: goalId,
      partition,
      seq,
      source_ref: sourceRef,
    }))
    .digest("hex");
  return `local-shadow-tx-${digest}`;
}

export function outboxPartitionDirectory(
  runtimeRoot: string,
  goalId: string,
  partition: string,
): string {
  return join(runtimeRoot, "authority-shadow", "outbox", goalId, partition);
}

export function outboxEntryFileName(seq: number, entryId: string, phase: "prepared" | "committed"): string {
  return `${String(seq).padStart(10, "0")}-${entryId}.${phase}.json`;
}

function isMissing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException | null)?.code === "ENOENT";
}

async function nextSeq(directory: string): Promise<number> {
  let highest = 0;
  try {
    for (const name of await readdir(directory)) {
      const match = ENTRY_FILE.exec(name);
      if (match !== null) highest = Math.max(highest, Number(match[1]));
    }
  } catch (error) {
    if (!isMissing(error)) throw error;
  }
  try {
    const raw: unknown = JSON.parse(await readFile(join(directory, "drain-cursor.json"), "utf8"));
    if (raw !== null && typeof raw === "object") {
      const lastSeq = (raw as Record<string, unknown>).last_seq;
      if (typeof lastSeq === "number" && Number.isSafeInteger(lastSeq)) {
        highest = Math.max(highest, lastSeq);
      }
    }
  } catch (error) {
    if (!isMissing(error)) throw error;
  }
  return highest + 1;
}

async function readLeasePartition(
  leaseDirectory: string,
  plannedStem: string,
  plannedLease: JsonObject,
): Promise<JsonObject[]> {
  const records = new Map<string, JsonObject>();
  let names: string[] = [];
  try {
    names = await readdir(leaseDirectory);
  } catch (error) {
    if (!isMissing(error)) throw error;
  }
  for (const name of names) {
    if (!LEASE_FILE.test(name) || name.startsWith(".")) continue;
    const stem = name.slice(0, -".json".length);
    if (stem === plannedStem) continue;
    const raw: unknown = JSON.parse(await readFile(join(leaseDirectory, name), "utf8"));
    if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
      records.set(stem, raw as JsonObject);
    }
  }
  records.set(plannedStem, plannedLease);
  const stems = [...records.keys()];
  stems.sort(authorityUnicodeCompare);
  return stems.map((stem) => ({ file_stem: stem, record: records.get(stem) as JsonObject }));
}

function leaseSourceFacts(record: JsonObject | null): JsonObject | null {
  if (record === null) return null;
  const facts: JsonObject = {};
  for (const field of LEASE_SOURCE_FIELDS) {
    const value = record[field];
    if (value === undefined) continue;
    if (typeof value === "string" || typeof value === "number" || value === null) {
      facts[field] = value;
    }
  }
  return facts;
}

export interface LeaseOutboxCaptureInput {
  runtime_root: string;
  goal_id: string;
  lease_directory: string;
  write_class: string;
  operation_id: string | null;
  previous_lease: JsonObject | null;
  planned_lease: JsonObject;
}

export interface LeaseOutboxCapture {
  entry_id: string | null;
  seq: number | null;
  source_bytes_digest: string | null;
  failure: { reason_code: string; error_class: string } | null;
  /** Write the committed marker after the lease record landed. Never throws. */
  commit(): Promise<void>;
}

function failureOf(reasonCode: string, error: unknown): { reason_code: string; error_class: string } {
  return {
    reason_code: reasonCode,
    error_class: error instanceof Error ? error.constructor.name : typeof error,
  };
}

/**
 * Record a prepared lease-partition entry for the record about to be written.
 *
 * Call inside the lease lock, right before `atomicWriteJson(leasePath, planned)`;
 * call `commit()` right after it returns. A returned failure never blocks the
 * primary write.
 */
export async function beginLeaseOutboxEntry(
  input: LeaseOutboxCaptureInput,
): Promise<LeaseOutboxCapture> {
  const inert: LeaseOutboxCapture = {
    entry_id: null,
    seq: null,
    source_bytes_digest: null,
    failure: null,
    async commit(): Promise<void> {},
  };
  const plannedStem = typeof input.planned_lease.todo_id === "string"
    ? input.planned_lease.todo_id
    : "";
  if (plannedStem.length === 0) {
    return { ...inert, failure: { reason_code: "outbox_prepare_failed", error_class: "MissingTodoId" } };
  }
  const directory = outboxPartitionDirectory(input.runtime_root, input.goal_id, LEASE_PARTITION);
  try {
    const projection = { leases: await readLeasePartition(input.lease_directory, plannedStem, input.planned_lease) };
    const bytesDigest = leaseRecordDigest(input.planned_lease);
    const seq = await nextSeq(directory);
    const entryId = outboxEntryIdentity(input.goal_id, LEASE_PARTITION, seq, bytesDigest);
    const entry: JsonObject = {
      schema_version: LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA,
      goal_id: input.goal_id,
      partition: LEASE_PARTITION,
      seq,
      entry_id: entryId,
      writer: {
        runtime: "typescript",
        write_class: input.write_class,
        operation_id: input.operation_id,
      },
      source: {
        kind: "task_lease_record",
        previous_bytes_digest: input.previous_lease === null
          ? null
          : leaseRecordDigest(input.previous_lease),
        bytes_digest: bytesDigest,
        lease: leaseSourceFacts(input.planned_lease),
        previous_lease: leaseSourceFacts(input.previous_lease),
        event_id: null,
      },
      source_root_digest: sha256Digest(resolve(input.runtime_root)),
      projection,
      partition_digest: null,
      prepared_at: new Date().toISOString(),
    };
    await durableWriteJson(join(directory, outboxEntryFileName(seq, entryId, "prepared")), entry);
    let committed = false;
    const capture: LeaseOutboxCapture = {
      entry_id: entryId,
      seq,
      source_bytes_digest: bytesDigest,
      failure: null,
      async commit(): Promise<void> {
        if (committed) return;
        committed = true;
        try {
          await durableWriteJson(
            join(directory, outboxEntryFileName(seq, entryId, "committed")),
            {
              schema_version: LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA,
              entry_id: entryId,
              committed_at: new Date().toISOString(),
            },
          );
        } catch (error) {
          capture.failure = failureOf("outbox_commit_marker_failed", error);
        }
      },
    };
    return capture;
  } catch (error) {
    return { ...inert, failure: failureOf("outbox_prepare_failed", error) };
  }
}

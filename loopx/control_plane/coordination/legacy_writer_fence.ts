import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { atomicWriteJson, withFileMutationLock } from "../effect_runtime_io.ts";
import { requireJsonObject } from "../runtime_decode.ts";
import {
  canonicalAuthorityBytes,
  canonicalAuthorityObject,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";

export const LEGACY_COORDINATION_WRITER_FENCE_SCHEMA =
  "loopx_legacy_coordination_writer_fence_v0";
export const LEGACY_COORDINATION_WRITER_FENCE_ENGAGE_REQUEST_SCHEMA =
  "loopx_legacy_coordination_writer_fence_engage_request_v0";
export const LEGACY_COORDINATION_WRITER_FENCE_RESULT_SCHEMA =
  "loopx_legacy_coordination_writer_fence_result_v0";
export const LEGACY_COORDINATION_WRITE_CHECK_REQUEST_SCHEMA =
  "loopx_legacy_coordination_write_check_request_v0";
export const LEGACY_COORDINATION_WRITE_CHECK_RESULT_SCHEMA =
  "loopx_legacy_coordination_write_check_result_v0";
export const LEGACY_COORDINATION_TODO_LOCK_KEY = "legacy-todo-writer";
export const LEGACY_COORDINATION_LEASE_LOCK_KEY = "legacy-task-lease-writer";

function runtimeRoot(value: unknown): string {
  if (typeof value !== "string" || value.trim() !== value || !isAbsolute(value)) {
    throw new Error("runtime_root must be an absolute path");
  }
  return value;
}

export function legacyCoordinationWriterFencePath(root: string, goalId: string): string {
  const digest = createHash("sha256").update(goalId, "utf8").digest("hex").slice(0, 16);
  return join(root, "authority-transition", "file-v0", `legacy-writer-fence-${digest}.json`);
}

export function legacyCoordinationTodoLockPath(root: string, goalId: string): string {
  const digest = createHash("sha256").update(goalId, "utf8").digest("hex").slice(0, 16);
  return join(root, "authority-transition", "file-v0", `legacy-todo-writer-${digest}`);
}

export function legacyCoordinationLeaseLockPath(root: string, goalId: string): string {
  const digest = createHash("sha256").update(goalId, "utf8").digest("hex").slice(0, 16);
  return join(root, "authority-transition", "file-v0", `legacy-task-lease-writer-${digest}`);
}

export function decodeLegacyCoordinationWriterFence(value: unknown): JsonObject {
  const fence = canonicalAuthorityObject(value, "legacy coordination writer fence");
  if (
    fence.schema_version !== LEGACY_COORDINATION_WRITER_FENCE_SCHEMA ||
    fence.state !== "engaged"
  ) throw new Error("legacy coordination writer fence must be engaged");
  return canonicalAuthorityObject({
    schema_version: LEGACY_COORDINATION_WRITER_FENCE_SCHEMA,
    state: "engaged",
    goal_id: requireAuthorityStoreId(fence.goal_id, "writer fence goal id"),
    fence_id: requireAuthorityStoreId(fence.fence_id, "writer fence id"),
    source_version: requireAuthorityStoreId(
      fence.source_version,
      "writer fence source version",
    ),
    source_projection_sha256: requireAuthorityStoreId(
      fence.source_projection_sha256,
      "writer fence source projection sha256",
    ),
    expected_shadow_provider_revision: requireAuthorityStoreId(
      fence.expected_shadow_provider_revision,
      "writer fence expected shadow provider revision",
    ),
  }, "legacy coordination writer fence");
}

export async function loadLegacyCoordinationWriterFence(
  root: string,
  goalId: string,
): Promise<{ status: "missing" } | { status: "loaded"; fence: JsonObject } | {
  status: "failed";
  reason_code: string;
  reason: string;
}> {
  try {
    const raw = await readFile(legacyCoordinationWriterFencePath(runtimeRoot(root), goalId), "utf8");
    const fence = decodeLegacyCoordinationWriterFence(JSON.parse(raw));
    if (fence.goal_id !== goalId) throw new Error("legacy writer fence goal mismatch");
    return { status: "loaded", fence };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { status: "missing" };
    return {
      status: "failed",
      reason_code: "legacy_writer_fence_read_failed",
      reason: error instanceof Error ? error.message : "legacy writer fence read failed",
    };
  }
}

/** Persist the fail-closed marker that every legacy writer must inspect. */
export async function engageLegacyCoordinationWriterFence(value: unknown): Promise<JsonObject> {
  try {
    const input = requireJsonObject(value, "legacy coordination writer fence request");
    if (input.schema_version !== LEGACY_COORDINATION_WRITER_FENCE_ENGAGE_REQUEST_SCHEMA) {
      throw new Error("legacy coordination writer fence request schema mismatch");
    }
    const root = runtimeRoot(input.runtime_root);
    const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
    const fence = decodeLegacyCoordinationWriterFence(input.fence);
    if (fence.goal_id !== goalId) throw new Error("legacy writer fence goal mismatch");
    const path = legacyCoordinationWriterFencePath(root, goalId);
    return await withFileMutationLock(path, async () => {
      const existing = await loadLegacyCoordinationWriterFence(root, goalId);
      if (existing.status === "loaded") {
        const matched = canonicalAuthorityBytes(existing.fence).equals(
          canonicalAuthorityBytes(fence),
        );
        return {
          schema_version: LEGACY_COORDINATION_WRITER_FENCE_RESULT_SCHEMA,
          status: matched ? "replayed" : "conflict",
          ...(matched ? { fence } : {
            reason_code: "legacy_writer_fence_identity_mismatch",
            reason: "a different legacy writer fence is already engaged",
          }),
        };
      }
      if (existing.status === "failed") return {
        schema_version: LEGACY_COORDINATION_WRITER_FENCE_RESULT_SCHEMA,
        ...existing,
      };
      await atomicWriteJson(path, fence);
      const readback = await loadLegacyCoordinationWriterFence(root, goalId);
      if (
        readback.status !== "loaded" ||
        !canonicalAuthorityBytes(readback.fence).equals(canonicalAuthorityBytes(fence))
      ) throw new Error("legacy writer fence readback mismatch");
      return {
        schema_version: LEGACY_COORDINATION_WRITER_FENCE_RESULT_SCHEMA,
        status: "applied",
        fence,
      };
    });
  } catch (error) {
    return {
      schema_version: LEGACY_COORDINATION_WRITER_FENCE_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_legacy_writer_fence_request",
      reason: error instanceof Error ? error.message : "invalid writer fence request",
    };
  }
}

/**
 * Shared guard for legacy Todo/task-lease writers. Missing means legacy mode;
 * a valid engaged marker blocks the write; unreadable state fails closed.
 */
export async function checkLegacyCoordinationWriteAllowed(value: unknown): Promise<JsonObject> {
  try {
    const input = requireJsonObject(value, "legacy coordination write check request");
    if (input.schema_version !== LEGACY_COORDINATION_WRITE_CHECK_REQUEST_SCHEMA) {
      throw new Error("legacy coordination write check request schema mismatch");
    }
    const root = runtimeRoot(input.runtime_root);
    const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
    const result = await loadLegacyCoordinationWriterFence(root, goalId);
    if (result.status === "missing") return {
      schema_version: LEGACY_COORDINATION_WRITE_CHECK_RESULT_SCHEMA,
      status: "allowed",
      authority_mode: "legacy_canonical",
    };
    if (result.status === "loaded") return {
      schema_version: LEGACY_COORDINATION_WRITE_CHECK_RESULT_SCHEMA,
      status: "blocked",
      reason_code: "legacy_coordination_writer_fenced",
      authority_mode: "file_v0",
      fence_id: result.fence.fence_id,
    };
    return {
      schema_version: LEGACY_COORDINATION_WRITE_CHECK_RESULT_SCHEMA,
      ...result,
      status: "failed",
      authority_mode: "unknown_fail_closed",
    };
  } catch (error) {
    return {
      schema_version: LEGACY_COORDINATION_WRITE_CHECK_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_legacy_coordination_write_check",
      reason: error instanceof Error ? error.message : "invalid legacy write check",
      authority_mode: "unknown_fail_closed",
    };
  }
}

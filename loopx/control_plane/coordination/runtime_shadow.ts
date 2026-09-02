import { createHash } from "node:crypto";
import { isAbsolute, join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { requireJsonObject } from "../runtime_decode.ts";
import type {
  AuthorityStore,
  AuthorityStoreReceiptResult,
} from "./authority_store.ts";
import {
  canonicalAuthorityBytes,
  canonicalAuthorityObject,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";
import { FileAuthorityStore } from "./file_authority_store.ts";

export const COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA =
  "loopx_coordination_runtime_shadow_commit_v0";
export const COORDINATION_RUNTIME_SHADOW_RESULT_SCHEMA =
  "loopx_coordination_runtime_shadow_result_v0";
export const COORDINATION_RUNTIME_SHADOW_RECEIPT_SCHEMA =
  "loopx_coordination_runtime_shadow_receipt_v0";

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
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.trim() !== value || value.length === 0) {
    throw new Error(`${label} must be a non-empty trimmed string`);
  }
  return value;
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

function sha256(value: unknown): string {
  return createHash("sha256").update(canonicalAuthorityBytes(value)).digest("hex");
}

function expectedReceipt(request: RuntimeShadowRequest): JsonObject {
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_RECEIPT_SCHEMA,
    operation_id: request.operation_id,
    event_kind: request.event_kind,
    source_version: request.source_version,
    projection_sha256: sha256(request.projection),
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
  const projectionMatches = sha256(head.head) === sha256(request.projection);
  return {
    verified: projectionMatches,
    status: projectionMatches ? "matched_current_head" : "projection_mismatch",
    projection_matches: projectionMatches,
    provider_revision: head.provider_revision,
  };
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

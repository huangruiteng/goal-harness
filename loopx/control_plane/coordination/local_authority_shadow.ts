import { join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import { requireJsonObject, requireNonEmptyString } from "../runtime_decode.ts";
import type {
  AuthorityStore,
  AuthorityStoreLoadResult,
  AuthorityStoreReceiptResult,
} from "./authority_store.ts";
import { FileAuthorityStore } from "./file_authority_store.ts";

export const LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA =
  "loopx_local_authority_shadow_request_v0";
export const LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA =
  "loopx_local_authority_shadow_projection_v0";
export const LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA =
  "loopx_local_authority_shadow_evidence_v0";
export const LOCAL_AUTHORITY_SHADOW_OBSERVATION_RECEIPT_SCHEMA =
  "loopx_local_authority_shadow_observation_receipt_v0";

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

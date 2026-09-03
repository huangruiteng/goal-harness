import { isAbsolute, join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { requireJsonObject } from "../runtime_decode.ts";
import {
  commitCoordinationProjectionMutation,
  indexCoordinationProjection,
  indexCoordinationProjectionTodos,
  validateCoordinationTodoReadModel,
  type CoordinationProjectionMutation,
} from "./coordination_projection.ts";
import type { AuthorityStore, AuthorityStoreReceiptResult } from "./authority_store.ts";
import {
  canonicalAuthorityBytes,
  canonicalAuthorityObject,
  canonicalAuthoritySha256,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";
import { FileAuthorityStore } from "./file_authority_store.ts";
import {
  decodeLegacyCoordinationWriterFence,
  LEGACY_COORDINATION_WRITER_FENCE_SCHEMA,
  loadLegacyCoordinationWriterFence,
} from "./legacy_writer_fence.ts";
import {
  COORDINATION_RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA,
  qualifyCoordinationRuntimeShadow,
} from "./runtime_shadow.ts";

export const LOCAL_COORDINATION_MUTATION_REQUEST_SCHEMA =
  "loopx_local_coordination_mutation_request_v0";
export const LOCAL_COORDINATION_MUTATION_RESULT_SCHEMA =
  "loopx_local_coordination_mutation_result_v0";
export const LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA =
  "loopx_local_coordination_todo_read_request_v0";
export const LOCAL_COORDINATION_TODO_READ_RESULT_SCHEMA =
  "loopx_local_coordination_todo_read_result_v0";
export const LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA =
  "loopx_local_coordination_todo_list_request_v0";
export const LOCAL_COORDINATION_TODO_LIST_RESULT_SCHEMA =
  "loopx_local_coordination_todo_list_result_v0";
export const LOCAL_COORDINATION_PROMOTION_REQUEST_SCHEMA =
  "loopx_local_coordination_promotion_request_v0";
export const LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA =
  "loopx_local_coordination_promotion_result_v0";
export const LOCAL_COORDINATION_PROMOTION_RECEIPT_SCHEMA =
  "loopx_local_coordination_promotion_receipt_v0";
export { LEGACY_COORDINATION_WRITER_FENCE_SCHEMA } from "./legacy_writer_fence.ts";

interface LocalAuthorityRuntimeDependencies {
  createStore?: (directory: string, goalId: string) => AuthorityStore;
  createShadowStore?: (directory: string, goalId: string) => AuthorityStore;
  createCanonicalStore?: (directory: string, goalId: string) => AuthorityStore;
}

function runtimeRoot(value: unknown): string {
  if (typeof value !== "string" || value.trim() !== value || !isAbsolute(value)) {
    throw new Error("runtime_root must be an absolute path");
  }
  return value;
}

function authorityDirectory(root: string): string {
  return join(root, "authority", "file-v0");
}

function shadowDirectory(root: string): string {
  return join(root, "authority-shadow", "file-v0");
}

function requiredPositiveSafeInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 1 || Number(value) > 10_000) {
    throw new Error(`${label} must be a positive safe integer no greater than 10000`);
  }
  return Number(value);
}

function requiredUniqueStrings(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.length > 32) {
    throw new Error(`${label} must be an array with at most 32 entries`);
  }
  const values = value.map((entry, index) =>
    requireAuthorityStoreId(entry, `${label}[${index}]`)
  );
  if (new Set(values).size !== values.length) throw new Error(`${label} contains duplicates`);
  return values;
}

interface LocalCoordinationPromotionRequest {
  runtime_root: string;
  goal_id: string;
  operation_id: string;
  expected_shadow_provider_revision: string;
  expected_shadow_projection_sha256: string;
  minimum_operations: number;
  required_event_kinds: string[];
  writer_fence: JsonObject;
}

function decodePromotionRequest(value: unknown): LocalCoordinationPromotionRequest {
  const input = requireJsonObject(value, "local coordination promotion request");
  if (input.schema_version !== LOCAL_COORDINATION_PROMOTION_REQUEST_SCHEMA) {
    throw new Error("local coordination promotion request schema mismatch");
  }
  const fence = decodeLegacyCoordinationWriterFence(input.writer_fence);
  return {
    runtime_root: runtimeRoot(input.runtime_root),
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    operation_id: requireAuthorityStoreId(input.operation_id, "operation id"),
    expected_shadow_provider_revision: requireAuthorityStoreId(
      input.expected_shadow_provider_revision,
      "expected shadow provider revision",
    ),
    expected_shadow_projection_sha256: requireAuthorityStoreId(
      input.expected_shadow_projection_sha256,
      "expected shadow projection sha256",
    ),
    minimum_operations: requiredPositiveSafeInteger(
      input.minimum_operations,
      "minimum_operations",
    ),
    required_event_kinds: requiredUniqueStrings(
      input.required_event_kinds,
      "required_event_kinds",
    ),
    writer_fence: fence,
  };
}

function promotionIdentity(request: LocalCoordinationPromotionRequest): JsonObject {
  return canonicalAuthorityObject({
    schema_version: LOCAL_COORDINATION_PROMOTION_RECEIPT_SCHEMA,
    operation_id: request.operation_id,
    goal_id: request.goal_id,
    source_shadow_provider_revision: request.expected_shadow_provider_revision,
    source_projection_sha256: request.expected_shadow_projection_sha256,
    writer_fence_id: request.writer_fence.fence_id,
    source_version: request.writer_fence.source_version,
  }, "local coordination promotion identity");
}

function matchingReceipt(
  result: AuthorityStoreReceiptResult,
  expected: JsonObject,
): Extract<AuthorityStoreReceiptResult, { status: "found" }> | null {
  return result.status === "found" && result.receipts.length === 1 &&
      canonicalAuthorityBytes(result.receipts[0]).equals(canonicalAuthorityBytes(expected))
    ? result
    : null;
}

async function promotionReadback(
  store: AuthorityStore,
  request: LocalCoordinationPromotionRequest,
): Promise<{ matched: boolean; provider_revision?: string; cursor?: string; reason_code?: string }> {
  const receiptResult = await store.readReceipt(request.operation_id);
  const receipt = matchingReceipt(receiptResult, promotionIdentity(request));
  if (receipt === null) {
    return {
      matched: false,
      reason_code: receiptResult.status === "found"
        ? "local_authority_promotion_identity_mismatch"
        : "local_authority_promotion_receipt_missing",
    };
  }
  const lineage = await store.scanCommitted(null, 1);
  const promotion = lineage.status === "page" ? lineage.transactions[0] : undefined;
  if (
    promotion === undefined ||
    promotion.cursor !== "1" ||
    promotion.operation_id !== request.operation_id ||
    canonicalAuthoritySha256(promotion.projection) !== request.expected_shadow_projection_sha256
  ) {
    return { matched: false, reason_code: "local_authority_promotion_lineage_mismatch" };
  }
  return {
    matched: true,
    provider_revision: receipt.provider_revision,
    cursor: receipt.cursor,
  };
}

function promotionResult(
  request: LocalCoordinationPromotionRequest,
  status: "applied" | "replayed" | "recovered",
  readback: Awaited<ReturnType<typeof promotionReadback>>,
): JsonObject {
  return {
    schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
    status,
    operation_id: request.operation_id,
    provider_revision: readback.provider_revision,
    cursor: readback.cursor,
    source_shadow_provider_revision: request.expected_shadow_provider_revision,
    source_projection_sha256: request.expected_shadow_projection_sha256,
    writer_fence_id: request.writer_fence.fence_id,
    source_version: request.writer_fence.source_version,
    canonical_authority: "file_v0",
    legacy_writer_fenced: true,
    legacy_fallback_used: false,
  };
}

/**
 * Explicit Stage 2C cutover. The shadow must still match the caller's exact
 * qualified revision and digest after the legacy writer fence is engaged.
 * Nothing calls this from a read path, so canonical promotion cannot happen
 * implicitly as a side effect of observing a healthy shadow.
 */
export async function promoteLocalCoordinationAuthority(
  value: unknown,
  dependencies: LocalAuthorityRuntimeDependencies = {},
): Promise<JsonObject> {
  let request: LocalCoordinationPromotionRequest;
  try {
    request = decodePromotionRequest(value);
  } catch (error) {
    return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_local_coordination_promotion_request",
      reason: error instanceof Error ? error.message : "invalid promotion request",
      legacy_writer_fenced: false,
      legacy_fallback_used: false,
    };
  }
  if (request.writer_fence.source_projection_sha256 !== request.expected_shadow_projection_sha256) {
    return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "local_authority_writer_fence_projection_mismatch",
      reason: "writer fence is not bound to the selected shadow projection",
      legacy_writer_fenced: false,
      legacy_fallback_used: false,
    };
  }
  if (
    request.writer_fence.goal_id !== request.goal_id ||
    request.writer_fence.expected_shadow_provider_revision !==
      request.expected_shadow_provider_revision
  ) {
    return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "local_authority_writer_fence_revision_mismatch",
      reason: "writer fence is not bound to the selected goal and shadow revision",
      legacy_writer_fenced: false,
      legacy_fallback_used: false,
    };
  }

  const shadow = dependencies.createShadowStore?.(
    shadowDirectory(request.runtime_root),
    request.goal_id,
  ) ?? new FileAuthorityStore(shadowDirectory(request.runtime_root), request.goal_id);
  const canonical = dependencies.createCanonicalStore?.(
    authorityDirectory(request.runtime_root),
    request.goal_id,
  ) ?? dependencies.createStore?.(
    authorityDirectory(request.runtime_root),
    request.goal_id,
  ) ?? new FileAuthorityStore(authorityDirectory(request.runtime_root), request.goal_id);
  try {
    const persistedFence = await loadLegacyCoordinationWriterFence(
      request.runtime_root,
      request.goal_id,
    );
    if (
      persistedFence.status !== "loaded" ||
      !canonicalAuthorityBytes(persistedFence.fence).equals(
        canonicalAuthorityBytes(request.writer_fence),
      )
    ) return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: persistedFence.status === "failed"
        ? persistedFence.reason_code
        : "local_authority_writer_fence_not_verified",
      reason: persistedFence.status === "failed"
        ? persistedFence.reason
        : "exact durable legacy writer fence must be engaged before promotion",
      legacy_writer_fenced: false,
      legacy_fallback_used: false,
    };
    const existing = await canonical.loadAuthority();
    if (existing.status === "loaded") {
      const readback = await promotionReadback(canonical, request);
      return readback.matched
        ? promotionResult(request, "replayed", readback)
        : {
          schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
          status: "failed",
          reason_code: readback.reason_code ?? "local_authority_already_initialized",
          reason: "canonical local authority is already initialized by different content",
          legacy_writer_fenced: true,
          legacy_fallback_used: false,
        };
    }
    if (existing.status !== "missing") return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      ...existing,
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };

    const shadowHead = await shadow.loadAuthority();
    if (shadowHead.status !== "loaded") return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: shadowHead.status === "missing"
        ? "local_authority_shadow_missing"
        : shadowHead.reason_code,
      reason: shadowHead.status === "missing" ? "qualified shadow authority is missing" : shadowHead.reason,
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };
    const observedDigest = canonicalAuthoritySha256(shadowHead.head);
    if (
      shadowHead.provider_revision !== request.expected_shadow_provider_revision ||
      observedDigest !== request.expected_shadow_projection_sha256
    ) return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "local_authority_shadow_fence_mismatch",
      reason: "shadow revision or projection changed before promotion",
      observed_shadow_provider_revision: shadowHead.provider_revision,
      observed_shadow_projection_sha256: observedDigest,
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };
    indexCoordinationProjection(shadowHead.head, request.goal_id);

    const qualification = await qualifyCoordinationRuntimeShadow({
      schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA,
      runtime_root: request.runtime_root,
      goal_id: request.goal_id,
      projection: shadowHead.head,
      minimum_operations: request.minimum_operations,
      required_event_kinds: request.required_event_kinds,
    }, {
      createStore: () => shadow,
    });
    if (qualification.status !== "qualified" || qualification.qualified !== true) return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "local_authority_shadow_not_qualified",
      reason: "shadow parity evidence does not satisfy the promotion policy",
      qualification_status: qualification.status,
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };

    const finalShadowHead = await shadow.loadAuthority();
    if (
      finalShadowHead.status !== "loaded" ||
      finalShadowHead.provider_revision !== request.expected_shadow_provider_revision ||
      canonicalAuthoritySha256(finalShadowHead.head) !== request.expected_shadow_projection_sha256
    ) return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "local_authority_shadow_changed_during_qualification",
      reason: "shadow head changed while promotion evidence was being verified",
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };

    const identity = promotionIdentity(request);
    const committed = await canonical.commitAuthority({
      expected_provider_revision: null,
      operation_id: request.operation_id,
      events: [{
        ...identity,
        schema_version: "loopx_local_coordination_promotion_event_v0",
        mode_transition: "legacy_canonical_to_file_v0",
      }],
      next_projection: finalShadowHead.head,
      receipts: [identity],
    });
    if (committed.status === "applied") {
      const readback = await promotionReadback(canonical, request);
      return readback.matched
        ? promotionResult(request, "applied", readback)
        : {
          schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
          status: "failed",
          reason_code: readback.reason_code ?? "local_authority_promotion_readback_mismatch",
          reason: "promotion commit lacks an exact durable readback",
          legacy_writer_fenced: true,
          legacy_fallback_used: false,
        };
    }
    const readback = await promotionReadback(canonical, request);
    if (readback.matched) {
      return promotionResult(
        request,
        committed.status === "ambiguous" ? "recovered" : "replayed",
        readback,
      );
    }
    return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      ...committed,
      ...(committed.status === "ambiguous" ? { reconciliation_required: true } : {}),
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };
  } catch (error) {
    return {
      schema_version: LOCAL_COORDINATION_PROMOTION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "local_authority_promotion_unavailable",
      reason: error instanceof Error ? error.message : "promotion unavailable",
      legacy_writer_fenced: true,
      legacy_fallback_used: false,
    };
  }
}

function decodeMutations(value: unknown): CoordinationProjectionMutation[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("mutations must be a non-empty array");
  }
  return value.map((candidate, index) => {
    const mutation = canonicalAuthorityObject(candidate, `mutations[${index}]`);
    switch (mutation.kind) {
      case "todo_upsert":
        return {
          kind: "todo_upsert",
          todo: canonicalAuthorityObject(mutation.todo, `mutations[${index}].todo`),
        };
      case "todo_remove":
        return {
          kind: "todo_remove",
          todo_id: requireAuthorityStoreId(mutation.todo_id, `mutations[${index}].todo_id`),
        };
      case "lease_upsert":
        return {
          kind: "lease_upsert",
          lease: canonicalAuthorityObject(mutation.lease, `mutations[${index}].lease`),
        };
      case "lease_remove":
        return {
          kind: "lease_remove",
          todo_id: requireAuthorityStoreId(mutation.todo_id, `mutations[${index}].todo_id`),
        };
      default:
        throw new Error(`mutations[${index}].kind is unsupported`);
    }
  });
}

/** Provider-first mutation entry point. It never reads a legacy projection. */
export async function mutateLocalCoordinationAuthority(
  value: unknown,
  dependencies: LocalAuthorityRuntimeDependencies = {},
): Promise<JsonObject> {
  try {
    const input = requireJsonObject(value, "local coordination mutation request");
    if (input.schema_version !== LOCAL_COORDINATION_MUTATION_REQUEST_SCHEMA) {
      throw new Error("local coordination mutation request schema mismatch");
    }
    const root = runtimeRoot(input.runtime_root);
    const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
    const store = dependencies.createStore?.(authorityDirectory(root), goalId) ??
      new FileAuthorityStore(authorityDirectory(root), goalId);
    const result = await commitCoordinationProjectionMutation(store, {
      goal_id: goalId,
      operation_id: requireAuthorityStoreId(input.operation_id, "operation id"),
      expected_provider_revision: requireAuthorityStoreId(
        input.expected_provider_revision,
        "expected provider revision",
      ),
      mutations: decodeMutations(input.mutations),
    });
    return {
      schema_version: LOCAL_COORDINATION_MUTATION_RESULT_SCHEMA,
      ...result,
      source_authority: "file_v0",
      decision_read_from_provider: true,
      legacy_fallback_used: false,
    };
  } catch (error) {
    return {
      schema_version: LOCAL_COORDINATION_MUTATION_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_local_coordination_mutation_request",
      reason: error instanceof Error ? error.message : "invalid mutation request",
      source_authority: "file_v0",
      decision_read_from_provider: true,
      legacy_fallback_used: false,
    };
  }
}

/** Provider-first exact Todo read. Missing/unavailable state never falls back. */
export async function readLocalCoordinationTodo(
  value: unknown,
  dependencies: LocalAuthorityRuntimeDependencies = {},
): Promise<JsonObject> {
  try {
    const input = requireJsonObject(value, "local coordination Todo read request");
    if (input.schema_version !== LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA) {
      throw new Error("local coordination Todo read request schema mismatch");
    }
    const root = runtimeRoot(input.runtime_root);
    const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
    const todoId = requireAuthorityStoreId(input.todo_id, "todo id");
    const store = dependencies.createStore?.(authorityDirectory(root), goalId) ??
      new FileAuthorityStore(authorityDirectory(root), goalId);
    const head = await store.loadAuthority();
    if (head.status !== "loaded") {
      return {
        schema_version: LOCAL_COORDINATION_TODO_READ_RESULT_SCHEMA,
        ...head,
        source_authority: "file_v0",
        decision_read_from_provider: true,
        legacy_fallback_used: false,
      };
    }
    const projection = indexCoordinationProjectionTodos(head.head, goalId);
    validateCoordinationTodoReadModel(head.head, goalId);
    const todo = projection.todos.get(todoId);
    return {
      schema_version: LOCAL_COORDINATION_TODO_READ_RESULT_SCHEMA,
      status: todo === undefined ? "missing" : "found",
      todo_id: todoId,
      ...(todo === undefined ? {} : { todo }),
      todo_ids: projection.todo_ids,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      source_authority: "file_v0",
      decision_read_from_provider: true,
      legacy_fallback_used: false,
    };
  } catch (error) {
    return {
      schema_version: LOCAL_COORDINATION_TODO_READ_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_local_coordination_todo_read_request",
      reason: error instanceof Error ? error.message : "invalid Todo read request",
      source_authority: "file_v0",
      decision_read_from_provider: true,
      legacy_fallback_used: false,
    };
  }
}

/** Provider-first Todo collection read. Missing/unavailable state never falls back. */
export async function listLocalCoordinationTodos(
  value: unknown,
  dependencies: LocalAuthorityRuntimeDependencies = {},
): Promise<JsonObject> {
  try {
    const input = requireJsonObject(value, "local coordination Todo list request");
    if (input.schema_version !== LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA) {
      throw new Error("local coordination Todo list request schema mismatch");
    }
    const root = runtimeRoot(input.runtime_root);
    const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
    const store = dependencies.createStore?.(authorityDirectory(root), goalId) ??
      new FileAuthorityStore(authorityDirectory(root), goalId);
    const head = await store.loadAuthority();
    if (head.status !== "loaded") {
      return {
        schema_version: LOCAL_COORDINATION_TODO_LIST_RESULT_SCHEMA,
        ...head,
        source_authority: "file_v0",
        decision_read_from_provider: true,
        legacy_fallback_used: false,
      };
    }
    const projection = indexCoordinationProjectionTodos(head.head, goalId);
    const todoReadModel = validateCoordinationTodoReadModel(head.head, goalId);
    return {
      schema_version: LOCAL_COORDINATION_TODO_LIST_RESULT_SCHEMA,
      status: "loaded",
      todos: projection.todo_ids.map((todoId) => projection.todos.get(todoId)!),
      todo_ids: projection.todo_ids,
      todo_read_model: todoReadModel,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      source_authority: "file_v0",
      decision_read_from_provider: true,
      legacy_fallback_used: false,
    };
  } catch (error) {
    return {
      schema_version: LOCAL_COORDINATION_TODO_LIST_RESULT_SCHEMA,
      status: "failed",
      reason_code: "invalid_local_coordination_todo_list_request",
      reason: error instanceof Error ? error.message : "invalid Todo list request",
      source_authority: "file_v0",
      decision_read_from_provider: true,
      legacy_fallback_used: false,
    };
  }
}

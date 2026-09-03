import type { JsonObject } from "../effect_program.ts";
import type {
  AuthorityStore,
  AuthorityStoreCommit,
  AuthorityStoreCommitResult,
  AuthorityStoreReadFailure,
  AuthorityStoreReceiptResult,
} from "./authority_store.ts";
import {
  AuthorityStoreProtocolError,
  authorityUnicodeCompare,
  canonicalAuthorityBytes,
  canonicalAuthorityObject,
  canonicalAuthoritySha256,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";

export const COORDINATION_PROJECTION_MUTATION_EVENT_SCHEMA =
  "loopx_coordination_projection_mutation_event_v0";
export const COORDINATION_PROJECTION_MUTATION_RECEIPT_SCHEMA =
  "loopx_coordination_projection_mutation_receipt_v0";

export interface CoordinationTodoProjectionIndex {
  readonly todos: ReadonlyMap<string, JsonObject>;
  readonly todo_ids: readonly string[];
}

export interface CoordinationProjectionIndex extends CoordinationTodoProjectionIndex {
  readonly leases: ReadonlyMap<string, JsonObject>;
  readonly lease_todo_ids: readonly string[];
}

export type CoordinationProjectionMutation =
  | { readonly kind: "todo_upsert"; readonly todo: JsonObject }
  | { readonly kind: "todo_remove"; readonly todo_id: string }
  | { readonly kind: "lease_upsert"; readonly lease: JsonObject }
  | { readonly kind: "lease_remove"; readonly todo_id: string };

export interface CoordinationProjectionCommitInput {
  readonly goal_id: string;
  readonly operation_id: string;
  readonly expected_provider_revision: string;
  readonly projection: JsonObject;
  readonly mutations: readonly CoordinationProjectionMutation[];
}

export interface CoordinationProjectionMutationInput {
  readonly goal_id: string;
  readonly operation_id: string;
  readonly expected_provider_revision: string;
  readonly mutations: readonly CoordinationProjectionMutation[];
}

export type CoordinationProjectionMutationResult =
  | {
    readonly status: "applied" | "replayed" | "recovered";
    readonly provider_revision: string;
    readonly cursor: string;
  }
  | Extract<AuthorityStoreCommitResult, { status: "conflict" | "ambiguous" }>
  | AuthorityStoreReadFailure;

function sortedIds(values: Iterable<string>): string[] {
  return [...values].sort(authorityUnicodeCompare);
}

function indexRecords(
  value: unknown,
  field: "todos" | "leases",
): Map<string, JsonObject> {
  if (!Array.isArray(value)) {
    throw new AuthorityStoreProtocolError(`coordination projection ${field} must be an array`);
  }
  const records = new Map<string, JsonObject>();
  for (const [index, candidate] of value.entries()) {
    const record = canonicalAuthorityObject(candidate, `projection.${field}[${index}]`);
    const todoId = requireAuthorityStoreId(
      record.todo_id,
      `projection.${field}[${index}].todo_id`,
    );
    if (records.has(todoId)) {
      throw new AuthorityStoreProtocolError(
        `coordination projection contains duplicate ${field === "todos" ? "todo" : "lease"} ids`,
      );
    }
    records.set(todoId, record);
  }
  return records;
}

/**
 * Validate and index the Todo portion of one canonical coordination
 * projection. Keeping this invariant outside a provider adapter lets the
 * current shadow read and the future canonical transition path share exactly
 * one identity boundary.
 */
export function indexCoordinationProjectionTodos(
  value: JsonObject,
  expectedGoalId: string,
): CoordinationTodoProjectionIndex {
  if (value.goal_id !== expectedGoalId) {
    throw new AuthorityStoreProtocolError("coordination projection goal mismatch");
  }
  const todos = indexRecords(value.todos, "todos");

  return {
    todos,
    todo_ids: sortedIds(todos.keys()),
  };
}

/** Validate the complete Todo/lease identity graph of one coordination head. */
export function indexCoordinationProjection(
  value: JsonObject,
  expectedGoalId: string,
): CoordinationProjectionIndex {
  const todoIndex = indexCoordinationProjectionTodos(value, expectedGoalId);
  const leases = indexRecords(value.leases, "leases");
  for (const todoId of leases.keys()) {
    if (!todoIndex.todos.has(todoId)) {
      throw new AuthorityStoreProtocolError(
        "coordination projection lease references an unknown todo",
      );
    }
  }
  return {
    ...todoIndex,
    leases,
    lease_todo_ids: sortedIds(leases.keys()),
  };
}

/**
 * Apply one already-authorized coordination transaction as a pure projection
 * reduction. Domain transition policy stays with the LoopX kernel; this
 * reducer owns only exact identity replacement/removal, deterministic order,
 * and the final Todo/lease referential-integrity fence shared by every store.
 */
export function reduceCoordinationProjection(
  value: JsonObject,
  expectedGoalId: string,
  mutations: readonly CoordinationProjectionMutation[],
): JsonObject {
  if (mutations.length === 0) {
    throw new AuthorityStoreProtocolError("coordination projection mutation batch is empty");
  }
  const current = indexCoordinationProjection(value, expectedGoalId);
  const todos = new Map(current.todos);
  const leases = new Map(current.leases);
  const mutatedRecords = new Set<string>();

  const claimMutationTarget = (kind: "todo" | "lease", todoId: string): void => {
    const target = `${kind}:${todoId}`;
    if (mutatedRecords.has(target)) {
      throw new AuthorityStoreProtocolError(
        "coordination projection mutation targets one record more than once",
      );
    }
    mutatedRecords.add(target);
  };

  for (const [index, mutation] of mutations.entries()) {
    switch (mutation.kind) {
      case "todo_upsert": {
        const todo = canonicalAuthorityObject(mutation.todo, `mutations[${index}].todo`);
        const todoId = requireAuthorityStoreId(todo.todo_id, `mutations[${index}].todo_id`);
        claimMutationTarget("todo", todoId);
        todos.set(todoId, todo);
        break;
      }
      case "todo_remove": {
        const todoId = requireAuthorityStoreId(
          mutation.todo_id,
          `mutations[${index}].todo_id`,
        );
        claimMutationTarget("todo", todoId);
        if (!todos.delete(todoId)) {
          throw new AuthorityStoreProtocolError("coordination projection todo remove target missing");
        }
        break;
      }
      case "lease_upsert": {
        const lease = canonicalAuthorityObject(mutation.lease, `mutations[${index}].lease`);
        const todoId = requireAuthorityStoreId(lease.todo_id, `mutations[${index}].todo_id`);
        claimMutationTarget("lease", todoId);
        leases.set(todoId, lease);
        break;
      }
      case "lease_remove": {
        const todoId = requireAuthorityStoreId(
          mutation.todo_id,
          `mutations[${index}].todo_id`,
        );
        claimMutationTarget("lease", todoId);
        if (!leases.delete(todoId)) {
          throw new AuthorityStoreProtocolError("coordination projection lease remove target missing");
        }
        break;
      }
      default: {
        const unreachable: never = mutation;
        throw new AuthorityStoreProtocolError(
          `unsupported coordination projection mutation: ${String(unreachable)}`,
        );
      }
    }
  }

  for (const todoId of leases.keys()) {
    if (!todos.has(todoId)) {
      throw new AuthorityStoreProtocolError(
        "coordination projection mutation leaves an orphan lease",
      );
    }
  }
  return canonicalAuthorityObject({
    ...value,
    todos: sortedIds(todos.keys()).map((todoId) => todos.get(todoId)!),
    leases: sortedIds(leases.keys()).map((todoId) => leases.get(todoId)!),
  }, "coordination projection");
}

function mutationTarget(mutation: CoordinationProjectionMutation, index: number): string {
  const record = mutation.kind === "todo_upsert"
    ? canonicalAuthorityObject(mutation.todo, `mutations[${index}].todo`)
    : mutation.kind === "lease_upsert"
    ? canonicalAuthorityObject(mutation.lease, `mutations[${index}].lease`)
    : mutation;
  const todoId = requireAuthorityStoreId(record.todo_id, `mutations[${index}].todo_id`);
  return `${mutation.kind.startsWith("todo_") ? "todo" : "lease"}:${todoId}`;
}

/**
 * Prepare the one AuthorityStore transaction used by the canonical cutover.
 * Event, next projection, and receipt are derived from the same validated
 * reduction so a provider adapter cannot accidentally persist three
 * disagreeing descriptions of one effect.
 */
export function prepareCoordinationProjectionCommit(
  input: CoordinationProjectionCommitInput,
): AuthorityStoreCommit {
  const goalId = requireAuthorityStoreId(input.goal_id, "goal id");
  const operationId = requireAuthorityStoreId(input.operation_id, "operation id");
  const expectedRevision = requireAuthorityStoreId(
    input.expected_provider_revision,
    "expected provider revision",
  );
  const currentProjection = canonicalAuthorityObject(input.projection, "projection");
  const nextProjection = reduceCoordinationProjection(
    currentProjection,
    goalId,
    input.mutations,
  );
  const targets = input.mutations.map(mutationTarget).sort(authorityUnicodeCompare);
  const mutationKinds = input.mutations.map((mutation) => mutation.kind).sort(
    authorityUnicodeCompare,
  );
  const previousProjectionSha256 = canonicalAuthoritySha256(currentProjection);
  const nextProjectionSha256 = canonicalAuthoritySha256(nextProjection);
  const mutationSha256 = canonicalAuthoritySha256(input.mutations);
  const common = {
    operation_id: operationId,
    goal_id: goalId,
    mutation_kinds: mutationKinds,
    targets,
    mutation_sha256: mutationSha256,
    previous_projection_sha256: previousProjectionSha256,
    next_projection_sha256: nextProjectionSha256,
  };
  return {
    expected_provider_revision: expectedRevision,
    operation_id: operationId,
    events: [{
      schema_version: COORDINATION_PROJECTION_MUTATION_EVENT_SCHEMA,
      ...common,
    }],
    next_projection: nextProjection,
    receipts: [{
      schema_version: COORDINATION_PROJECTION_MUTATION_RECEIPT_SCHEMA,
      ...common,
    }],
  };
}

function expectedMutationReceiptIdentity(
  input: CoordinationProjectionMutationInput,
): JsonObject {
  return canonicalAuthorityObject({
    schema_version: COORDINATION_PROJECTION_MUTATION_RECEIPT_SCHEMA,
    operation_id: requireAuthorityStoreId(input.operation_id, "operation id"),
    goal_id: requireAuthorityStoreId(input.goal_id, "goal id"),
    mutation_sha256: canonicalAuthoritySha256(input.mutations),
  }, "coordination mutation receipt identity");
}

function receiptProvesMutation(
  result: AuthorityStoreReceiptResult,
  expected: JsonObject,
): result is Extract<AuthorityStoreReceiptResult, { status: "found" }> {
  if (result.status !== "found" || result.receipts.length !== 1) return false;
  const receipt = result.receipts[0]!;
  return receipt.schema_version === expected.schema_version &&
    receipt.operation_id === expected.operation_id &&
    receipt.goal_id === expected.goal_id &&
    receipt.mutation_sha256 === expected.mutation_sha256;
}

function receiptIdentityMismatch(
  result: AuthorityStoreReceiptResult,
  expected: JsonObject,
): CoordinationProjectionMutationResult | null {
  if (result.status !== "found" || receiptProvesMutation(result, expected)) return null;
  return {
    status: "failed",
    reason_code: "coordination_operation_identity_mismatch",
    reason: "operation id already names a different coordination mutation",
  };
}

/**
 * Execute one provider-first coordination mutation against the exact loaded
 * head. The caller supplies no projection, which prevents a legacy snapshot
 * from being smuggled back into the canonical write path after promotion.
 */
export async function commitCoordinationProjectionMutation(
  store: AuthorityStore,
  input: CoordinationProjectionMutationInput,
): Promise<CoordinationProjectionMutationResult> {
  let expectedReceipt: JsonObject;
  try {
    expectedReceipt = expectedMutationReceiptIdentity(input);
  } catch (error) {
    return {
      status: "failed",
      reason_code: "invalid_coordination_mutation",
      reason: error instanceof Error ? error.message : "invalid coordination mutation",
    };
  }

  const existing = await store.readReceipt(input.operation_id);
  if (existing.status === "found") {
    return receiptProvesMutation(existing, expectedReceipt)
      ? {
        status: "replayed",
        provider_revision: existing.provider_revision,
        cursor: existing.cursor,
      }
      : {
        status: "failed",
        reason_code: "coordination_operation_identity_mismatch",
        reason: "operation id already names a different coordination mutation",
      };
  }
  if (existing.status !== "missing") return existing;

  const head = await store.loadAuthority();
  if (head.status === "missing") {
    return {
      status: "failed",
      reason_code: "coordination_authority_missing",
      reason: "canonical coordination authority must be initialized before mutation",
    };
  }
  if (head.status !== "loaded") return head;

  let commit: AuthorityStoreCommit;
  try {
    commit = prepareCoordinationProjectionCommit({
      ...input,
      projection: head.head,
    });
  } catch (error) {
    return {
      status: "failed",
      reason_code: "invalid_coordination_mutation",
      reason: error instanceof Error ? error.message : "invalid coordination mutation",
    };
  }
  const committed = await store.commitAuthority(commit);
  if (committed.status === "conflict" || committed.status === "ambiguous") {
    const readback = await store.readReceipt(input.operation_id);
    if (receiptProvesMutation(readback, expectedReceipt)) {
      return {
        status: "recovered",
        provider_revision: readback.provider_revision,
        cursor: readback.cursor,
      };
    }
    const mismatch = receiptIdentityMismatch(readback, expectedReceipt);
    if (mismatch !== null) return mismatch;
    return committed;
  }
  if (committed.status === "failed") {
    const readback = await store.readReceipt(input.operation_id);
    if (receiptProvesMutation(readback, expectedReceipt)) {
      return {
        status: "recovered",
        provider_revision: readback.provider_revision,
        cursor: readback.cursor,
      };
    }
    const mismatch = receiptIdentityMismatch(readback, expectedReceipt);
    if (mismatch !== null) return mismatch;
    return committed;
  }

  const readback = await store.readReceipt(input.operation_id);
  if (!receiptProvesMutation(readback, expectedReceipt)) {
    return {
      status: "failed",
      reason_code: "coordination_commit_readback_mismatch",
      reason: "applied coordination mutation lacks its exact durable receipt",
    };
  }
  return {
    status: "applied",
    provider_revision: readback.provider_revision,
    cursor: readback.cursor,
  };
}

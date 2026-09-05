import type { JsonObject } from "../effect_program.ts";
import type { AuthorityStore, AuthorityStoreCommit, AuthorityStoreReceiptResult } from "./authority_store.ts";
import {
  AuthorityStoreProtocolError,
  canonicalAuthorityBytes,
  canonicalAuthorityObject,
  canonicalAuthoritySha256,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";
import {
  TODO_DOMAIN_ITEM_SCHEMA,
  canonicalCoordinationTodoRecord,
  canonicalTodoDomainRecord,
} from "./coordination_state_contract.ts";
import {
  indexCoordinationProjection,
  prepareCoordinationProjectionCommit,
  validateCoordinationTodoReadModel,
} from "./coordination_projection.ts";
import { normalizeRegisteredTodoAgents, normalizeTodoAgent } from "./todo_agents.ts";

export const COORDINATION_TODO_UPDATE_REQUEST_SCHEMA =
  "loopx_local_coordination_todo_update_request_v0";
export const COORDINATION_TODO_UPDATE_RESULT_SCHEMA =
  "loopx_coordination_todo_update_result_v0";
export const COORDINATION_TODO_UPDATE_RECEIPT_SCHEMA =
  "loopx_coordination_todo_update_receipt_v0";

const IMMUTABLE_FIELDS = new Set([
  "schema_version", "todo_id", "role", "status", "done", "archive_state",
  "created_by", "claimed_by", "last_actor_agent_id", "updated_at",
]);
const PROJECTION_FIELDS = new Set(["index", "source_section"]);

export interface CoordinationTodoUpdateInput {
  readonly goal_id: string;
  readonly todo_id: string;
  readonly expected_role: string | null;
  readonly actor_agent_id: string | null;
  readonly registered_agents: readonly string[];
  readonly operation_id: string;
  readonly patch: JsonObject;
  readonly clear_fields: readonly string[];
  readonly dry_run: boolean;
  readonly now: Date;
}

export type CoordinationTodoUpdateResult = JsonObject & {
  readonly schema_version: typeof COORDINATION_TODO_UPDATE_RESULT_SCHEMA;
};

function failure(code: string, reason: string): CoordinationTodoUpdateResult {
  return {schema_version: COORDINATION_TODO_UPDATE_RESULT_SCHEMA, status: "failed",
    changed: false, reason_code: code, reason};
}

function normalizeInput(raw: CoordinationTodoUpdateInput): CoordinationTodoUpdateInput {
  const patch = canonicalAuthorityObject(raw.patch, "Todo update patch");
  const clearFields = raw.clear_fields.map((field, index) =>
    requireAuthorityStoreId(field, `clear_fields[${index}]`));
  if (Object.keys(patch).length + clearFields.length === 0) {
    throw new AuthorityStoreProtocolError("Todo update requires a non-empty patch");
  }
  if (new Set(clearFields).size !== clearFields.length) {
    throw new AuthorityStoreProtocolError("clear_fields must be unique");
  }
  const fields = [...Object.keys(patch), ...clearFields];
  const forbidden = fields.find((field) => IMMUTABLE_FIELDS.has(field) || PROJECTION_FIELDS.has(field));
  if (forbidden !== undefined) {
    throw new AuthorityStoreProtocolError(`Todo update cannot mutate ${forbidden}`);
  }
  if (Object.keys(patch).some((field) => clearFields.includes(field))) {
    throw new AuthorityStoreProtocolError("Todo update cannot patch and clear the same field");
  }
  if (raw.expected_role !== null && !["agent", "user"].includes(raw.expected_role)) {
    throw new AuthorityStoreProtocolError("expected_role must be agent or user");
  }
  if (typeof raw.dry_run !== "boolean") {
    throw new AuthorityStoreProtocolError("dry_run must be a boolean");
  }
  if (!(raw.now instanceof Date) || Number.isNaN(raw.now.valueOf())) {
    throw new AuthorityStoreProtocolError("now must be a valid Date");
  }
  return {...raw,
    goal_id: requireAuthorityStoreId(raw.goal_id, "goal id"),
    todo_id: requireAuthorityStoreId(raw.todo_id, "todo id"),
    operation_id: requireAuthorityStoreId(raw.operation_id, "operation id"),
    actor_agent_id: raw.actor_agent_id === null ? null :
      normalizeTodoAgent(raw.actor_agent_id, "actor_agent_id"),
    registered_agents: normalizeRegisteredTodoAgents(raw.registered_agents),
    patch, clear_fields: clearFields};
}

function replayUpdate(
  receipt: AuthorityStoreReceiptResult, input: CoordinationTodoUpdateInput,
  requestSha: string, status: "replayed" | "applied" | "recovered",
): CoordinationTodoUpdateResult | null {
  if (receipt.status === "missing") return null;
  if (receipt.status !== "found") {
    return {schema_version: COORDINATION_TODO_UPDATE_RESULT_SCHEMA, ...receipt, changed: false};
  }
  const original = receipt.receipts[0];
  if (receipt.receipts.length !== 1 ||
      original?.schema_version !== COORDINATION_TODO_UPDATE_RECEIPT_SCHEMA ||
      original.operation_id !== input.operation_id || original.goal_id !== input.goal_id ||
      original.todo_id !== input.todo_id || original.request_sha256 !== requestSha ||
      typeof original.changed !== "boolean") {
    return failure("coordination_operation_identity_mismatch",
      "operation id already names a different Todo update request");
  }
  return {schema_version: COORDINATION_TODO_UPDATE_RESULT_SCHEMA,
    status: status === "applied" && !original.changed ? "no_change" : status,
    changed: status !== "replayed" && original.changed,
    todo_id: input.todo_id, provider_revision: receipt.provider_revision,
    cursor: receipt.cursor, original_receipt: original,
    projection_delivery: original.changed ? "pending" : "not_required",
    projection_source: "committed_authority_journal"};
}

/** Update mutable Todo metadata from the canonical provider head. */
export async function executeCoordinationTodoUpdate(
  store: AuthorityStore, rawInput: CoordinationTodoUpdateInput,
): Promise<CoordinationTodoUpdateResult> {
  let input: CoordinationTodoUpdateInput;
  try { input = normalizeInput(rawInput); } catch (error) {
    return failure("invalid_coordination_todo_update",
      error instanceof Error ? error.message : "invalid Todo update");
  }
  const requestSha = canonicalAuthoritySha256({goal_id: input.goal_id,
    todo_id: input.todo_id, expected_role: input.expected_role,
    actor_agent_id: input.actor_agent_id, patch: input.patch,
    clear_fields: input.clear_fields, dry_run: input.dry_run});
  const replay = replayUpdate(await store.readReceipt(input.operation_id), input, requestSha, "replayed");
  if (replay !== null) return replay;
  if (input.actor_agent_id === null || !input.registered_agents.includes(input.actor_agent_id)) {
    return failure("actor_not_registered", "Todo update requires a registered actor");
  }
  const head = await store.loadAuthority();
  if (head.status !== "loaded") {
    return {schema_version: COORDINATION_TODO_UPDATE_RESULT_SCHEMA, ...head, changed: false};
  }
  let todo: JsonObject;
  let projection: ReturnType<typeof indexCoordinationProjection>;
  try {
    validateCoordinationTodoReadModel(head.head, input.goal_id);
    projection = indexCoordinationProjection(head.head, input.goal_id);
    const found = projection.todos.get(input.todo_id);
    if (found === undefined) return failure("todo_not_found", "canonical Todo is missing");
    todo = found;
  } catch (error) {
    return failure("invalid_coordination_projection",
      error instanceof Error ? error.message : "invalid coordination projection");
  }
  if (input.expected_role !== null && todo.role !== input.expected_role) {
    return failure("todo_role_mismatch", "Todo does not have the requested role");
  }
  if (todo.archive_state !== "active") {
    return failure("todo_archived", "Todo update requires an active Todo");
  }
  if (todo.role !== "agent" || todo.status === "done") {
    return failure("unsupported_todo_update_target",
      "native metadata update currently requires a non-completed agent Todo");
  }
  if (todo.claimed_by !== input.actor_agent_id) {
    return failure("update_owner_mismatch", "Todo update requires the current claim owner");
  }
  // Lease-bearing updates need an execution-instance fence in addition to the
  // actor identity. Until the native request carries that proof, fail closed.
  if (![undefined, "legacy", "soft_claim"].includes(head.head.handoff_mode as string | undefined) ||
      projection.leases.has(input.todo_id)) {
    return failure("update_lease_unsupported", "lease-bearing Todo updates are not yet supported");
  }
  const next: JsonObject = {...todo, ...input.patch};
  for (const field of input.clear_fields) delete next[field];
  next.last_actor_agent_id = input.actor_agent_id;
  next.updated_at = input.now.toISOString().replace(/\.\d{3}Z$/u, "Z");
  try {
    if (todo.schema_version === TODO_DOMAIN_ITEM_SCHEMA) {
      canonicalTodoDomainRecord(next, "updated Todo");
    } else {
      canonicalCoordinationTodoRecord(next, "updated Todo");
    }
  } catch (error) {
    return failure("invalid_coordination_todo_update",
      error instanceof Error ? error.message : "invalid updated Todo");
  }
  const changedBeforeAudit = {...next};
  delete changedBeforeAudit.last_actor_agent_id;
  delete changedBeforeAudit.updated_at;
  const originalBeforeAudit = {...todo};
  delete originalBeforeAudit.last_actor_agent_id;
  delete originalBeforeAudit.updated_at;
  const changed = !canonicalAuthorityBytes(changedBeforeAudit).equals(
    canonicalAuthorityBytes(originalBeforeAudit));
  if (!changed) {
    next.last_actor_agent_id = todo.last_actor_agent_id;
    next.updated_at = todo.updated_at;
  }
  if (input.dry_run) return {schema_version: COORDINATION_TODO_UPDATE_RESULT_SCHEMA,
    status: changed ? "planned" : "no_change", changed, todo_id: input.todo_id,
    provider_revision: head.provider_revision, cursor: head.cursor, dry_run: true};
  const commit: AuthorityStoreCommit = changed ? prepareCoordinationProjectionCommit({
    goal_id: input.goal_id, operation_id: input.operation_id,
    expected_provider_revision: head.provider_revision, projection: head.head,
    mutations: [{kind: "todo_upsert", todo: next, clear_fields: input.clear_fields}],
  }) : {operation_id: input.operation_id,
    expected_provider_revision: head.provider_revision, next_projection: head.head,
    events: [], receipts: []};
  commit.receipts = [{schema_version: COORDINATION_TODO_UPDATE_RECEIPT_SCHEMA,
    operation_id: input.operation_id, goal_id: input.goal_id,
    todo_id: input.todo_id, request_sha256: requestSha, changed}];
  const committed = await store.commitAuthority(commit);
  const readback = replayUpdate(await store.readReceipt(input.operation_id), input, requestSha,
    committed.status === "applied" ? "applied" : "recovered");
  if (readback !== null) return readback;
  return committed.status === "applied"
    ? failure("coordination_commit_readback_mismatch", "applied update lacks its durable receipt")
    : {schema_version: COORDINATION_TODO_UPDATE_RESULT_SCHEMA, ...committed, changed: false};
}

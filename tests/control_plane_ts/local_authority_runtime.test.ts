import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import { canonicalAuthorityBytes } from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {
  TODO_CANONICAL_READ_RECORD_FIELDS,
  TODO_CANONICAL_READ_RECORD_SCHEMA,
} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import {
  LOCAL_COORDINATION_PROMOTION_REQUEST_SCHEMA,
  LOCAL_COORDINATION_MUTATION_REQUEST_SCHEMA,
  LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA,
  LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA,
  listLocalCoordinationTodos,
  mutateLocalCoordinationAuthority,
  promoteLocalCoordinationAuthority,
  readLocalCoordinationTodo,
} from "../../loopx/control_plane/coordination/local_authority_runtime.ts";
import {
  checkLegacyCoordinationWriteAllowed,
  engageLegacyCoordinationWriterFence,
  LEGACY_COORDINATION_WRITER_FENCE_ENGAGE_REQUEST_SCHEMA,
  LEGACY_COORDINATION_WRITER_FENCE_SCHEMA,
  LEGACY_COORDINATION_WRITE_CHECK_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/legacy_writer_fence.ts";
import {
  bootstrapCoordinationRuntimeShadow,
  commitCoordinationRuntimeShadow,
  COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/runtime_shadow.ts";
import { executeTaskLeaseAcquire } from "../../loopx/control_plane/work_items/task_lease_acquire.ts";
import {
  TASK_LEASE_LIFECYCLE_REQUEST_SCHEMA_VERSION,
  executeTaskLeaseLifecycle,
} from "../../loopx/control_plane/work_items/task_lease_lifecycle.ts";

function sha256(value: unknown): string {
  return createHash("sha256").update(canonicalAuthorityBytes(value)).digest("hex");
}

function withTodoReadModel<T extends Record<string, unknown>>(projection: T): T {
  const todos = projection.todos as Record<string, unknown>[];
  return {
    ...projection,
    todo_read_model: {
      schema_version: TODO_CANONICAL_READ_RECORD_SCHEMA,
      todo_count: todos.length,
      records_sha256: sha256(todos),
      contract_fields: [...TODO_CANONICAL_READ_RECORD_FIELDS],
    },
  };
}

function todoRecord(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema_version: "todo_item_v0",
    todo_id: "todo_a",
    role: "agent",
    status: "open",
    done: false,
    text: "Qualify canonical Todo semantics",
    archive_state: "active",
    source_section: "Agent Todo",
    ...overrides,
  };
}

async function qualifiedShadow(root: string) {
  const baseline = withTodoReadModel({
    goal_id: "goal-a",
    todos: [todoRecord()],
    leases: [],
  });
  const bootstrapped = await bootstrapCoordinationRuntimeShadow({
    schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "bootstrap:goal-a:state-0",
    source_version: "state:0",
    projection: baseline,
  });
  assert.equal(bootstrapped.status, "applied");
  const projection = withTodoReadModel({
    ...baseline,
    todos: [todoRecord({ claimed_by: "agent-a" })],
  });
  const mirrored = await commitCoordinationRuntimeShadow({
    schema_version: COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "todo:goal-a:todo_a:claim-1",
    event_kind: "todo_claim",
    source_version: "state:1",
    projection,
  });
  assert.equal(mirrored.status, "applied");
  return { projection, providerRevision: String(mirrored.provider_revision) };
}

function promotionRequest(
  root: string,
  projection: Record<string, unknown>,
  providerRevision: string,
) {
  const digest = sha256(projection);
  return {
    schema_version: LOCAL_COORDINATION_PROMOTION_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "promote:goal-a:state-1",
    expected_shadow_provider_revision: providerRevision,
    expected_shadow_projection_sha256: digest,
    minimum_operations: 1,
    required_event_kinds: ["todo_claim"],
    writer_fence: {
      schema_version: LEGACY_COORDINATION_WRITER_FENCE_SCHEMA,
      state: "engaged",
      goal_id: "goal-a",
      fence_id: "legacy-writer-fence:goal-a:state-1",
      source_version: "state:1",
      source_projection_sha256: digest,
      expected_shadow_provider_revision: providerRevision,
    },
  };
}

async function engageFence(request: ReturnType<typeof promotionRequest>) {
  const result = await engageLegacyCoordinationWriterFence({
    schema_version: LEGACY_COORDINATION_WRITER_FENCE_ENGAGE_REQUEST_SCHEMA,
    runtime_root: request.runtime_root,
    goal_id: request.goal_id,
    fence: request.writer_fence,
  });
  assert.equal(result.status, "applied");
}

test("legacy write guard flips from allowed to fail-closed after the durable fence", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-legacy-writer-fence-"));
  const shadow = await qualifiedShadow(root);
  const request = promotionRequest(root, shadow.projection, shadow.providerRevision);
  const check = {
    schema_version: LEGACY_COORDINATION_WRITE_CHECK_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
  };
  assert.equal((await checkLegacyCoordinationWriteAllowed(check)).status, "allowed");
  await engageFence(request);
  const replayed = await engageLegacyCoordinationWriterFence({
    schema_version: LEGACY_COORDINATION_WRITER_FENCE_ENGAGE_REQUEST_SCHEMA,
    runtime_root: request.runtime_root,
    goal_id: request.goal_id,
    fence: request.writer_fence,
  });
  assert.equal(replayed.status, "replayed");
  const conflict = await engageLegacyCoordinationWriterFence({
    schema_version: LEGACY_COORDINATION_WRITER_FENCE_ENGAGE_REQUEST_SCHEMA,
    runtime_root: request.runtime_root,
    goal_id: request.goal_id,
    fence: { ...request.writer_fence, fence_id: "legacy-writer-fence:other" },
  });
  assert.equal(conflict.status, "conflict");
  const blocked = await checkLegacyCoordinationWriteAllowed(check);
  assert.equal(blocked.status, "blocked");
  assert.equal(blocked.reason_code, "legacy_coordination_writer_fenced");
  assert.equal(blocked.authority_mode, "file_v0");
});

test("explicit local promotion requires qualified shadow and creates replayable canonical authority", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-promote-"));
  const shadow = await qualifiedShadow(root);
  const request = promotionRequest(root, shadow.projection, shadow.providerRevision);
  await engageFence(request);

  const applied = await promoteLocalCoordinationAuthority(request);
  assert.equal(applied.status, "applied");
  assert.equal(applied.legacy_writer_fenced, true);
  assert.equal(applied.legacy_fallback_used, false);
  assert.equal(applied.canonical_authority, "file_v0");

  const advanced = await mutateLocalCoordinationAuthority({
    schema_version: LOCAL_COORDINATION_MUTATION_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "todo:goal-a:todo_a:advance-after-promotion",
    expected_provider_revision: applied.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: todoRecord({ status: "in_progress", claimed_by: "agent-a" }),
    }],
  });
  assert.equal(advanced.status, "applied");

  const partialReplacement = await mutateLocalCoordinationAuthority({
    schema_version: LOCAL_COORDINATION_MUTATION_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "todo:goal-a:todo_a:partial-after-promotion",
    expected_provider_revision: advanced.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: {
        schema_version: "todo_item_v0",
        todo_id: "todo_a",
        role: "agent",
        status: "done",
        done: true,
        text: "Qualify canonical Todo semantics",
        archive_state: "active",
        source_section: "Agent Todo",
      },
    }],
  });
  assert.equal(partialReplacement.status, "failed");
  assert.equal(partialReplacement.reason_code, "invalid_coordination_mutation");
  assert.match(String(partialReplacement.reason ?? ""), /omits existing fields: claimed_by/);
  const unchanged = await readLocalCoordinationTodo({
    schema_version: LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_a",
  });
  assert.equal(unchanged.status, "found");
  assert.equal((unchanged.todo as Record<string, unknown>).claimed_by, "agent-a");
  assert.equal((unchanged.todo as Record<string, unknown>).status, "in_progress");

  const replayed = await promoteLocalCoordinationAuthority(request);
  assert.equal(replayed.status, "replayed");
  assert.equal(replayed.provider_revision, applied.provider_revision);

  const read = await readLocalCoordinationTodo({
    schema_version: LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_a",
  });
  assert.equal(read.status, "found");
  assert.equal((read.todo as Record<string, unknown>).claimed_by, "agent-a");
  assert.equal((read.todo as Record<string, unknown>).status, "in_progress");
  assert.equal(read.legacy_fallback_used, false);
});

test("local promotion fences shadow revision, digest, and writer-fence identity", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-promote-fence-"));
  const shadow = await qualifiedShadow(root);
  const request = promotionRequest(root, shadow.projection, shadow.providerRevision);

  const missingFence = await promoteLocalCoordinationAuthority(request);
  assert.equal(missingFence.status, "failed");
  assert.equal(missingFence.reason_code, "local_authority_writer_fence_not_verified");
  await engageFence(request);

  const staleRevision = await promoteLocalCoordinationAuthority({
    ...request,
    expected_shadow_provider_revision: "file:stale",
  });
  assert.equal(staleRevision.status, "failed");
  assert.equal(staleRevision.reason_code, "local_authority_writer_fence_revision_mismatch");

  const mismatchedFence = await promoteLocalCoordinationAuthority({
    ...request,
    writer_fence: { ...request.writer_fence, source_projection_sha256: "0".repeat(64) },
  });
  assert.equal(mismatchedFence.status, "failed");
  assert.equal(
    mismatchedFence.reason_code,
    "local_authority_writer_fence_projection_mismatch",
  );

  const unqualified = await promoteLocalCoordinationAuthority({
    ...request,
    minimum_operations: 2,
  });
  assert.equal(unqualified.status, "failed");
  assert.equal(unqualified.reason_code, "local_authority_shadow_not_qualified");
  const canonical = new FileAuthorityStore(join(root, "authority", "file-v0"), "goal-a");
  assert.equal((await canonical.loadAuthority()).status, "missing");
});

test("promotion and provider list fail closed without exact Todo consumer semantics", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-semantic-fence-"));
  const incomplete = {
    goal_id: "goal-a",
    todos: [{ todo_id: "todo_a", role: "agent", status: "open" }],
    leases: [],
  };
  const bootstrapped = await bootstrapCoordinationRuntimeShadow({
    schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "bootstrap:goal-a:incomplete",
    source_version: "state:0",
    projection: incomplete,
  });
  assert.equal(bootstrapped.status, "applied");
  const mirrored = await commitCoordinationRuntimeShadow({
    schema_version: COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "todo:goal-a:incomplete",
    event_kind: "todo_update",
    source_version: "state:1",
    projection: incomplete,
  });
  assert.equal(mirrored.status, "applied");
  const request = promotionRequest(root, incomplete, String(mirrored.provider_revision));
  request.required_event_kinds = ["todo_update"];
  await engageFence(request);
  const rejected = await promoteLocalCoordinationAuthority(request);
  assert.equal(rejected.status, "failed");
  assert.equal(rejected.reason_code, "local_authority_shadow_not_qualified");

  const canonical = new FileAuthorityStore(join(root, "authority", "file-v0"), "goal-a");
  const committed = await canonical.commitAuthority({
    expected_provider_revision: null,
    operation_id: "unsafe:test-only",
    events: [{ schema_version: "test_v0" }],
    next_projection: incomplete,
    receipts: [],
  });
  assert.equal(committed.status, "applied");
  const listed = await listLocalCoordinationTodos({
    schema_version: LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
  });
  assert.equal(listed.status, "failed");
  assert.equal(listed.reason_code, "invalid_local_coordination_todo_list_request");
});

test("local canonical runtime reads and mutates only the provider head", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-runtime-"));
  const store = new FileAuthorityStore(join(root, "authority", "file-v0"), "goal-a");
  const initial = await store.commitAuthority({
    expected_provider_revision: null,
    operation_id: "promote:goal-a",
    events: [{ schema_version: "promotion_v0" }],
    next_projection: withTodoReadModel({
      goal_id: "goal-a",
      source_authority: "file_v0",
      todos: [todoRecord()],
      leases: [],
    }),
    receipts: [],
  });
  assert.equal(initial.status, "applied");
  if (initial.status !== "applied") return;

  const before = await readLocalCoordinationTodo({
    schema_version: LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_a",
  });
  assert.equal(before.status, "found");
  assert.equal(before.decision_read_from_provider, true);
  assert.equal(before.legacy_fallback_used, false);

  const mutation = await mutateLocalCoordinationAuthority({
    schema_version: LOCAL_COORDINATION_MUTATION_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: "claim:goal-a:todo_a:1",
    expected_provider_revision: initial.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: todoRecord({ claimed_by: "agent-a" }),
    }],
  });
  assert.equal(mutation.status, "applied");
  assert.equal(mutation.decision_read_from_provider, true);
  assert.equal(mutation.legacy_fallback_used, false);

  const after = await readLocalCoordinationTodo({
    schema_version: LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_a",
  });
  assert.equal((after.todo as Record<string, unknown>).claimed_by, "agent-a");

  const listed = await listLocalCoordinationTodos({
    schema_version: LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
  });
  assert.equal(listed.status, "loaded");
  assert.deepEqual(listed.todo_ids, ["todo_a"]);
  assert.equal((listed.todos as Record<string, unknown>[])[0]?.claimed_by, "agent-a");
  assert.equal(listed.decision_read_from_provider, true);
  assert.equal(listed.legacy_fallback_used, false);
});

test("local canonical runtime never falls back when provider state is missing", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-missing-"));
  const result = await readLocalCoordinationTodo({
    schema_version: LOCAL_COORDINATION_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_a",
  });
  assert.equal(result.status, "missing");
  assert.equal(result.decision_read_from_provider, true);
  assert.equal(result.legacy_fallback_used, false);
});

test("engaged promotion fence blocks every native legacy task-lease writer", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-lease-fence-"));
  const shadow = await qualifiedShadow(root);
  const request = promotionRequest(root, shadow.projection, shadow.providerRevision);
  await engageFence(request);

  const authorityPath = join(root, "authority-source.json");
  const authorityContent = "authority-v1";
  await writeFile(authorityPath, authorityContent, "utf8");
  const authority = {
    handoff_mode: "hard_lease",
    registered_agent_candidates: [["agent-a"]],
    todos: [{
      todo_id: "todo_abc",
      status: "open",
      claimed_by: "agent-a",
      role: "agent",
      task_class: "advancement_task",
    }],
    todo_projection_error: null,
    source_receipts: [{
      source_id: "authority",
      path: authorityPath,
      state: "file",
      sha256: createHash("sha256").update(authorityContent).digest("hex"),
    }],
  };
  const acquire = await executeTaskLeaseAcquire({
    schema_version: "loopx_task_lease_acquire_native_v0",
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_abc",
    owner: "agent-a",
    idempotency_key: "lease:fenced-acquire",
    write_scopes: [],
    ttl_seconds: 60,
    expected_version: null,
    authority,
  });
  assert.equal(acquire.ok, false);
  assert.equal(acquire.error_code, "legacy_coordination_writer_fenced");

  const renew = await executeTaskLeaseLifecycle({
    schema_version: TASK_LEASE_LIFECYCLE_REQUEST_SCHEMA_VERSION,
    operation: "renew",
    runtime_root: root,
    goal_id: "goal-a",
    todo_id: "todo_abc",
    owner: "agent-a",
    idempotency_key: "lease:fenced-renew",
    expected_version: 1,
    ttl_seconds: 60,
    new_owner: null,
    new_idempotency_key: null,
    authority,
  });
  assert.equal(renew.ok, false);
  assert.equal(renew.error_code, "legacy_coordination_writer_fenced");
});

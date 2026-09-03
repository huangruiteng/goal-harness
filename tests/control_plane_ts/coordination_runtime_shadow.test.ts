import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { canonicalAuthorityBytes } from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import {
  TODO_CANONICAL_READ_RECORD_FIELDS,
  TODO_CANONICAL_READ_RECORD_SCHEMA,
} from "../../loopx/control_plane/coordination/coordination_projection.ts";

import type {
  AuthorityStoreCommit,
  AuthorityStoreCommitResult,
} from "../../loopx/control_plane/coordination/authority_store.ts";
import {
  FileAuthorityStore,
  type FileAuthorityArchiveResult,
} from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  bootstrapCoordinationRuntimeShadow,
  commitCoordinationRuntimeShadow,
  inspectCoordinationRuntimeShadow,
  qualifyCoordinationRuntimeShadow,
  readCoordinationRuntimeShadowTodoCandidate,
  rollbackCoordinationRuntimeShadow,
  COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/runtime_shadow.ts";

function withTodoReadModel<T extends Record<string, unknown>>(projection: T): T {
  const todos = projection.todos as Record<string, unknown>[];
  return {
    ...projection,
    todo_read_model: {
      schema_version: TODO_CANONICAL_READ_RECORD_SCHEMA,
      todo_count: todos.length,
      records_sha256: createHash("sha256").update(canonicalAuthorityBytes(todos)).digest("hex"),
      contract_fields: [...TODO_CANONICAL_READ_RECORD_FIELDS],
    },
  };
}

async function request(root: string, operationId = "todo:goal-a:todo_one:v1") {
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: operationId,
    event_kind: "todo_claim",
    source_version: "state:1",
    projection: withTodoReadModel({
      schema_version: "loopx_coordination_shadow_projection_v0",
      goal_id: "goal-a",
      todos: [{
        schema_version: "todo_item_v0",
        todo_id: "todo_one",
        role: "agent",
        status: "open",
        done: false,
        text: "Qualify shadow semantics",
        archive_state: "active",
        source_section: "Agent Todo",
        claimed_by: "agent-a",
      }],
      leases: [],
    }),
  };
}

async function bootstrapRequest(root: string) {
  const commit = await request(root);
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: commit.goal_id,
    operation_id: "bootstrap:goal-a:state-1",
    source_version: "state:1",
    projection: commit.projection,
  };
}

test("runtime shadow bootstrap records a replayable baseline with no receipt", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-bootstrap-"));
  const input = await bootstrapRequest(root);

  const applied = await bootstrapCoordinationRuntimeShadow(input);
  assert.equal(applied.status, "applied");
  assert.equal(applied.cursor, "1");
  assert.equal(applied.mode_declaration, "legacy_canonical_shadow");
  assert.equal(applied.bootstrap_receipts_empty, true);
  assert.equal(applied.decision_read_from_shadow, false);

  const replayed = await bootstrapCoordinationRuntimeShadow(input);
  assert.equal(replayed.status, "replayed");
  assert.equal(replayed.provider_revision, applied.provider_revision);

  const store = new FileAuthorityStore(
    join(root, "authority-shadow", "file-v0"),
    "goal-a",
  );
  const receipt = await store.readReceipt(input.operation_id);
  assert.equal(receipt.status, "found");
  if (receipt.status === "found") assert.deepEqual(receipt.receipts, []);
  const scan = await store.scanCommitted(null, 1);
  assert.equal(scan.status, "page");
  if (scan.status === "page") {
    assert.equal(scan.transactions[0]?.receipts.length, 0);
    assert.equal(
      (scan.transactions[0]?.events[0] as Record<string, unknown>).source_version,
      "state:1",
    );
  }

  const next = await request(root, "todo:goal-a:todo_one:v2");
  const committed = await commitCoordinationRuntimeShadow(next);
  assert.equal(committed.status, "applied");
  assert.equal(committed.cursor, "2");
});

test("runtime shadow bootstrap fails closed against different initialized content", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-bootstrap-conflict-"));
  assert.equal((await commitCoordinationRuntimeShadow(await request(root))).status, "applied");

  const result = await bootstrapCoordinationRuntimeShadow(await bootstrapRequest(root));
  assert.equal(result.status, "failed");
  assert.equal(result.reason_code, "shadow_bootstrap_identity_mismatch");
  assert.equal(result.primary_writeback_preserved, true);
});

test("runtime shadow bootstrap reconciles an applied commit whose response was lost", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-bootstrap-ambiguous-"));
  class LostBootstrapResponseStore extends FileAuthorityStore {
    override async commitAuthority(
      commit: AuthorityStoreCommit,
    ): Promise<AuthorityStoreCommitResult> {
      const result = await super.commitAuthority(commit);
      return result.status === "applied"
        ? {
          status: "ambiguous",
          reason_code: "simulated_response_loss",
          reason: "commit response was lost",
        }
        : result;
    }
  }

  const result = await bootstrapCoordinationRuntimeShadow(
    await bootstrapRequest(root),
    {
      createStore: (directory, goalId) =>
        new LostBootstrapResponseStore(directory, goalId),
    },
  );
  assert.equal(result.status, "recovered");
  assert.equal(result.cursor, "1");
  assert.equal(result.bootstrap_receipts_empty, true);
});

test("runtime shadow rollback quarantines and exactly replays one fenced lineage", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-rollback-"));
  const bootstrap = await bootstrapCoordinationRuntimeShadow(await bootstrapRequest(root));
  assert.equal(bootstrap.status, "applied");
  const rollbackRequest = {
    schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: `rollback:goal-a:${String(bootstrap.provider_revision)}`,
    expected_provider_revision: bootstrap.provider_revision,
  };

  const applied = await rollbackCoordinationRuntimeShadow(rollbackRequest);
  assert.equal(applied.status, "applied");
  assert.equal(applied.active_shadow_removed, true);
  assert.equal(applied.archive_retained, true);
  assert.equal(applied.decision_read_from_shadow, false);

  const store = new FileAuthorityStore(
    join(root, "authority-shadow", "file-v0"),
    "goal-a",
  );
  assert.equal((await store.loadAuthority()).status, "missing");
  assert.equal(
    (await readdir(join(root, "authority-shadow", "file-v0", "rollback"))).length,
    1,
  );

  const replayed = await rollbackCoordinationRuntimeShadow(rollbackRequest);
  assert.equal(replayed.status, "replayed");
  assert.equal(replayed.archive_id, applied.archive_id);
});

test("runtime shadow rollback fences revision drift and operation reuse", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-rollback-fence-"));
  const bootstrapInput = await bootstrapRequest(root);
  const first = await bootstrapCoordinationRuntimeShadow(bootstrapInput);
  assert.equal(first.status, "applied");
  const rollbackRequest = {
    schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: `rollback:goal-a:${String(first.provider_revision)}`,
    expected_provider_revision: first.provider_revision,
  };
  const stale = await rollbackCoordinationRuntimeShadow({
    ...rollbackRequest,
    expected_provider_revision: "file:stale-revision",
  });
  assert.equal(stale.status, "failed");
  assert.equal(stale.reason_code, "provider_revision_mismatch");

  assert.equal((await rollbackCoordinationRuntimeShadow(rollbackRequest)).status, "applied");
  const second = await bootstrapCoordinationRuntimeShadow({
    ...bootstrapInput,
    operation_id: "bootstrap:goal-a:state-2",
    source_version: "state:2",
  });
  assert.equal(second.status, "applied");

  const reused = await rollbackCoordinationRuntimeShadow(rollbackRequest);
  assert.equal(reused.status, "failed");
  assert.equal(reused.reason_code, "archive_operation_reused_after_rebootstrap");
  assert.equal(reused.primary_writeback_preserved, true);
});

test("runtime shadow rollback reconciles a quarantined lineage after response loss", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-rollback-ambiguous-"));
  const bootstrap = await bootstrapCoordinationRuntimeShadow(await bootstrapRequest(root));
  assert.equal(bootstrap.status, "applied");
  const rollbackRequest = {
    schema_version: COORDINATION_RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: `rollback:goal-a:${String(bootstrap.provider_revision)}`,
    expected_provider_revision: bootstrap.provider_revision,
  };
  class LostRollbackResponseStore extends FileAuthorityStore {
    override async archiveAuthorityDocument(
      expectedProviderRevision: string,
      operationId: string,
    ): Promise<FileAuthorityArchiveResult> {
      const result = await super.archiveAuthorityDocument(
        expectedProviderRevision,
        operationId,
      );
      return result.status === "applied"
        ? {
          status: "ambiguous",
          reason_code: "simulated_response_loss",
          reason: "rollback response was lost",
        }
        : result;
    }
  }

  const ambiguous = await rollbackCoordinationRuntimeShadow(
    rollbackRequest,
    {
      createFileStore: (directory, goalId) =>
        new LostRollbackResponseStore(directory, goalId),
    },
  );
  assert.equal(ambiguous.status, "ambiguous");
  assert.equal(ambiguous.reconciliation_required, true);

  const recovered = await rollbackCoordinationRuntimeShadow(rollbackRequest);
  assert.equal(recovered.status, "replayed");
  assert.equal(recovered.archive_retained, true);
});

test("runtime shadow commits and exactly replays one legacy mutation", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-"));
  const input = await request(root);

  const applied = await commitCoordinationRuntimeShadow(input);
  assert.equal(applied.status, "applied");
  assert.equal(applied.cursor, "1");
  assert.equal(applied.primary_writeback_preserved, true);
  assert.equal(applied.decision_read_from_shadow, false);
  assert.equal((applied.parity as Record<string, unknown>).receipt_matches, true);
  assert.deepEqual(
    (applied.parity as Record<string, unknown>).projection_readback,
    {
      verified: true,
      status: "matched_current_head",
      projection_matches: true,
      provider_revision: applied.provider_revision,
    },
  );

  const replayed = await commitCoordinationRuntimeShadow(input);
  assert.equal(replayed.status, "replayed");
  assert.equal(replayed.cursor, "1");

  const store = new FileAuthorityStore(
    join(root, "authority-shadow", "file-v0"),
    "goal-a",
  );
  const scan = await store.scanCommitted(null, 10);
  assert.equal(scan.status, "page");
  if (scan.status === "page") assert.equal(scan.transactions.length, 1);
});

test("runtime shadow rejects operation-id content drift without changing history", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-drift-"));
  const input = await request(root);
  assert.equal((await commitCoordinationRuntimeShadow(input)).status, "applied");

  const drifted = structuredClone(input);
  (drifted.projection.todos[0] as Record<string, unknown>).claimed_by = "agent-b";
  const result = await commitCoordinationRuntimeShadow(drifted);
  assert.equal(result.status, "failed");
  assert.equal(result.reason_code, "shadow_operation_identity_mismatch");
  assert.equal(result.primary_writeback_preserved, true);

  const store = new FileAuthorityStore(
    join(root, "authority-shadow", "file-v0"),
    "goal-a",
  );
  const scan = await store.scanCommitted(null, 10);
  assert.equal(scan.status, "page");
  if (scan.status === "page") assert.equal(scan.transactions.length, 1);
});

test("runtime shadow reconciles an applied commit whose response was lost", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-ambiguous-"));
  class LostResponseStore extends FileAuthorityStore {
    override async commitAuthority(
      commit: AuthorityStoreCommit,
    ): Promise<AuthorityStoreCommitResult> {
      const result = await super.commitAuthority(commit);
      return result.status === "applied"
        ? {
          status: "ambiguous",
          reason_code: "simulated_response_loss",
          reason: "commit response was lost",
        }
        : result;
    }
  }
  const result = await commitCoordinationRuntimeShadow(
    await request(root),
    {
      createStore: (directory, goalId) =>
        new LostResponseStore(directory, goalId),
    },
  );
  assert.equal(result.status, "recovered");
  assert.equal(result.cursor, "1");
  assert.equal(result.primary_writeback_preserved, true);
});

test("runtime shadow isolates provider failure from primary truth", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-failure-"));
  class FailedStore extends FileAuthorityStore {
    override async commitAuthority(): Promise<AuthorityStoreCommitResult> {
      return {
        status: "failed",
        reason_code: "simulated_unavailable",
        reason: "shadow is offline",
      };
    }
  }
  const result = await commitCoordinationRuntimeShadow(
    await request(root),
    {
      createStore: (directory, goalId) => new FailedStore(directory, goalId),
    },
  );
  assert.equal(result.status, "failed");
  assert.equal(result.reason_code, "simulated_unavailable");
  assert.equal(result.primary_writeback_preserved, true);
  assert.equal(result.decision_read_from_shadow, false);
});

test("runtime shadow inspection reports missing, matched, and drifted evidence", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-inspect-"));
  const input = await request(root);
  const inspection = {
    schema_version: COORDINATION_RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: input.goal_id,
    projection: input.projection,
  };

  const missing = await inspectCoordinationRuntimeShadow(inspection);
  assert.equal(missing.status, "missing");
  assert.equal(missing.bootstrap_required, true);
  assert.equal(missing.parity_matches, false);
  assert.equal(missing.decision_read_from_shadow, false);

  assert.equal((await commitCoordinationRuntimeShadow(input)).status, "applied");
  const matched = await inspectCoordinationRuntimeShadow(inspection);
  assert.equal(matched.status, "matched");
  assert.equal(matched.bootstrap_required, false);
  assert.equal(matched.parity_matches, true);
  assert.equal(matched.decision_read_from_shadow, false);

  const driftedInput = structuredClone(inspection);
  (driftedInput.projection.todos[0] as Record<string, unknown>).claimed_by = "agent-b";
  const drifted = await inspectCoordinationRuntimeShadow(driftedInput);
  assert.equal(drifted.status, "drifted");
  assert.equal(drifted.parity_matches, false);
  assert.notEqual(
    drifted.expected_projection_sha256,
    drifted.observed_projection_sha256,
  );
  assert.equal(drifted.decision_read_from_shadow, false);
});

test("runtime shadow Todo read candidate requires exact legacy parity", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-todo-read-"));
  const input = await request(root);
  const readRequest = {
    schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: input.goal_id,
    todo_id: "todo_one",
    projection: input.projection,
  };

  const missing = await readCoordinationRuntimeShadowTodoCandidate(readRequest);
  assert.equal(missing.status, "missing");
  assert.equal(missing.read_candidate_qualified, false);

  assert.equal((await commitCoordinationRuntimeShadow(input)).status, "applied");
  const matched = await readCoordinationRuntimeShadowTodoCandidate(readRequest);
  assert.equal(matched.status, "matched");
  assert.equal(matched.read_candidate_qualified, true);
  assert.equal(matched.decision_read_from_shadow, false);
  assert.deepEqual(matched.todo, input.projection.todos[0]);
  assert.deepEqual(matched.todo_ids, ["todo_one"]);

  const driftedProjection = structuredClone(input.projection);
  (driftedProjection.todos[0] as Record<string, unknown>).claimed_by = "agent-b";
  const drifted = await readCoordinationRuntimeShadowTodoCandidate({
    ...readRequest,
    projection: driftedProjection,
  });
  assert.equal(drifted.status, "drifted");
  assert.equal(drifted.read_candidate_qualified, false);
  assert.equal(drifted.parity_matches, false);
});

test("runtime shadow Todo read candidate fails closed for missing or duplicate Todo ids", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-todo-read-invalid-"));
  const input = await request(root);
  assert.equal((await commitCoordinationRuntimeShadow(input)).status, "applied");

  const absent = await readCoordinationRuntimeShadowTodoCandidate({
    schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: input.goal_id,
    todo_id: "todo_absent",
    projection: input.projection,
  });
  assert.equal(absent.status, "todo_missing");
  assert.equal(absent.read_candidate_qualified, false);

  const duplicateProjection = structuredClone(input.projection);
  duplicateProjection.todos.push(structuredClone(duplicateProjection.todos[0]!));
  const duplicateRoot = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-todo-duplicate-"));
  assert.equal((await commitCoordinationRuntimeShadow({
    ...input,
    runtime_root: duplicateRoot,
    operation_id: "todo:goal-a:duplicate:v1",
    projection: duplicateProjection,
  })).status, "applied");
  const duplicate = await readCoordinationRuntimeShadowTodoCandidate({
    schema_version: COORDINATION_RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA,
    runtime_root: duplicateRoot,
    goal_id: input.goal_id,
    todo_id: "todo_one",
    projection: duplicateProjection,
  });
  assert.equal(duplicate.status, "failed");
  assert.equal(duplicate.reason_code, "shadow_todo_read_unavailable");
  assert.equal(duplicate.read_candidate_qualified, false);
});

test("runtime shadow qualification requires sustained operation and event coverage", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-runtime-shadow-qualify-"));
  const bootstrap = await bootstrapRequest(root);
  assert.equal((await bootstrapCoordinationRuntimeShadow(bootstrap)).status, "applied");

  const first = await request(root, "todo:goal-a:todo_one:v2");
  assert.equal((await commitCoordinationRuntimeShadow(first)).status, "applied");
  const second = await request(root, "lease:goal-a:todo_one:v3");
  second.event_kind = "task_lease_acquire";
  second.source_version = "state:3";
  assert.equal((await commitCoordinationRuntimeShadow(second)).status, "applied");
  const third = await request(root, "todo:goal-a:todo_one:v4");
  third.source_version = "state:4";
  assert.equal((await commitCoordinationRuntimeShadow(third)).status, "applied");

  const input = {
    schema_version: COORDINATION_RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    projection: third.projection,
    minimum_operations: 3,
    required_event_kinds: ["todo_claim", "task_lease_acquire"],
  };
  const qualified = await qualifyCoordinationRuntimeShadow(input);
  assert.equal(qualified.status, "qualified");
  assert.equal(qualified.qualified, true);
  assert.equal(qualified.parity_matches, true);
  assert.equal(
    (qualified.evidence as Record<string, unknown>).operation_count,
    3,
  );
  assert.deepEqual(
    (qualified.evidence as Record<string, unknown>).observed_event_kinds,
    ["task_lease_acquire", "todo_claim"],
  );
  assert.equal(qualified.decision_read_from_shadow, false);

  const insufficient = await qualifyCoordinationRuntimeShadow({
    ...input,
    minimum_operations: 4,
  });
  assert.equal(insufficient.status, "insufficient_evidence");
  assert.equal(insufficient.qualified, false);

  const missingKind = await qualifyCoordinationRuntimeShadow({
    ...input,
    required_event_kinds: ["todo_complete"],
  });
  assert.equal(missingKind.status, "insufficient_evidence");
  assert.deepEqual(
    (missingKind.evidence as Record<string, unknown>).missing_required_event_kinds,
    ["todo_complete"],
  );

  const driftedProjection = structuredClone(third.projection);
  (driftedProjection.todos[0] as Record<string, unknown>).status = "done";
  const drifted = await qualifyCoordinationRuntimeShadow({
    ...input,
    projection: driftedProjection,
  });
  assert.equal(drifted.status, "drifted");
  assert.equal(drifted.qualified, false);
});

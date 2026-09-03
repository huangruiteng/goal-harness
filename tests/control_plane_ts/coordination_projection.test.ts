import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type {
  AuthorityStoreCommit,
  AuthorityStoreCommitResult,
} from "../../loopx/control_plane/coordination/authority_store.ts";
import {
  commitCoordinationProjectionMutation,
  indexCoordinationProjection,
  indexCoordinationProjectionTodos,
  prepareCoordinationProjectionCommit,
  reduceCoordinationProjection,
} from "../../loopx/control_plane/coordination/coordination_projection.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";

test("coordination projection indexes exact Todo identities in stable order", () => {
  const first = { todo_id: "todo_b", status: "open" };
  const second = { todo_id: "todo_a", status: "done" };

  const index = indexCoordinationProjectionTodos(
    {
      schema_version: "loopx_coordination_runtime_shadow_projection_v0",
      goal_id: "goal-a",
      todos: [first, second],
      leases: [],
    },
    "goal-a",
  );

  assert.deepEqual(index.todo_ids, ["todo_a", "todo_b"]);
  assert.deepEqual(index.todos.get("todo_b"), first);
});

test("coordination projection fails closed on goal, shape, or identity drift", () => {
  assert.throws(
    () => indexCoordinationProjectionTodos({ goal_id: "goal-b", todos: [] }, "goal-a"),
    /goal mismatch/,
  );
  assert.throws(
    () => indexCoordinationProjectionTodos({ goal_id: "goal-a", todos: {} }, "goal-a"),
    /todos must be an array/,
  );
  assert.throws(
    () => indexCoordinationProjectionTodos({
      goal_id: "goal-a",
      todos: [{ todo_id: "todo_one" }, { todo_id: "todo_one" }],
    }, "goal-a"),
    /duplicate todo ids/,
  );
});

test("coordination projection indexes leases and fences orphan identities", () => {
  const index = indexCoordinationProjection({
    goal_id: "goal-a",
    todos: [{ todo_id: "todo_a", status: "open" }],
    leases: [{ todo_id: "todo_a", owner: "agent-a" }],
  }, "goal-a");
  assert.deepEqual(index.lease_todo_ids, ["todo_a"]);
  assert.equal(index.leases.get("todo_a")?.owner, "agent-a");

  assert.throws(() => indexCoordinationProjection({
    goal_id: "goal-a",
    todos: [],
    leases: [{ todo_id: "todo_absent", owner: "agent-a" }],
  }, "goal-a"), /unknown todo/);
});

test("coordination projection reducer applies one atomic Todo and lease batch", () => {
  const reduced = reduceCoordinationProjection({
    schema_version: "loopx_coordination_runtime_shadow_projection_v0",
    goal_id: "goal-a",
    source_authority: "file_v0",
    todos: [
      { todo_id: "todo_b", status: "open" },
      { todo_id: "todo_a", status: "open", claimed_by: "agent-old" },
    ],
    leases: [{ todo_id: "todo_a", owner: "agent-old", lease_epoch: 1 }],
  }, "goal-a", [
    {
      kind: "todo_upsert",
      todo: { todo_id: "todo_a", status: "done", claimed_by: "agent-new" },
    },
    {
      kind: "lease_upsert",
      lease: { todo_id: "todo_a", owner: "agent-new", lease_epoch: 2 },
    },
  ]);

  assert.deepEqual(reduced.todos, [
    { claimed_by: "agent-new", status: "done", todo_id: "todo_a" },
    { status: "open", todo_id: "todo_b" },
  ]);
  assert.deepEqual(reduced.leases, [
    { lease_epoch: 2, owner: "agent-new", todo_id: "todo_a" },
  ]);
  assert.equal(reduced.source_authority, "file_v0");
});

test("coordination projection reducer fails closed on partial or invalid batches", () => {
  const projection = {
    goal_id: "goal-a",
    todos: [{ todo_id: "todo_a", status: "open" }],
    leases: [{ todo_id: "todo_a", owner: "agent-a" }],
  };
  assert.throws(
    () => reduceCoordinationProjection(projection, "goal-a", []),
    /batch is empty/,
  );
  assert.throws(
    () => reduceCoordinationProjection(projection, "goal-a", [{
      kind: "todo_remove",
      todo_id: "todo_a",
    }]),
    /orphan lease/,
  );
  const removed = reduceCoordinationProjection(projection, "goal-a", [
    { kind: "lease_remove", todo_id: "todo_a" },
    { kind: "todo_remove", todo_id: "todo_a" },
  ]);
  assert.deepEqual(removed.todos, []);
  assert.deepEqual(removed.leases, []);
  assert.throws(
    () => reduceCoordinationProjection(projection, "goal-a", [{
      kind: "lease_upsert",
      lease: { todo_id: "todo_absent", owner: "agent-b" },
    }]),
    /orphan lease/,
  );
  assert.throws(
    () => reduceCoordinationProjection(projection, "goal-a", [
      { kind: "todo_upsert", todo: { todo_id: "todo_a", status: "done" } },
      { kind: "todo_remove", todo_id: "todo_a" },
    ]),
    /more than once/,
  );
});

test("coordination projection commit derives one auditable atomic transaction", () => {
  const projection = {
    schema_version: "loopx_coordination_runtime_shadow_projection_v0",
    goal_id: "goal-a",
    source_authority: "file_v0",
    todos: [{ todo_id: "todo_a", status: "open" }],
    leases: [],
  };
  const commit = prepareCoordinationProjectionCommit({
    goal_id: "goal-a",
    operation_id: "todo:goal-a:todo_a:claim:1",
    expected_provider_revision: "file:revision-1",
    projection,
    mutations: [
      {
        kind: "todo_upsert",
        todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-a" },
      },
      {
        kind: "lease_upsert",
        lease: { todo_id: "todo_a", owner: "agent-a", lease_epoch: 1 },
      },
    ],
  });

  assert.equal(commit.expected_provider_revision, "file:revision-1");
  assert.equal(commit.operation_id, "todo:goal-a:todo_a:claim:1");
  assert.deepEqual(commit.events[0]?.mutation_kinds, ["lease_upsert", "todo_upsert"]);
  assert.deepEqual(commit.events[0]?.targets, ["lease:todo_a", "todo:todo_a"]);
  assert.equal(
    commit.events[0]?.next_projection_sha256,
    commit.receipts[0]?.next_projection_sha256,
  );
  assert.equal(
    commit.events[0]?.mutation_sha256,
    commit.receipts[0]?.mutation_sha256,
  );
  assert.equal(
    commit.events[0]?.previous_projection_sha256,
    commit.receipts[0]?.previous_projection_sha256,
  );
  assert.deepEqual(commit.next_projection.leases, [
    { lease_epoch: 1, owner: "agent-a", todo_id: "todo_a" },
  ]);
});

test("provider-first coordination mutation applies, replays, and reads its receipt", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-coordination-mutation-"));
  const store = new FileAuthorityStore(root, "goal-a");
  const initial = await store.commitAuthority({
    expected_provider_revision: null,
    operation_id: "bootstrap:goal-a",
    events: [{ schema_version: "bootstrap_v0" }],
    next_projection: {
      schema_version: "loopx_coordination_runtime_shadow_projection_v0",
      goal_id: "goal-a",
      source_authority: "file_v0",
      todos: [{ todo_id: "todo_a", status: "open" }],
      leases: [],
    },
    receipts: [],
  });
  assert.equal(initial.status, "applied");
  if (initial.status !== "applied") return;

  const input = {
    goal_id: "goal-a",
    operation_id: "claim:goal-a:todo_a:1",
    expected_provider_revision: initial.provider_revision,
    mutations: [
      {
        kind: "todo_upsert" as const,
        todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-a" },
      },
      {
        kind: "lease_upsert" as const,
        lease: { todo_id: "todo_a", owner: "agent-a", lease_epoch: 1 },
      },
    ],
  };
  const applied = await commitCoordinationProjectionMutation(store, input);
  assert.equal(applied.status, "applied");
  const replayed = await commitCoordinationProjectionMutation(store, input);
  assert.equal(replayed.status, "replayed");

  const head = await store.loadAuthority();
  assert.equal(head.status, "loaded");
  if (head.status === "loaded") {
    assert.equal(
      (head.head.todos as Array<Record<string, unknown>>)[0]?.claimed_by,
      "agent-a",
    );
    assert.equal((head.head.leases as Array<Record<string, unknown>>)[0]?.owner, "agent-a");
  }
});

test("provider-first coordination mutation fences stale revision and operation reuse", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-coordination-mutation-fence-"));
  const store = new FileAuthorityStore(root, "goal-a");
  const initial = await store.commitAuthority({
    expected_provider_revision: null,
    operation_id: "bootstrap:goal-a",
    events: [{ schema_version: "bootstrap_v0" }],
    next_projection: {
      goal_id: "goal-a",
      source_authority: "file_v0",
      todos: [{ todo_id: "todo_a", status: "open" }],
      leases: [],
    },
    receipts: [],
  });
  assert.equal(initial.status, "applied");
  if (initial.status !== "applied") return;

  const stale = await commitCoordinationProjectionMutation(store, {
    goal_id: "goal-a",
    operation_id: "claim:stale",
    expected_provider_revision: "file:stale",
    mutations: [{
      kind: "todo_upsert",
      todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-a" },
    }],
  });
  assert.equal(stale.status, "conflict");

  const applied = await commitCoordinationProjectionMutation(store, {
    goal_id: "goal-a",
    operation_id: "claim:reused",
    expected_provider_revision: initial.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-a" },
    }],
  });
  assert.equal(applied.status, "applied");
  const mismatch = await commitCoordinationProjectionMutation(store, {
    goal_id: "goal-a",
    operation_id: "claim:reused",
    expected_provider_revision: initial.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-b" },
    }],
  });
  assert.equal(mismatch.status, "failed");
  if (mismatch.status === "failed") {
    assert.equal(mismatch.reason_code, "coordination_operation_identity_mismatch");
  }
});

test("provider-first coordination mutation recovers a lost applied response", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-coordination-mutation-recover-"));
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
  const store = new LostResponseStore(root, "goal-a");
  const bootstrap = await FileAuthorityStore.prototype.commitAuthority.call(store, {
    expected_provider_revision: null,
    operation_id: "bootstrap:goal-a",
    events: [{ schema_version: "bootstrap_v0" }],
    next_projection: {
      goal_id: "goal-a",
      source_authority: "file_v0",
      todos: [{ todo_id: "todo_a", status: "open" }],
      leases: [],
    },
    receipts: [],
  });
  assert.equal(bootstrap.status, "applied");
  if (bootstrap.status !== "applied") return;

  const recovered = await commitCoordinationProjectionMutation(store, {
    goal_id: "goal-a",
    operation_id: "claim:recover",
    expected_provider_revision: bootstrap.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-a" },
    }],
  });
  assert.equal(recovered.status, "recovered");
  const replayed = await commitCoordinationProjectionMutation(store, {
    goal_id: "goal-a",
    operation_id: "claim:recover",
    expected_provider_revision: bootstrap.provider_revision,
    mutations: [{
      kind: "todo_upsert",
      todo: { todo_id: "todo_a", status: "open", claimed_by: "agent-a" },
    }],
  });
  assert.equal(replayed.status, "replayed");
});

import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type {
  AuthorityStoreCommit,
  AuthorityStoreCommitResult,
} from "../../loopx/control_plane/coordination/authority_store.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  commitCoordinationRuntimeShadow,
  inspectCoordinationRuntimeShadow,
  COORDINATION_RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA,
  COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
} from "../../loopx/control_plane/coordination/runtime_shadow.ts";

async function request(root: string, operationId = "todo:goal-a:todo_one:v1") {
  return {
    schema_version: COORDINATION_RUNTIME_SHADOW_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    operation_id: operationId,
    event_kind: "todo_claim",
    source_version: "state:1",
    projection: {
      schema_version: "loopx_coordination_shadow_projection_v0",
      goal_id: "goal-a",
      todos: [{ todo_id: "todo_one", status: "open", claimed_by: "agent-a" }],
      leases: [],
    },
  };
}

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

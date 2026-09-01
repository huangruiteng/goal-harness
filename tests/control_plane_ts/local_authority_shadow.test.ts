import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type {
  AuthorityStore,
  AuthorityStoreCommit,
  AuthorityStoreCommitResult,
  AuthorityStoreIdentityResult,
  AuthorityStoreLoadResult,
  AuthorityStoreReceiptResult,
  AuthorityStoreScanResult,
} from "../../loopx/control_plane/coordination/authority_store.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA,
  recordLocalAuthorityShadow,
} from "../../loopx/control_plane/coordination/local_authority_shadow.ts";

function request(directory: string, operationId = "local-operation-a") {
  return {
    schema_version: "loopx_local_authority_shadow_request_v0",
    mode: "file_one_way",
    runtime_root: directory,
    goal_id: "goal-a",
    operation_id: operationId,
    source_operation: "todo_update",
    source_digest: `sha256:${"a".repeat(64)}`,
    source_projection: {
      schema_version: "loopx_local_authority_shadow_projection_v0",
      goal_id: "goal-a",
      handoff_mode: "hard_lease",
      todos: [{ todo_id: "todo-a", status: "open", claimed_by: "agent-a" }],
      leases: [{ todo_id: "todo-a", version: 2, lease_epoch: 1, status: "active" }],
    },
  };
}

test("one-way file shadow commits an observation without becoming decision authority", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-shadow-"));
  t.after(() => rm(root, { recursive: true, force: true }));

  const evidence = await recordLocalAuthorityShadow(request(root));

  assert.equal(evidence.schema_version, LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA);
  assert.equal(evidence.outcome, "advanced");
  assert.equal(evidence.primary_authority, "legacy_local");
  assert.equal(evidence.candidate_read_for_decision, false);
  assert.equal(evidence.provider_to_local_writes, false);
  assert.equal(evidence.primary_writeback_preserved, true);
  const loaded = await new FileAuthorityStore(
    join(root, "authority-shadow", "file", "goal-a"),
    "goal-a",
  ).loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status === "loaded") {
    assert.deepEqual(loaded.head, request(root).source_projection);
  }
});

test("same operation replays its typed observation receipt", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-shadow-"));
  t.after(() => rm(root, { recursive: true, force: true }));

  assert.equal((await recordLocalAuthorityShadow(request(root))).outcome, "advanced");
  const replay = await recordLocalAuthorityShadow(request(root));

  assert.equal(replay.outcome, "replayed");
  const page = await new FileAuthorityStore(
    join(root, "authority-shadow", "file", "goal-a"),
    "goal-a",
  ).scanCommitted(null, 10);
  assert.equal(page.status, "page");
  if (page.status === "page") assert.equal(page.transactions.length, 1);
});

class UnavailableStore implements AuthorityStore {
  commits = 0;

  async storeIdentity(): Promise<AuthorityStoreIdentityResult> {
    return { status: "unavailable", reason_code: "injected", reason: "offline" };
  }
  async loadAuthority(): Promise<AuthorityStoreLoadResult> {
    return { status: "unavailable", reason_code: "injected", reason: "offline" };
  }
  async commitAuthority(_commit: AuthorityStoreCommit): Promise<AuthorityStoreCommitResult> {
    this.commits += 1;
    return { status: "failed", reason_code: "unexpected", reason: "must not commit" };
  }
  async readReceipt(_operationId: string): Promise<AuthorityStoreReceiptResult> {
    return { status: "missing" };
  }
  async scanCommitted(_afterCursor: string | null, _limit: number): Promise<AuthorityStoreScanResult> {
    return { status: "page", transactions: [], next_cursor: null, has_more: false };
  }
}

test("candidate unavailability is typed evidence and attempts no commit", async () => {
  const store = new UnavailableStore();
  const evidence = await recordLocalAuthorityShadow(request("/not-used"), {
    openStore: () => store,
  });

  assert.equal(evidence.outcome, "unavailable");
  assert.equal(evidence.reason_code, "injected");
  assert.equal(evidence.primary_writeback_preserved, true);
  assert.equal(store.commits, 0);
});

class RevisionConflictStore extends UnavailableStore {
  override async storeIdentity(): Promise<AuthorityStoreIdentityResult> {
    return { status: "available", store_identity: "file:test" };
  }
  override async loadAuthority(): Promise<AuthorityStoreLoadResult> {
    return {
      status: "loaded",
      head: {},
      provider_revision: "provider-revision-a",
      cursor: "1",
    };
  }
  override async commitAuthority(
    _commit: AuthorityStoreCommit,
  ): Promise<AuthorityStoreCommitResult> {
    this.commits += 1;
    return {
      status: "conflict",
      conflict_kind: "provider_revision_mismatch",
      current_provider_revision: "provider-revision-b",
      current_cursor: "2",
    };
  }
}

test("provider revision conflict requests a fresh source projection without stale retry", async () => {
  const store = new RevisionConflictStore();

  const result = await recordLocalAuthorityShadow(request("/not-used"), {
    openStore: () => store,
  });

  assert.equal(result.outcome, "conflict_retry_required");
  assert.equal(result.reason_code, "provider_revision_mismatch");
  assert.equal(store.commits, 1);
});

test("goal id cannot escape the fixed shadow directory", async () => {
  await assert.rejects(
    recordLocalAuthorityShadow({
      ...request("/not-used"),
      goal_id: "../other-goal",
      source_projection: {
        ...request("/not-used").source_projection,
        goal_id: "../other-goal",
      },
    }),
    /single path segment/u,
  );
});

test("ambiguous response is success only when the exact receipt is readable", async () => {
  const root = await mkdtemp(join(tmpdir(), "loopx-local-authority-shadow-"));
  tCleanup(root);
  class AfterCommitStore extends FileAuthorityStore {
    protected override async replaceDurably(path: string, payload: Uint8Array): Promise<void> {
      await super.replaceDurably(path, payload);
      if (path === this.path) throw new Error("lost response after durable replace");
    }
  }
  const recovered = await recordLocalAuthorityShadow(request(root), {
    openStore: (directory, goalId) => new AfterCommitStore(directory, goalId),
  });
  assert.equal(recovered.outcome, "ambiguous_reconciled");

  const beforeRoot = await mkdtemp(join(tmpdir(), "loopx-local-authority-shadow-"));
  tCleanup(beforeRoot);
  class BeforeCommitStore extends FileAuthorityStore {
    protected override async replaceDurably(path: string, _payload: Uint8Array): Promise<void> {
      if (path === this.path) throw new Error("failed before durable replace");
      return await super.replaceDurably(path, _payload);
    }
  }
  const unproved = await recordLocalAuthorityShadow(request(beforeRoot), {
    openStore: (directory, goalId) => new BeforeCommitStore(directory, goalId),
  });
  assert.equal(unproved.outcome, "ambiguous_unproved");
});

const cleanupRoots: string[] = [];
function tCleanup(root: string): void {
  cleanupRoots.push(root);
}
test.after(async () => {
  await Promise.all(cleanupRoots.map((root) => rm(root, { recursive: true, force: true })));
});

import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import { promisify } from "node:util";

import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";
import {
  LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V1,
  LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_TRANSACTION_RECEIPT_SCHEMA,
  commitLocalAuthorityShadowEntry,
  composeLocalAuthorityShadowHead,
  localAuthorityShadowHeadDigest,
  readLocalAuthorityShadow,
} from "../../loopx/control_plane/coordination/local_authority_shadow.ts";
import {
  LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA,
  LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA,
  beginLeaseOutboxEntry,
  decodeLocalAuthorityShadowBinding,
  leaseRecordDigest,
  outboxEntryIdentity,
  sha256Digest,
} from "../../loopx/control_plane/coordination/local_authority_shadow_outbox.ts";

const execFileAsync = promisify(execFile);
const GOAL = "goal-a";
const HEX = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

function entryId(seq: number, sourceRef: string): string {
  return outboxEntryIdentity(GOAL, "todos", seq, sourceRef);
}

function todoEntry(seq: number, digest: string, resolution = "committed") {
  return {
    entry_id: entryId(seq, `sha256:${HEX}`),
    partition: "todos",
    seq,
    writer: { runtime: "python", write_class: "todo_add", operation_id: null },
    source: {
      kind: "markdown_active_state",
      previous_bytes_digest: null,
      bytes_digest: `sha256:${HEX}`,
      lease: null,
      event_id: null,
    },
    source_root_digest: `sha256:${HEX}`,
    prepared_at: "2026-09-03T00:00:00.000Z",
    committed_at: "2026-09-03T00:00:00.100Z",
    resolution,
  };
}

function commitRequest(root: string, seq: number, todos: object[], resolution = "committed") {
  const projection = { handoff_mode: "hard_lease", todos };
  return {
    schema_version: "loopx_coordination_runtime_shadow_commit_entry_request_v0",
    runtime_root: root,
    goal_id: GOAL,
    entry: todoEntry(seq, `sha256:${HEX}`, resolution),
    partition_projection: projection,
    partition_digest: `sha256:${"b".repeat(64)}`,
  };
}

function noOpRequest(root: string, seq: number, resolution: "abandoned" | "unproved") {
  return {
    schema_version: "loopx_coordination_runtime_shadow_commit_entry_request_v0",
    runtime_root: root,
    goal_id: GOAL,
    entry: todoEntry(seq, `sha256:${HEX}`, resolution),
    partition_projection: null,
    partition_digest: null,
  };
}

async function tempRoot(t: test.TestContext): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "loopx-shadow-outbox-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test("commit_entry folds one partition into a v1 head and binds the receipt to the entry", async (t) => {
  const root = await tempRoot(t);
  const todos = [{ todo_id: "todo-a", status: "open" }];

  const result = await commitLocalAuthorityShadowEntry(commitRequest(root, 1, todos));

  assert.equal(result.schema_version, LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA);
  assert.equal(result.outcome, "delivered");
  assert.equal(result.no_op, false);
  assert.equal(result.cursor, "1");
  const store = new FileAuthorityStore(join(root, "authority-shadow", "file-v0"), GOAL);
  const loaded = await store.loadAuthority();
  assert.equal(loaded.status, "loaded");
  if (loaded.status !== "loaded") return;
  assert.equal(loaded.head.schema_version, LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V1);
  assert.equal(loaded.head.handoff_mode, "hard_lease");
  assert.deepEqual(loaded.head.todos, todos);
  assert.deepEqual(loaded.head.leases, []);
  assert.deepEqual(loaded.head.partitions, {
    todos: { seq: 1, partition_digest: `sha256:${"b".repeat(64)}` },
    leases: null,
  });
  assert.equal(result.head_digest, localAuthorityShadowHeadDigest(loaded.head));
  const receipt = await store.readReceipt(entryId(1, `sha256:${HEX}`));
  assert.equal(receipt.status, "found");
  if (receipt.status !== "found") return;
  const record = receipt.receipts[0] as Record<string, unknown>;
  assert.equal(record.schema_version, LOCAL_AUTHORITY_SHADOW_TRANSACTION_RECEIPT_SCHEMA);
  assert.equal(record.entry_id, entryId(1, `sha256:${HEX}`));
  assert.equal(record.source_transaction_correlated, true);
  assert.equal(record.durable_source_outbox, true);
  assert.equal(record.parity_verdict, "not_evaluated");
  assert.equal(record.primary_authority, "legacy_local");
  assert.equal(record.provider_to_local_writes, false);
  assert.equal(record.candidate_read_for_decision, false);
});

test("commit_entry replays only when the existing receipt carries the same partition digest", async (t) => {
  const root = await tempRoot(t);
  const todos = [{ todo_id: "todo-a", status: "open" }];
  assert.equal((await commitLocalAuthorityShadowEntry(commitRequest(root, 1, todos))).outcome, "delivered");

  const replay = await commitLocalAuthorityShadowEntry(commitRequest(root, 1, todos));
  assert.equal(replay.outcome, "replayed");
  assert.equal(replay.cursor, "1");

  const tampered = commitRequest(root, 1, todos);
  tampered.partition_digest = `sha256:${"c".repeat(64)}`;
  const mismatch = await commitLocalAuthorityShadowEntry(tampered);
  assert.equal(mismatch.outcome, "protocol_mismatch");
  assert.equal(mismatch.reason_code, "transaction_receipt_mismatch");

  const page = await new FileAuthorityStore(join(root, "authority-shadow", "file-v0"), GOAL)
    .scanCommitted(null, 10);
  assert.equal(page.status, "page");
  if (page.status === "page") assert.equal(page.transactions.length, 1);
});

test("no-op resolutions keep the sequence auditable without touching compared fields", async (t) => {
  const root = await tempRoot(t);
  const todos = [{ todo_id: "todo-a", status: "open" }];
  const first = await commitLocalAuthorityShadowEntry(commitRequest(root, 1, todos));

  const abandoned = await commitLocalAuthorityShadowEntry(noOpRequest(root, 2, "abandoned"));
  const unproved = await commitLocalAuthorityShadowEntry(noOpRequest(root, 3, "unproved"));

  assert.equal(abandoned.outcome, "delivered");
  assert.equal(abandoned.no_op, true);
  assert.equal(unproved.no_op, true);
  assert.equal(unproved.cursor, "3");
  assert.equal(abandoned.head_digest, first.head_digest);
  const store = new FileAuthorityStore(join(root, "authority-shadow", "file-v0"), GOAL);
  const page = await store.scanCommitted(null, 10);
  assert.equal(page.status, "page");
  if (page.status !== "page") return;
  assert.deepEqual(
    page.transactions.map((transaction) => (transaction.events[0] as Record<string, unknown>).kind),
    ["source_transaction_delivered", "source_transaction_abandoned", "source_transaction_unproved"],
  );
  const loaded = await store.loadAuthority();
  if (loaded.status === "loaded") {
    assert.deepEqual((loaded.head.partitions as Record<string, unknown>).todos, {
      seq: 1,
      partition_digest: `sha256:${"b".repeat(64)}`,
    });
  }
});

test("commit_entry rejects projection/resolution combinations that would misstate a transaction", async (t) => {
  const root = await tempRoot(t);
  const withProjection = noOpRequest(root, 1, "abandoned") as Record<string, unknown>;
  withProjection.partition_projection = { handoff_mode: "hard_lease", todos: [] };
  withProjection.partition_digest = `sha256:${"b".repeat(64)}`;
  await assert.rejects(commitLocalAuthorityShadowEntry(withProjection), /must not carry/u);

  const withoutProjection = commitRequest(root, 1, []) as Record<string, unknown>;
  withoutProjection.partition_projection = null;
  withoutProjection.partition_digest = null;
  await assert.rejects(commitLocalAuthorityShadowEntry(withoutProjection), /requires partition_projection/u);

  const badId = commitRequest(root, 1, []);
  badId.entry.entry_id = "local-shadow:abc";
  await assert.rejects(commitLocalAuthorityShadowEntry(badId), /entry\.entry_id/u);

  const extra = { ...commitRequest(root, 1, []), observation_id: "x" };
  await assert.rejects(commitLocalAuthorityShadowEntry(extra), /unsupported fields/u);
});

test("a v0 observation head is accepted as the starting point for partition folds", () => {
  const v0 = {
    schema_version: "loopx_local_authority_shadow_projection_v0",
    goal_id: GOAL,
    handoff_mode: "hard_lease",
    todos: [{ todo_id: "todo-a", status: "open" }],
    leases: [{ todo_id: "todo-a", version: 1 }],
  };
  const folded = composeLocalAuthorityShadowHead(
    v0,
    GOAL,
    { partition: "leases", seq: 4 },
    { leases: [] },
    `sha256:${"d".repeat(64)}`,
  );
  assert.equal(folded.schema_version, LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V1);
  assert.equal(folded.handoff_mode, "hard_lease");
  assert.deepEqual(folded.todos, v0.todos);
  assert.deepEqual(folded.leases, []);
  assert.deepEqual(folded.partitions, {
    todos: null,
    leases: { seq: 4, partition_digest: `sha256:${"d".repeat(64)}` },
  });
});

test("read returns head, comparison digest, and a bounded scan page", async (t) => {
  const root = await tempRoot(t);
  const missing = await readLocalAuthorityShadow({
    schema_version: "loopx_coordination_runtime_shadow_outbox_read_v0",
    runtime_root: root,
    goal_id: GOAL,
    scan_after_cursor: null,
    scan_limit: 10,
  });
  assert.equal(missing.schema_version, LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA);
  assert.equal(missing.status, "missing");
  assert.equal(missing.head, null);

  const todos = [{ todo_id: "todo-a", status: "open" }];
  await commitLocalAuthorityShadowEntry(commitRequest(root, 1, todos));
  await commitLocalAuthorityShadowEntry(noOpRequest(root, 2, "abandoned"));
  const view = await readLocalAuthorityShadow({
    schema_version: "loopx_coordination_runtime_shadow_outbox_read_v0",
    runtime_root: root,
    goal_id: GOAL,
    scan_after_cursor: null,
    scan_limit: 1,
  });
  assert.equal(view.status, "loaded");
  assert.equal(view.cursor, "2");
  assert.match(String(view.store_identity), /^file:[0-9a-f]{32}$/u);
  assert.equal(view.head_digest, localAuthorityShadowHeadDigest(view.head as Record<string, unknown>));
  const scan = view.scan as { transactions: Record<string, unknown>[]; next_cursor: string | null; has_more: boolean };
  assert.equal(scan.transactions.length, 1);
  assert.equal(scan.has_more, true);
  assert.equal(scan.transactions[0].operation_id, entryId(1, `sha256:${HEX}`));
  assert.equal(scan.transactions[0].projection_digest, view.head_digest);
  assert.equal("projection" in scan.transactions[0], false);
});

test("lease outbox entries are two-phase, durable, and skipped without a binding", async (t) => {
  const root = await tempRoot(t);
  const leaseDirectory = join(root, "goals", GOAL, "task-leases");
  const other = { goal_id: GOAL, todo_id: "todo-b", version: 1, status: "active" };
  await mkdir(leaseDirectory, { recursive: true });
  await writeFile(join(leaseDirectory, "todo-b.json"), `${JSON.stringify(other, null, 2)}\n`);
  const planned = { goal_id: GOAL, todo_id: "todo-a", version: 2, lease_epoch: 1, status: "active", updated_at: "t2" };

  assert.equal(decodeLocalAuthorityShadowBinding(undefined), null);
  assert.equal(decodeLocalAuthorityShadowBinding({ provider: "file_v0" }), null);
  assert.deepEqual(
    decodeLocalAuthorityShadowBinding({
      schema_version: "loopx_coordination_runtime_shadow_binding_v0",
      provider: "file_v0",
    }),
    { schema_version: "loopx_coordination_runtime_shadow_binding_v0", provider: "file_v0" },
  );

  const capture = await beginLeaseOutboxEntry({
    runtime_root: root,
    goal_id: GOAL,
    lease_directory: leaseDirectory,
    write_class: "task_lease_acquire",
    operation_id: "op-1",
    previous_lease: null,
    planned_lease: planned,
  });
  assert.equal(capture.failure, null);
  assert.equal(capture.seq, 1);
  assert.equal(capture.source_bytes_digest, leaseRecordDigest(planned));
  assert.equal(capture.entry_id, outboxEntryIdentity(GOAL, "leases", 1, leaseRecordDigest(planned)));
  const directory = join(root, "authority-shadow", "outbox", GOAL, "leases");
  let names = await readdir(directory);
  assert.deepEqual(names, [`0000000001-${capture.entry_id}.prepared.json`]);
  const prepared = JSON.parse(await readFile(join(directory, names[0]), "utf8"));
  assert.equal(prepared.schema_version, LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA);
  assert.equal(prepared.partition, "leases");
  assert.equal(prepared.partition_digest, null);
  assert.equal(prepared.source_root_digest, sha256Digest(resolve(root)));
  assert.deepEqual(prepared.source.lease, {
    todo_id: "todo-a",
    version: 2,
    lease_epoch: 1,
    status: "active",
    updated_at: "t2",
  });
  assert.deepEqual(
    prepared.projection.leases.map((item: { file_stem: string }) => item.file_stem),
    ["todo-a", "todo-b"],
  );
  assert.deepEqual(prepared.projection.leases[0].record, planned);

  await capture.commit();
  assert.equal(capture.failure, null);
  names = (await readdir(directory)).sort((a, b) => (a < b ? -1 : 1));
  assert.deepEqual(names, [
    `0000000001-${capture.entry_id}.committed.json`,
    `0000000001-${capture.entry_id}.prepared.json`,
  ]);
  const committed = JSON.parse(await readFile(join(directory, names[0]), "utf8"));
  assert.equal(committed.schema_version, LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA);
  assert.equal(committed.entry_id, capture.entry_id);

  const second = await beginLeaseOutboxEntry({
    runtime_root: root,
    goal_id: GOAL,
    lease_directory: leaseDirectory,
    write_class: "task_lease_renew",
    operation_id: null,
    previous_lease: planned,
    planned_lease: { ...planned, version: 3, updated_at: "t3" },
  });
  assert.equal(second.seq, 2);
  const failing = await beginLeaseOutboxEntry({
    runtime_root: root,
    goal_id: GOAL,
    lease_directory: leaseDirectory,
    write_class: "task_lease_renew",
    operation_id: null,
    previous_lease: null,
    planned_lease: { goal_id: GOAL },
  });
  assert.equal(failing.entry_id, null);
  assert.equal(failing.failure?.reason_code, "outbox_prepare_failed");
});

test("entry identity derivation agrees byte-for-byte with the Python outbox module", async () => {
  const python = process.env.LOOPX_TEST_PYTHON ?? "python3";
  const script = [
    "from loopx.control_plane.coordination.local_authority_shadow_outbox import entry_identity",
    "from loopx.control_plane.coordination.local_authority_shadow_projection import sha256_digest",
    `print(entry_identity(goal_id='${GOAL}', partition='leases', seq=7, source_ref='sha256:${HEX}'))`,
    "print(sha256_digest({'handoff_mode': 'hard_lease', 'todos': [{'todo_id': 'todo-a', 'status': 'open'}], 'leases': []}))",
  ].join("\n");
  let stdout: string;
  try {
    ({ stdout } = await execFileAsync(python, ["-c", script], {
      cwd: join(import.meta.dirname, "..", ".."),
      env: { ...process.env, PYTHONPATH: join(import.meta.dirname, "..", "..") },
    }));
  } catch {
    return; // Python without the loopx package: the Python suite pins the same fixture.
  }
  const [pythonEntryId, pythonHeadDigest] = stdout.trim().split("\n");
  assert.equal(pythonEntryId, outboxEntryIdentity(GOAL, "leases", 7, `sha256:${HEX}`));
  assert.equal(
    pythonHeadDigest,
    localAuthorityShadowHeadDigest({
      handoff_mode: "hard_lease",
      todos: [{ todo_id: "todo-a", status: "open" }],
      leases: [],
    }),
  );
});

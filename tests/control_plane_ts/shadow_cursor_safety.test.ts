import assert from "node:assert/strict";
import test from "node:test";
import * as outbox from "../../loopx/control_plane/coordination/local_authority_shadow_outbox.ts";

const cursor = {
  schema_version: outbox.LOCAL_AUTHORITY_SHADOW_DRAIN_CURSOR_SCHEMA,
  partition: "todos",
  last_seq: 1,
  last_entry_id: `local-shadow-tx-${"a".repeat(64)}`,
  last_partition_digest: `sha256:${"b".repeat(64)}`,
  last_cursor: "opaque-cursor",
  last_provider_revision: "opaque-revision",
  updated_at: "2026-09-05T01:02:03.123456+00:00",
};

test("cursor accepts opaque receipt coordinates and JSON integer semantics", () => {
  assert.deepEqual(outbox.decodeOutboxCursor(cursor, "todos"), cursor);
});

for (const last_seq of [true, false, "1", null, -1, 0, 1.5, 10_000_000_000, NaN, Infinity]) {
  test(`cursor rejects invalid sequence ${String(last_seq)}`, () => {
    assert.throws(() => outbox.decodeOutboxCursor({ ...cursor, last_seq }, "todos"), /cursor/u);
  });
}

for (const patch of [
  { partition: "leases" }, { last_entry_id: "local-shadow-tx-short" },
  { last_partition_digest: "sha256:short" }, { last_cursor: null },
  { last_provider_revision: "" }, { updated_at: "yesterday" },
  { updated_at: "2026-02-30T00:00:00Z" }, { unrecognized: true },
]) {
  test(`cursor rejects invalid binding ${JSON.stringify(patch)}`, () => {
    assert.throws(() => outbox.decodeOutboxCursor({ ...cursor, ...patch }, "todos"), /cursor/u);
  });
}

test("same source and sequence have distinct identity in another lineage or root", () => {
  const source = `sha256:${"b".repeat(64)}`;
  const root = `sha256:${"c".repeat(64)}`;
  const first = outbox.outboxEntryIdentity("goal", "todos", 1, source, "epoch-a", root);
  assert.notEqual(first, outbox.outboxEntryIdentity("goal", "todos", 1, source, "epoch-b", root));
  assert.notEqual(first, outbox.outboxEntryIdentity("goal", "todos", 1, source, "epoch-a", source));
});

test("cursor reader distinguishes missing, invalid UTF8, and unavailable bytes", async (t) => {
  const { mkdtemp, writeFile, rm, mkdir } = await import("node:fs/promises");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const directory = await mkdtemp(join(tmpdir(), "loopx-cursor-bytes-"));
  t.after(() => rm(directory, { recursive: true, force: true }));
  assert.equal(await outbox.readOutboxCursor(directory, "todos"), null);
  const path = join(directory, "drain-cursor.json");
  const bytes = Buffer.from(JSON.stringify({ ...cursor, last_cursor: "opaque-INVALID" }));
  bytes[bytes.indexOf("INVALID")] = 0xff;
  await writeFile(path, bytes);
  await assert.rejects(outbox.readOutboxCursor(directory, "todos"), { code: "outbox_file_invalid" });
  assert.deepEqual(await (await import("node:fs/promises")).readFile(path), bytes);
  await rm(path);
  await mkdir(path);
  await assert.rejects(outbox.readOutboxCursor(directory, "todos"), { code: "outbox_file_unavailable" });
});

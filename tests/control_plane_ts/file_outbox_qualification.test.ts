import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { canonicalAuthorityBytes } from "../../loopx/control_plane/coordination/authority_store_codec.ts";
import { LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA } from "../../loopx/control_plane/coordination/coordination_state_contract.generated.ts";
import { commitLocalAuthorityShadowEntry } from "../../loopx/control_plane/coordination/local_authority_shadow.ts";

test("a drained entry cannot silently bootstrap a missing candidate", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "loopx-entry-no-bootstrap-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const projection = { handoff_mode: "hard_lease", todos: [] };
  const digest = `sha256:${createHash("sha256").update(canonicalAuthorityBytes(projection)).digest("hex")}`;
  const result = await commitLocalAuthorityShadowEntry({
    schema_version: LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA,
    runtime_root: root,
    goal_id: "goal-a",
    entry: {
      capture_lineage_id: "lineage-a", prepared_sha256: `sha256:${"d".repeat(64)}`, committed_sha256: null,
      entry_id: `local-shadow-tx-${"a".repeat(64)}`,
      partition: "todos", seq: 1,
      writer: { runtime: "python", write_class: "todo_add", operation_id: null },
      source: { kind: "markdown_active_state", previous_bytes_digest: null,
        previous_partition_digest: digest,
        bytes_digest: `sha256:${"b".repeat(64)}`, lease: null, event_id: null },
      source_root_digest: `sha256:${"c".repeat(64)}`,
      prepared_at: "2026-09-06T00:00:00.000Z", committed_at: "2026-09-06T00:00:00.100Z",
      resolution: "committed",
    },
    partition_projection: projection, partition_digest: digest,
  });
  assert.equal(result.outcome, "failed");
  assert.equal(result.reason_code, "bootstrap_required");
});

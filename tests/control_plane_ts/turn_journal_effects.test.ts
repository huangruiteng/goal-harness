import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { commitTurnJournal } from "../../loopx/control_plane/turn_driver/turn_journal_effects.ts";

function journal(status: string): Record<string, unknown> {
  return {
    schema_version: "loopx_turn_journal_v0",
    goal_id: "fixture-goal",
    turn_key: `sha256:${"a".repeat(64)}`,
    status,
    completed_phases: ["host_execute"],
    plan: {
      transaction: {
        settlement_plan: { identity: { effect_id: "fixture-effect" } },
      },
    },
  };
}

test("journal checkpoint retry is idempotent and operation-scoped", async () => {
  const directory = await mkdtemp(join(tmpdir(), "loopx-ts-journal-"));
  const path = join(directory, "turn.json");
  try {
    const first = await commitTurnJournal({
      path,
      journal: journal("in_progress"),
      expected_effect_id: "fixture-effect",
      expected_previous_sha256: null,
    });
    const replay = await commitTurnJournal({
      path,
      journal: journal("in_progress"),
      expected_effect_id: "fixture-effect",
      expected_previous_sha256: null,
    });
    assert.equal(first.appended, true);
    assert.equal(first.replayed, false);
    assert.equal(replay.appended, false);
    assert.equal(replay.replayed, true);
    assert.equal(first.operation_id, replay.operation_id);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("journal checkpoint rejects a stale compare-and-swap precondition", async () => {
  const directory = await mkdtemp(join(tmpdir(), "loopx-ts-journal-"));
  const path = join(directory, "turn.json");
  try {
    await commitTurnJournal({
      path,
      journal: journal("in_progress"),
      expected_effect_id: "fixture-effect",
      expected_previous_sha256: null,
    });
    await assert.rejects(
      commitTurnJournal({
        path,
        journal: journal("committed"),
        expected_effect_id: "fixture-effect",
        expected_previous_sha256: null,
      }),
      /compare-and-swap precondition failed/,
    );
    assert.equal(JSON.parse(await readFile(path, "utf8")).status, "in_progress");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

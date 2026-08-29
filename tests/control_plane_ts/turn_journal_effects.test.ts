import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { commitTurnJournal } from "../../loopx/control_plane/turn_driver/turn_journal_effects.ts";

const turnKey = `sha256:${"a".repeat(64)}`;
const todoId = "todo_fixture0001";
const phases = [
  "host_execute",
  "typed_result",
  "validation",
  "durable_writeback",
  "quota_spend",
  "scheduler_apply",
  "scheduler_ack",
] as const;

function effectId(agentId = "fixture-agent"): string {
  return `fixture-goal:${agentId}:${todoId}:${turnKey}`;
}

function journal(
  status = "in_progress",
  completedPhases: readonly string[] = [],
  agentId = "fixture-agent",
): Record<string, unknown> {
  return {
    schema_version: "loopx_turn_journal_v0",
    goal_id: "fixture-goal",
    turn_key: turnKey,
    status,
    completed_phases: [...completedPhases],
    plan: {
      turn_envelope: {
        goal_id: "fixture-goal",
        agent_id: agentId,
        action: { selected_todo: { todo_id: todoId } },
      },
      transaction: {
        turn_key: turnKey,
        settlement_plan: {
          schema_version: "quota_settlement_plan_v1",
          identity: {
            schema_version: "quota_settlement_identity_v0",
            effect_id: effectId(agentId),
            goal_id: "fixture-goal",
            agent_id: agentId,
            todo_id: todoId,
            turn_instance_id: turnKey,
          },
        },
      },
    },
  };
}

async function withJournalPath(
  run: (path: string) => Promise<void>,
): Promise<void> {
  const directory = await mkdtemp(join(tmpdir(), "loopx-ts-journal-"));
  try {
    await run(join(directory, "turn.json"));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

async function commit(path: string, snapshot: Record<string, unknown>) {
  return await commitTurnJournal({
    path,
    journal: snapshot,
    expected_effect_id: effectId(),
  });
}

test("journal checkpoint retry is idempotent and operation-scoped", async () => {
  await withJournalPath(async (path) => {
    const snapshot = journal();
    const first = await commit(path, snapshot);
    const replay = await commit(path, snapshot);

    assert.equal(first.appended, true);
    assert.equal(first.replayed, false);
    assert.equal(replay.appended, false);
    assert.equal(replay.replayed, true);
    assert.equal(first.operation_id, replay.operation_id);
  });
});

test("TS journal owner accepts the complete monotonic transaction", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    await commit(path, journal("in_progress", phases.slice(0, 2)));
    await commit(path, journal("in_progress", phases.slice(0, 3)));

    const preparedWriteback = journal("in_progress", phases.slice(0, 3));
    preparedWriteback.effect_attempts = {
      durable_writeback: {
        status: "prepared",
        effect_ref: `${effectId()}#durable_writeback`,
      },
    };
    await commit(path, preparedWriteback);
    await commit(path, journal("in_progress", phases.slice(0, 4)));

    const preparedSpend = journal("in_progress", phases.slice(0, 4));
    preparedSpend.effect_attempts = {
      quota_spend: {
        status: "prepared",
        effect_ref: `${effectId()}#quota_spend`,
      },
    };
    await commit(path, preparedSpend);
    await commit(path, journal("in_progress", phases.slice(0, 5)));
    await commit(path, journal("scheduler_action_required", phases.slice(0, 5)));
    await commit(path, journal("committed", phases));

    assert.equal(JSON.parse(await readFile(path, "utf8")).status, "committed");
  });
});

test("new journals cannot appear after side effects", async () => {
  await withJournalPath(async (path) => {
    await assert.rejects(
      commit(path, journal("in_progress", phases.slice(0, 3))),
      /must begin in progress with no completed phases/,
    );
  });
});

test("completed phases cannot regress", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    await commit(path, journal("in_progress", phases.slice(0, 2)));
    await commit(path, journal("in_progress", phases.slice(0, 3)));
    await assert.rejects(
      commit(path, journal("in_progress", phases.slice(0, 2))),
      /completed phases cannot regress or fork/,
    );
  });
});

test("completed phases cannot skip transaction checkpoints", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    await assert.rejects(
      commit(path, journal("committed", phases)),
      /cannot skip transaction checkpoints/,
    );
  });
});

test("failed validation may explicitly rewind for host reinvocation", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    const failed = journal("failed", phases.slice(0, 2));
    failed.receipt = { turn_key: turnKey, failed_phase: "validation" };
    await commit(path, failed);
    await commit(path, journal("in_progress", []));

    assert.deepEqual(JSON.parse(await readFile(path, "utf8")).completed_phases, []);
  });
});

test("terminal journal tombstones are immutable", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    await commit(path, journal("in_progress", phases.slice(0, 2)));
    await commit(path, journal("in_progress", phases.slice(0, 3)));
    await commit(path, journal("in_progress", phases.slice(0, 4)));
    await commit(path, journal("in_progress", phases.slice(0, 5)));
    await commit(path, journal("committed", phases));
    const changed = journal("committed", phases);
    changed.reason = "late mutation";
    await assert.rejects(commit(path, changed), /tombstones are immutable/);
  });
});

test("transaction plans are immutable within one effect", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    const changed = journal("in_progress", phases.slice(0, 2));
    const plan = changed.plan as Record<string, unknown>;
    plan.host = { kind: "changed-after-start" };
    await assert.rejects(commit(path, changed), /transaction plan is immutable/);
  });
});

test("cross-effect overwrite remains fail-closed", async () => {
  await withJournalPath(async (path) => {
    await commit(path, journal());
    await assert.rejects(
      commitTurnJournal({ path, journal: journal("in_progress", [], "other-agent") }),
      /belongs to another settlement effect/,
    );
  });
});

test("prepared effects must use the settlement identity", async () => {
  await withJournalPath(async (path) => {
    const invalid = journal();
    invalid.effect_attempts = {
      durable_writeback: {
        status: "prepared",
        effect_ref: "another-effect#durable_writeback",
      },
    };
    await assert.rejects(
      commit(path, invalid),
      /prepared effect does not match settlement identity/,
    );
  });
});

test("failed snapshots must name the next uncompleted phase", async () => {
  await withJournalPath(async (path) => {
    const invalid = journal("failed", phases.slice(0, 4));
    invalid.receipt = { turn_key: turnKey, failed_phase: "validation" };
    await assert.rejects(
      commit(path, invalid),
      /must name the next uncompleted phase/,
    );
  });
});

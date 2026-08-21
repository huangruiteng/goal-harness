import assert from "node:assert/strict";
import test from "node:test";

import {
  interpretTurnJournal,
  interpretTurnJournalEffect,
  type TurnJournalInspectionRequest,
} from "../../loopx/control_plane/turn_driver/turn_journal.ts";

const turnKey = `sha256:${"a".repeat(64)}`;

function request(status = "committed"): TurnJournalInspectionRequest {
  return {
    schema_version: "loopx_turn_journal_interpretation_request_v0",
    goal_id: "fixture-goal",
    agent_id: "fixture-agent",
    turn_key: turnKey,
    journal: {
      schema_version: "loopx_turn_journal_v0",
      goal_id: "fixture-goal",
      turn_key: turnKey,
      status,
      completed_phases: [
        "host_execute",
        "typed_result",
        "validation",
        "durable_writeback",
        "quota_spend",
        "scheduler_apply",
        "scheduler_ack",
      ],
      plan: {
        turn_envelope: { goal_id: "fixture-goal", agent_id: "fixture-agent" },
        transaction: {
          turn_key: turnKey,
          settlement_plan: {
            identity: { goal_id: "fixture-goal", agent_id: "fixture-agent" },
          },
        },
      },
      host_result: { turn_key: turnKey, private_detail: "do-not-expose" },
      receipt: { turn_key: turnKey, body: "do-not-expose" },
    },
  };
}

test("legal terminal replay is projected without effects or private fields", () => {
  const input = request();
  const before = structuredClone(input);
  const result = interpretTurnJournal(input);

  assert.equal(result.decision, "replay_legal");
  assert.equal(result.replay_legal, true);
  assert.deepEqual(result.violations, []);
  assert.deepEqual(result.effects, []);
  assert.equal(JSON.stringify(result).includes("do-not-expose"), false);
  assert.deepEqual(input, before);
});

test("journal interpretation preserves the canonical Effect Program slots", () => {
  const turn = interpretTurnJournalEffect(request());

  assert.equal(turn.request.kind, "turn_journal");
  assert.equal(turn.interpretation.route, "turn_journal_replay");
  assert.equal(turn.observation.decision, "replay_legal");
  assert.equal(turn.observation.should_run, false);
  assert.deepEqual(turn.next_effect.cli_actions, []);
  assert.deepEqual(interpretTurnJournal(request()), {
    ok: true,
    schema_version: "loopx_turn_journal_inspection_v0",
    decision: "replay_legal",
    journal_status: "committed",
    replay_legal: true,
    goal_matches: true,
    owner_matches: true,
    turn_key_matches: true,
    phases_form_ordered_prefix: true,
    completed_phases: [
      "host_execute",
      "typed_result",
      "validation",
      "durable_writeback",
      "quota_spend",
      "scheduler_apply",
      "scheduler_ack",
    ],
    tombstone_retained: true,
    violations: [],
    effects: [],
  });
});

test("identity and phase violations accumulate in stable order", () => {
  const input = request();
  input.journal.goal_id = "other-goal";
  input.journal.turn_key = "sha256:other-turn";
  input.journal.completed_phases = ["host_execute", "validation"];
  const plan = input.journal.plan as Record<string, unknown>;
  const transaction = (plan.transaction ?? {}) as Record<string, unknown>;
  const settlement = (transaction.settlement_plan ?? {}) as Record<string, unknown>;
  const identity = (settlement.identity ?? {}) as Record<string, unknown>;
  identity.agent_id = "other-agent";

  const result = interpretTurnJournal(input);

  assert.equal(result.decision, "replay_blocked");
  assert.deepEqual(result.violations, [
    "goal_mismatch",
    "owner_mismatch",
    "turn_key_mismatch",
    "completed_phases_not_ordered_prefix",
  ]);
});

test("non-terminal and malformed state cannot replay", () => {
  const input = request("in_progress");
  input.journal.completed_phases = "host_execute";

  const result = interpretTurnJournal(input);

  assert.equal(result.replay_legal, false);
  assert.equal(result.phases_form_ordered_prefix, false);
  assert.deepEqual(result.completed_phases, []);
  assert.deepEqual(result.violations, [
    "completed_phases_invalid",
    "journal_not_terminal",
  ]);
});

test("present malformed optional identities block replay", () => {
  const input = request();
  const hostResult = input.journal.host_result as Record<string, unknown>;
  const receipt = input.journal.receipt as Record<string, unknown>;
  hostResult.turn_key = "";
  receipt.turn_key = 7;

  const result = interpretTurnJournal(input);

  assert.equal(result.turn_key_matches, false);
  assert.deepEqual(result.violations, ["turn_key_identity_missing"]);
});

test("JSON non-string phases keep the Python boundary normalization", () => {
  const input = request();
  input.journal.completed_phases = ["host_execute", null];

  const result = interpretTurnJournal(input);

  assert.deepEqual(result.completed_phases, ["host_execute", "None"]);
  assert.equal(result.phases_form_ordered_prefix, false);
  assert.equal(result.replay_legal, false);
});

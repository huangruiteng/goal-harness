import assert from "node:assert/strict";
import test from "node:test";

import {
  commitStepPayload,
  effectProgramFromOrderedSteps,
  requireMatchingEffectId,
  seedCommittedSteps,
  settlementBindGate,
  settlementBindReduce,
  settlementFailed,
  settlementIdentity,
  settlementIdentityFromPlan,
  settlementNextAction,
  settlementPure,
  settlementResultPayload,
} from "../../loopx/control_plane/effect_program.ts";
import {
  receiptBoundMonitorPhase,
  receiptBoundReplayPhase,
  receiptBoundTerminalPhase,
} from "../../loopx/control_plane/quota/settlement_phase.ts";
import type {
  SettlementResult,
} from "../../loopx/control_plane/effect_program.ts";

const identityInput = {
  goal_id: "goal",
  agent_id: "agent",
  todo_id: "todo",
  turn_instance_id: "turn",
} as const;

// The native type contract must reject the previously expressible state in
// which one settlement result carried both a success value and a failure.
// @ts-expect-error successful settlement values cannot carry failures
const invalidSettlementResult: SettlementResult<{ value: number }> = {
  value: { value: 1 },
  receipts: [],
  failure: {
    kind: "permission_denied",
    step_kind: "durable_writeback",
    reason: "denied",
  },
};
void invalidSettlementResult;

test("ordered Effect Program steps preserve data and skip malformed entries", () => {
  const program = effectProgramFromOrderedSteps(
    [
      { id: "one", kind: "read", command: "loopx status", extra: 1 },
      null,
      { id: "two", prompt: "inspect evidence" },
    ],
    "bounded",
  );

  assert.equal(program.execution_mode, "bounded");
  assert.deepEqual(program.steps.map((step) => step.step_id), ["one", "two"]);
  assert.equal(program.steps[0]?.raw.extra, 1);
  assert.equal(program.steps[1]?.command, "inspect evidence");
});

test("settlement identity makes illegal dual bindings unrepresentable", () => {
  assert.deepEqual(settlementIdentity(identityInput), {
    ...identityInput,
    replan_obligation_id: null,
    binding_kind: "todo",
    binding_id: "todo",
    effect_id: "goal:agent:todo:turn",
  });
  assert.throws(
    () =>
      settlementIdentity({
        ...identityInput,
        replan_obligation_id: "replan",
      }),
    /cannot bind both/,
  );
});

test("receipt-bound monitor settlement phase is derived from typed receipts", () => {
  assert.equal(
    receiptBoundMonitorPhase({
      poll_present: false,
      material_change: false,
      durable_writeback_present: false,
      quota_spend_present: false,
    }),
    "poll_due",
  );
  assert.equal(
    receiptBoundMonitorPhase({
      poll_present: true,
      material_change: false,
      durable_writeback_present: false,
      quota_spend_present: false,
    }),
    "settled",
  );
  assert.equal(
    receiptBoundMonitorPhase({
      poll_present: true,
      material_change: true,
      durable_writeback_present: true,
      quota_spend_present: false,
    }),
    "settlement_pending",
  );
  assert.equal(
    receiptBoundMonitorPhase({
      poll_present: true,
      material_change: true,
      durable_writeback_present: true,
      quota_spend_present: true,
    }),
    "settled",
  );
});

test("receipt-bound replay settlement follows its binding and full chain", () => {
  assert.equal(
    receiptBoundReplayPhase({
      completion_receipt_present: false,
      durable_writeback_present: true,
      quota_spend_present: true,
    }),
    "open",
  );
  assert.equal(
    receiptBoundReplayPhase({
      binding_kind: "autonomous_replan",
      completion_receipt_present: false,
      durable_writeback_present: false,
      quota_spend_present: true,
    }),
    "open",
  );
  assert.equal(
    receiptBoundReplayPhase({
      binding_kind: "autonomous_replan",
      completion_receipt_present: false,
      durable_writeback_present: true,
      quota_spend_present: false,
    }),
    "settlement_pending",
  );
  assert.equal(
    receiptBoundReplayPhase({
      binding_kind: "autonomous_replan",
      completion_receipt_present: false,
      durable_writeback_present: true,
      quota_spend_present: true,
    }),
    "settled",
  );
  assert.equal(
    receiptBoundReplayPhase({
      completion_receipt_present: true,
      durable_writeback_present: true,
      quota_spend_present: false,
    }),
    "settlement_pending",
  );
  assert.equal(
    receiptBoundReplayPhase({
      completion_receipt_present: true,
      durable_writeback_present: true,
      quota_spend_present: true,
    }),
    "settled",
  );
  assert.equal(
    receiptBoundTerminalPhase({
      terminal_closeout_present: true,
      durable_writeback_present: true,
      quota_spend_present: true,
    }),
    "settled",
  );
});

test("bind preserves receipt order and short-circuits typed failures", () => {
  const receipt = {
    step_kind: "validation" as const,
    status: "committed",
    effect_id: "goal:agent:todo:turn",
  };
  const first = settlementPure({ value: 1 }, [receipt]);
  const gate = settlementBindGate(first);
  assert.equal(gate.execute, true);

  const second = settlementPure({ value: 2 }, [
    { ...receipt, step_kind: "durable_writeback" },
  ]);
  assert.deepEqual(settlementBindReduce(first, second).receipts, [
    receipt,
    { ...receipt, step_kind: "durable_writeback" },
  ]);

  const failed = settlementFailed({
    kind: "permission_denied",
    step_kind: "durable_writeback",
    reason: "denied",
    receipts: [receipt],
  });
  const stopped = settlementBindGate(failed);
  assert.equal(stopped.execute, false);
  assert.equal(stopped.result.failure?.kind, "permission_denied");
  assert.deepEqual(stopped.result.receipts, [receipt]);
});

test("durable receipts replay only for the same effect and ordered prefix", () => {
  const identity = settlementIdentity(identityInput);
  const seeded = seedCommittedSteps({
    identity,
    ordered_steps: ["validation", "durable_writeback", "quota_spend"],
    committed_payloads: {
      durable_writeback: { ok: true, appended: true, record: "write" },
    },
    completed_phases: ["validation", "durable_writeback"],
    transaction_phases: [
      "validation",
      "durable_writeback",
      "quota_spend",
    ],
  });
  assert.equal(seeded.failure, null);
  assert.deepEqual(
    seeded.receipts.map((receipt) => receipt.step_kind),
    ["validation", "durable_writeback"],
  );
  assert.equal(
    requireMatchingEffectId("other-effect", identity.effect_id).failure?.kind,
    "identity_mismatch",
  );
});

test("commit reduction advances one phase only after a committed payload", () => {
  const committed = commitStepPayload({
    identity: identityInput,
    step_kind: "quota_spend",
    transaction_phases: [
      "validation",
      "durable_writeback",
      "quota_spend",
    ],
    payload: { ok: true, appended: true },
  });
  assert.deepEqual(committed.completed_phases, [
    "validation",
    "durable_writeback",
    "quota_spend",
  ]);
  assert.equal(committed.result.receipts[0]?.step_kind, "quota_spend");

  const rejected = commitStepPayload({
    identity: identityInput,
    step_kind: "quota_spend",
    transaction_phases: ["validation", "durable_writeback", "quota_spend"],
    payload: { ok: false, error: "budget exhausted" },
  });
  assert.equal(rejected.completed_phases, null);
  assert.equal(rejected.result.failure?.kind, "budget_rejected");
});

test("runtime selects the next uncommitted effect instead of Python orchestration", () => {
  const next = settlementNextAction({
    identity: identityInput,
    ordered_steps: ["validation", "durable_writeback", "quota_spend"],
    committed_payloads: {},
    completed_phases: ["validation"],
    transaction_phases: ["validation", "durable_writeback", "quota_spend"],
  });
  assert.equal(next.decision, "execute");
  assert.equal(next.step_kind, "durable_writeback");

  const complete = settlementNextAction({
    identity: identityInput,
    ordered_steps: ["validation", "durable_writeback", "quota_spend"],
    committed_payloads: {
      durable_writeback: { ok: true, appended: true },
      quota_spend: { ok: true, appended: true },
    },
    completed_phases: ["validation", "durable_writeback", "quota_spend"],
    transaction_phases: ["validation", "durable_writeback", "quota_spend"],
  });
  assert.equal(complete.decision, "complete");
  assert.equal(complete.step_kind, null);
});

test("plan identity and public result payload remain stable at the boundary", () => {
  const identity = settlementIdentity(identityInput);
  const result = settlementIdentityFromPlan({
    settlement_plan: { identity },
  });
  assert.equal(result.value?.effect_id, identity.effect_id);
  assert.deepEqual(settlementResultPayload(result), {
    ok: true,
    receipts: [],
    failure: null,
  });
});

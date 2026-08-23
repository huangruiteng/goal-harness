import assert from "node:assert/strict";
import test from "node:test";

import {
  governedCapabilitySettlementStatus,
  validateGovernedCapabilityAdmission,
  validateGovernedCapabilityResult,
  validateGovernedCapabilitySettlementCallback,
} from "../../loopx/control_plane/governed_capability.ts";

const authority = {
  invocation_id: "capability-synthetic",
  effect_id: "goal:agent:todo:turn",
  result_schema: "synthetic_material_result_v0",
  effect_class: "external_write",
} as const;

const transitionContract = {
  proposal_kinds: [
    "continuous_monitor_upsert",
    "continuous_monitor_complete",
  ],
  monitor_key_prefixes: ["fixture:"],
  monitor_action_kinds: ["poll_delivery"],
  monitor_target_key_prefixes: ["delivery-run:"],
  monitor_required_capabilities: ["network"],
};

const monitorUpsert = {
  schema_version: "loopx_continuous_monitor_proposal_v0",
  proposal_id: "monitor_upsert_1",
  kind: "continuous_monitor_upsert",
  monitor_key: "fixture:delivery-run",
  text: "Poll the synthetic delivery run.",
  action_kind: "poll_delivery",
  target_key: "delivery-run:synthetic-1",
  cadence: "5m",
  next_due_at: "2099-01-01T00:05:00+00:00",
  expires_at: "2099-01-02T00:00:00+00:00",
  required_capabilities: ["network"],
};

const monitorComplete = {
  schema_version: "loopx_continuous_monitor_proposal_v0",
  proposal_id: "monitor_complete_1",
  kind: "continuous_monitor_complete",
  monitor_key: "fixture:delivery-run",
  evidence: "Synthetic delivery reached a terminal state.",
};

function result(status: "running" | "succeeded" | "no_change") {
  return {
    schema_version: authority.result_schema,
    invocation_id: authority.invocation_id,
    status,
    observations: [],
    domain_state_mutations: [],
    domain_transition_receipts: [],
    transition_proposals: [],
    effect_receipt:
      status === "running"
        ? null
        : {
            schema_version: "loopx_external_effect_receipt_v0",
            invocation_id: authority.invocation_id,
            idempotency_key: authority.effect_id,
            status: status === "no_change" ? "no_change" : "committed",
            external_ref: "synthetic-run-1",
            evidence_digest: "sha256:synthetic-evidence",
          },
    follow_up: { kind: status === "running" ? "poll" : "none" },
  };
}

test("material admission binds the exact Todo action to the operation", () => {
  const admission = {
    selected_todo: {
      todo_id: "todo_material1",
      role: "agent",
      status: "open",
      action_kind: "publish_requirement",
      target_key: "requirement:REQ-1",
    },
  };
  assert.equal(
    validateGovernedCapabilityAdmission({
      admission,
      todo_id: "todo_material1",
      todo_contract: {
        action_kinds: ["publish_requirement"],
        target_key_prefixes: ["requirement:"],
      },
    }).todo_id,
    "todo_material1",
  );
  assert.throws(
    () => validateGovernedCapabilityAdmission({
      admission,
      todo_id: "todo_material1",
      todo_contract: {
        action_kinds: ["deploy_release"],
        target_key_prefixes: ["release:"],
      },
    }),
    /not authorized by selected_todo action_kind/,
  );

  assert.throws(
    () => validateGovernedCapabilityAdmission({
      admission,
      todo_id: "todo_material1",
      todo_contract: {
        action_kinds: ["publish_requirement"],
        target_key_prefixes: ["release:"],
      },
    }),
    /not authorized by selected_todo target_key/,
  );
});

test("material provider state reduces to a typed journal status", () => {
  assert.equal(
    validateGovernedCapabilityResult({
      ...authority,
      value: result("running"),
    }).journal_status,
    "running",
  );
  assert.equal(
    validateGovernedCapabilityResult({
      ...authority,
      value: result("succeeded"),
    }).journal_status,
    "ready_to_settle",
  );
});

test("running providers cannot claim partial effects", () => {
  const invalid = result("running");
  invalid.domain_state_mutations.push({ kind: "partial-write" });

  assert.throws(
    () => validateGovernedCapabilityResult({ ...authority, value: invalid }),
    /must leave domain_state_mutations empty/,
  );
});

test("running providers may propose one admitted continuous monitor", () => {
  const running = result("running");
  running.transition_proposals = [{ ...monitorUpsert }];

  const validated = validateGovernedCapabilityResult({
    ...authority,
    transition_contract: transitionContract,
    value: running,
  });

  assert.equal(validated.journal_status, "running");
  assert.deepEqual(validated.result.transition_proposals, [monitorUpsert]);
});

test("transition proposals fail closed outside profile authority", () => {
  const running = result("running");
  running.transition_proposals = [{ ...monitorUpsert }];
  assert.throws(
    () => validateGovernedCapabilityResult({ ...authority, value: running }),
    /transition_contract must be an object/,
  );

  const wrongAction = result("running");
  wrongAction.transition_proposals = [{
    ...monitorUpsert,
    action_kind: "deploy_release",
  }];
  assert.throws(
    () => validateGovernedCapabilityResult({
      ...authority,
      transition_contract: transitionContract,
      value: wrongAction,
    }),
    /action_kind is not admitted/,
  );

  const wrongMonitor = result("running");
  wrongMonitor.transition_proposals = [{
    ...monitorUpsert,
    monitor_key: "unrelated:delivery-run",
  }];
  assert.throws(
    () => validateGovernedCapabilityResult({
      ...authority,
      transition_contract: transitionContract,
      value: wrongMonitor,
    }),
    /monitor_key is not admitted/,
  );

  const wrongTarget = result("running");
  wrongTarget.transition_proposals = [{
    ...monitorUpsert,
    target_key: "unrelated:synthetic-1",
  }];
  assert.throws(
    () => validateGovernedCapabilityResult({
      ...authority,
      transition_contract: transitionContract,
      value: wrongTarget,
    }),
    /target_key is not admitted/,
  );

  const wrongCapability = result("running");
  wrongCapability.transition_proposals = [{
    ...monitorUpsert,
    required_capabilities: ["production_access"],
  }];
  assert.throws(
    () => validateGovernedCapabilityResult({
      ...authority,
      transition_contract: transitionContract,
      value: wrongCapability,
    }),
    /required_capabilities are not admitted/,
  );
});

test("running providers cannot complete a monitor", () => {
  const running = result("running");
  running.transition_proposals = [{ ...monitorComplete }];

  assert.throws(
    () => validateGovernedCapabilityResult({
      ...authority,
      transition_contract: transitionContract,
      value: running,
    }),
    /running result may only upsert a monitor/,
  );
});

test("successful providers may complete an admitted monitor", () => {
  const succeeded = result("succeeded");
  succeeded.transition_proposals = [{ ...monitorComplete }];

  const validated = validateGovernedCapabilityResult({
    ...authority,
    transition_contract: transitionContract,
    value: succeeded,
  });

  assert.equal(validated.journal_status, "ready_to_settle");
  assert.deepEqual(validated.result.transition_proposals, [monitorComplete]);
});

test("terminal effect receipts bind the exact settlement effect", () => {
  const invalid = result("succeeded");
  assert.ok(invalid.effect_receipt);
  invalid.effect_receipt.idempotency_key = "different-effect";

  assert.throws(
    () => validateGovernedCapabilityResult({ ...authority, value: invalid }),
    /idempotency_key is invalid/,
  );
});

test("terminal result and effect receipt cannot contradict each other", () => {
  const falseCommit = result("no_change");
  assert.ok(falseCommit.effect_receipt);
  falseCommit.effect_receipt.status = "committed";
  assert.throws(
    () => validateGovernedCapabilityResult({ ...authority, value: falseCommit }),
    /requires a no-change effect receipt/,
  );

  const falseNoChange = result("succeeded");
  assert.ok(falseNoChange.effect_receipt);
  falseNoChange.effect_receipt.status = "no_change";
  assert.throws(
    () => validateGovernedCapabilityResult({ ...authority, value: falseNoChange }),
    /requires a committed effect receipt/,
  );

  const mutatedNoChange = result("no_change");
  mutatedNoChange.domain_state_mutations.push({ kind: "contradictory-write" });
  assert.throws(
    () =>
      validateGovernedCapabilityResult({ ...authority, value: mutatedNoChange }),
    /must leave domain_state_mutations empty/,
  );
});

test("writeback proves the effect receipt before settlement can spend", () => {
  const context = {
    effect_id: authority.effect_id,
    effect_receipt_digest: "sha256:receipt",
    require_receipt_digest: true,
  };
  const rejected = validateGovernedCapabilitySettlementCallback({
    ...context,
    payload: {
      ok: true,
      appended: true,
      settlement_identity: { effect_id: authority.effect_id },
    },
  });
  assert.deepEqual(rejected, {
    ok: false,
    appended: false,
    reason: "effect receipt was not written back",
  });

  const committed = validateGovernedCapabilitySettlementCallback({
    ...context,
    payload: {
      ok: true,
      appended: true,
      settlement_identity: { effect_id: authority.effect_id },
      effect_receipt_digest: context.effect_receipt_digest,
    },
  });
  assert.equal(committed.ok, true);
});

test("settlement terminal state is TS-owned", () => {
  assert.equal(governedCapabilitySettlementStatus(null), "committed");
  assert.equal(
    governedCapabilitySettlementStatus({ kind: "quota_spend_rejected" }),
    "settlement_failed",
  );
});

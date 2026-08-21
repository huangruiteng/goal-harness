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

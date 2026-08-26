import assert from "node:assert/strict";
import test from "node:test";

import {
  reduceTaskLeaseAcquire,
  TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION,
} from "../../loopx/control_plane/work_items/task_lease_settlement.ts";

function preflight(overrides: Record<string, unknown> = {}) {
  return reduceTaskLeaseAcquire({
    schema_version: TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION,
    phase: "preflight",
    goal_id: "lease-goal",
    owner: "Agent One",
    todo_id: "TODO_LEASE_ITEM",
    idempotency_key: "lease-turn-1",
    write_scopes: ["src/**", "docs/**", "src/**"],
    ttl_seconds: 600,
    expected_version: null,
    ...overrides,
  });
}

function finalize(
  prepared: ReturnType<typeof preflight>,
  providerResult: Record<string, unknown>,
) {
  assert.equal(prepared.decision, "execute");
  assert.ok(prepared.transaction);
  return reduceTaskLeaseAcquire({
    schema_version: TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION,
    phase: "finalize",
    transaction: prepared.transaction,
    provider_result: providerResult,
  });
}

test("preflight owns normalized identity, plan, and one coarse provider effect", () => {
  const reduction = preflight();
  assert.equal(reduction.decision, "execute");
  assert.equal(reduction.result, null);
  assert.deepEqual(reduction.transaction && {
    goal_id: reduction.transaction.goal_id,
    owner: reduction.transaction.owner,
    todo_id: reduction.transaction.todo_id,
    idempotency_key: reduction.transaction.idempotency_key,
  }, {
    goal_id: "lease-goal",
    owner: "agent-one",
    todo_id: "todo_lease_item",
    idempotency_key: "lease-turn-1",
  });
  assert.equal(
    reduction.transaction?.identity.effect_id,
    "lease-goal:agent-one:todo_lease_item:lease-turn-1",
  );
  assert.deepEqual(reduction.provider_effect, {
    step_kind: "durable_writeback",
    action: "acquire",
    effect_id: "lease-goal:agent-one:todo_lease_item:lease-turn-1",
    effect_ref:
      "lease-goal:agent-one:todo_lease_item:lease-turn-1#durable_writeback",
    parameters: {
      goal_id: "lease-goal",
      owner: "agent-one",
      todo_id: "todo_lease_item",
      idempotency_key: "lease-turn-1",
      write_scopes: ["src/**", "docs/**", "src/**"],
      ttl_seconds: 600,
      expected_version: null,
    },
  });
  assert.deepEqual(
    (reduction.settlement_plan?.ordered_steps as Record<string, unknown>[])
      .map((step) => step.kind),
    ["validation", "durable_writeback"],
  );
  const command = String(
    (reduction.settlement_plan?.ordered_steps as Record<string, unknown>[])[1]
      ?.command_template,
  );
  assert.match(command, /--idempotency-key lease-turn-1/);
  assert.ok(command.indexOf("docs/**") < command.indexOf("src/**"));
});

test("final reduction constructs the canonical ordered success receipts", () => {
  const prepared = preflight();
  const effectId = prepared.provider_effect?.effect_id;
  const reduction = finalize(prepared, {
    effect_id: effectId,
    ok: true,
    acquired: true,
    idempotent: false,
    lease: {
      goal_id: "lease-goal",
      todo_id: "todo_lease_item",
      owner: "agent-one",
      version: 1,
    },
    lease_path: "/runtime/task-leases/todo_lease_item.json",
  });

  assert.equal(reduction.decision, "complete");
  assert.deepEqual(reduction.result?.value, {
    goal_id: "lease-goal",
    todo_id: "todo_lease_item",
    owner: "agent-one",
    version: 1,
  });
  assert.deepEqual(
    reduction.result?.receipts.map((receipt) => ({
      step: receipt.step_kind,
      status: receipt.status,
      effect_id: receipt.effect_id,
    })),
    [
      { step: "validation", status: "committed", effect_id: effectId },
      { step: "durable_writeback", status: "committed", effect_id: effectId },
    ],
  );
  assert.deepEqual(reduction.settlement_result, {
    ok: true,
    receipts: [
      {
        schema_version: "quota_settlement_receipt_v1",
        step_kind: "validation",
        status: "committed",
        effect_id: effectId,
        source_ref: "/runtime/task-leases/todo_lease_item.json",
      },
      {
        schema_version: "quota_settlement_receipt_v1",
        step_kind: "durable_writeback",
        status: "committed",
        effect_id: effectId,
        source_ref: "/runtime/task-leases/todo_lease_item.json",
      },
    ],
    failure: null,
  });
});

test("idempotent provider replay remains one identity with idempotent receipts", () => {
  const prepared = preflight();
  const reduction = finalize(prepared, {
    effect_id: prepared.provider_effect?.effect_id,
    ok: true,
    acquired: false,
    idempotent: true,
    lease: { version: 1 },
    lease_path: "/runtime/task-leases/todo_lease_item.json",
  });
  assert.equal(reduction.decision, "complete");
  assert.deepEqual(
    reduction.result?.receipts.map((receipt) => receipt.status),
    ["idempotent", "idempotent"],
  );
});

test("invalid identity fails in preflight before a provider effect exists", () => {
  const reduction = preflight({ idempotency_key: "bad key!" });
  assert.equal(reduction.decision, "failed");
  assert.equal(reduction.provider_effect, null);
  assert.equal(reduction.result?.failure?.kind, "invalid_identity");
  assert.equal(reduction.result?.failure?.step_kind, "validation");
  assert.deepEqual(reduction.result?.receipts, []);
  assert.equal(
    reduction.result?.failure?.details?.task_lease_error_code,
    "invalid_idempotency_key",
  );
});

test("provider permission denial fails validation without a committed receipt", () => {
  const prepared = preflight();
  const reduction = finalize(prepared, {
    effect_id: prepared.provider_effect?.effect_id,
    ok: false,
    error: "owner is not registered",
    error_code: "owner_not_registered",
    task_lease_payload: { owner: "agent-one" },
  });
  assert.equal(reduction.decision, "failed");
  assert.equal(reduction.result?.failure?.kind, "permission_denied");
  assert.equal(reduction.result?.failure?.step_kind, "validation");
  assert.deepEqual(reduction.result?.receipts, []);
});

test("provider write rejection preserves the validation receipt prefix", () => {
  const prepared = preflight();
  const reduction = finalize(prepared, {
    effect_id: prepared.provider_effect?.effect_id,
    ok: false,
    error: "same key has different parameters",
    error_code: "idempotency_key_reuse",
    task_lease_payload: { idempotency_reuse_kind: "acquire_parameters" },
    lease_path: "/runtime/task-leases/todo_lease_item.json",
  });
  assert.equal(reduction.decision, "failed");
  assert.equal(reduction.result?.failure?.kind, "invalid_identity");
  assert.equal(reduction.result?.failure?.step_kind, "durable_writeback");
  assert.deepEqual(
    reduction.result?.receipts.map((receipt) => ({
      step: receipt.step_kind,
      source: receipt.source_ref,
    })),
    [{
      step: "validation",
      source: "/runtime/task-leases/todo_lease_item.json",
    }],
  );
});

test("cross-effect provider result is rejected before it can overwrite receipts", () => {
  const prepared = preflight();
  const reduction = finalize(prepared, {
    effect_id: "another-goal:another-agent:todo_other:turn",
    ok: true,
    acquired: true,
    idempotent: false,
    lease: { version: 1 },
    lease_path: "/runtime/task-leases/todo_lease_item.json",
  });
  assert.equal(reduction.decision, "failed");
  assert.equal(reduction.result?.failure?.kind, "identity_mismatch");
  assert.deepEqual(
    reduction.result?.receipts.map((receipt) => receipt.step_kind),
    ["validation"],
  );
});

test("boundary rejects unsupported schema and malformed provider payloads", () => {
  assert.throws(
    () => reduceTaskLeaseAcquire({
      schema_version: "unsupported",
      phase: "preflight",
    }),
    /request schema mismatch/,
  );
  const prepared = preflight();
  assert.throws(
    () => finalize(prepared, {
      effect_id: prepared.provider_effect?.effect_id,
      ok: "yes",
    }),
    /provider_result\.ok must be a boolean/,
  );
});

test("successful providers must return a non-empty durable path", () => {
  const prepared = preflight();
  const reduction = finalize(prepared, {
    effect_id: prepared.provider_effect?.effect_id,
    ok: true,
    acquired: true,
    idempotent: false,
    lease: { version: 1 },
    lease_path: "",
  });
  assert.equal(reduction.decision, "failed");
  assert.equal(reduction.result?.failure?.kind, "writeback_missing");
  assert.deepEqual(
    reduction.result?.receipts.map((receipt) => receipt.step_kind),
    ["validation"],
  );
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  createEffectRuntimeHandlers,
  dispatchEffectRuntimeMethod,
} from "../../loopx/control_plane/effect_runtime_handlers.ts";

const handlers = createEffectRuntimeHandlers({
  fingerprint: "test-fingerprint",
  requestShutdown: () => undefined,
});

test("runtime boundary rejects incomplete settlement identity", async () => {
  await assert.rejects(
    dispatchEffectRuntimeMethod(handlers, "settlement.identity", {
      goal_id: "goal",
      turn_instance_id: "turn",
    }),
    /identity\.agent_id must be a non-empty string/,
  );
});

test("runtime boundary rejects a result carrying value and failure", async () => {
  await assert.rejects(
    dispatchEffectRuntimeMethod(handlers, "settlement.bind_gate", {
      result: {
        value: { impossible: true },
        receipts: [],
        failure: {
          kind: "permission_denied",
          step_kind: "durable_writeback",
          reason: "denied",
        },
      },
    }),
    /cannot carry both a value and a failure/,
  );
});

test("runtime boundary rejects malformed journal inspection request", async () => {
  await assert.rejects(
    dispatchEffectRuntimeMethod(handlers, "turn_journal.inspect", {
      schema_version: "unsupported",
      journal: {},
      goal_id: "goal",
      agent_id: "agent",
      turn_key: "turn",
    }),
    /request schema mismatch/,
  );
});

test("runtime boundary dispatches the task-lease acquire transaction", async () => {
  const result = await dispatchEffectRuntimeMethod(
    handlers,
    "task_lease.acquire.reduce",
    {
      schema_version: "loopx_task_lease_acquire_transaction_v0",
      phase: "preflight",
      goal_id: "lease-goal",
      owner: "lease-agent",
      todo_id: "todo_lease_item",
      idempotency_key: "lease-turn",
      write_scopes: [],
      ttl_seconds: null,
      expected_version: null,
    },
  ) as Record<string, unknown>;
  assert.equal(result.decision, "execute");
  assert.ok(result.provider_effect);
});

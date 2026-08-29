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

test("runtime exposes the native task-lease acquire transaction", async () => {
  await assert.rejects(
    dispatchEffectRuntimeMethod(handlers, "task_lease.acquire.native", {
      schema_version: "loopx_task_lease_acquire_native_v0",
    }),
    /authority must be an object/,
  );
});

test("runtime exposes the canonical task-lease acquire decision", async () => {
  const result = await dispatchEffectRuntimeMethod(
    handlers,
    "task_lease.acquire.decide",
    {
      handoff_mode: "hard_lease",
      registered_agents: ["agent-a"],
      todo: {
        todo_id: "todo-a",
        status: "open",
        claimed_by: null,
        excluded_agents: [],
      },
      lease: null,
      other_leases: [],
      command: {
        owner: "agent-a",
        idempotency_key: "lease-a",
        ttl_seconds: 600,
        write_scopes: [],
        expected_version: null,
      },
    },
  ) as Record<string, unknown>;

  assert.equal(result.outcome, "apply");
  assert.equal(result.code, "lease_acquire");
});

test("runtime exposes the canonical task-lease write-scope rule", async () => {
  const result = await dispatchEffectRuntimeMethod(
    handlers,
    "task_lease.write_scopes.overlap",
    { left: ["docs/**"], right: ["docs/reference/rfc.md"] },
  ) as Record<string, unknown>;

  assert.equal(result.overlap, true);
});

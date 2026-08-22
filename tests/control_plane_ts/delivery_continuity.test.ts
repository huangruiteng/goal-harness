import assert from "node:assert/strict";
import test from "node:test";

import {
  DELIVERY_BOUNDARY_REQUEST_SCHEMA,
  DELIVERY_CONTINUITY_REQUEST_SCHEMA,
  evaluateDeliveryBoundary,
  evaluateDeliveryContinuity,
} from "../../loopx/control_plane/turn_driver/delivery_continuity.ts";

function request(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: DELIVERY_CONTINUITY_REQUEST_SCHEMA,
    agent_id: "codex-main",
    previous_todo_id: "todo_current001",
    previous_delivery_outcome: "outcome_progress",
    current_todo: {
      todo_id: "todo_current001",
      status: "open",
      task_class: "advancement_task",
      claimed_by: "codex-main",
      actionable: true,
      capability_ready: true,
    },
    preemptions: [],
    ...overrides,
  };
}

test("same open Todo resumes after accountable progress", () => {
  assert.deepEqual(evaluateDeliveryContinuity(request()), {
    schema_version: "loopx_delivery_continuity_result_v0",
    decision: "resume_in_flight",
    reason: "same_open_todo_after_progress",
    todo_id: "todo_current001",
    delivery_boundary: "in_flight_continuation",
  });
});

test("an initially selected open advancement Todo settles as in flight", () => {
  assert.deepEqual(evaluateDeliveryBoundary({
    schema_version: DELIVERY_BOUNDARY_REQUEST_SCHEMA,
    agent_id: "codex-main",
    current_todo: request().current_todo,
    preemptions: [],
  }), {
    schema_version: "loopx_delivery_boundary_result_v0",
    delivery_boundary: "in_flight_continuation",
    reason: "open_advancement_todo",
    todo_id: "todo_current001",
  });
});

test("non-advancement and preempted selections settle strictly", () => {
  const selectedTodo = request().current_todo as Record<string, unknown>;
  assert.equal(evaluateDeliveryBoundary({
    schema_version: DELIVERY_BOUNDARY_REQUEST_SCHEMA,
    agent_id: "codex-main",
    current_todo: { ...selectedTodo, task_class: "monitor_task" },
    preemptions: [],
  }).delivery_boundary, "semantic_closeout");
  assert.equal(evaluateDeliveryBoundary({
    schema_version: DELIVERY_BOUNDARY_REQUEST_SCHEMA,
    agent_id: "codex-main",
    current_todo: selectedTodo,
    preemptions: ["autonomous_replan"],
  }).reason, "autonomous_replan");
});

test("terminal and outcome-gap anchors release normal reselection", () => {
  assert.equal(
    evaluateDeliveryContinuity(request({
      current_todo: {
        ...(request().current_todo as Record<string, unknown>),
        status: "done",
      },
    })).reason,
    "todo_not_open",
  );
  assert.equal(
    evaluateDeliveryContinuity(request({
      previous_delivery_outcome: "outcome_gap",
    })).reason,
    "previous_delivery_not_progress",
  );
});

test("typed control obligations preempt sticky delivery", () => {
  const result = evaluateDeliveryContinuity(request({
    preemptions: ["autonomous_replan", "delivery_not_allowed"],
  }));
  assert.equal(result.decision, "preempt");
  assert.equal(result.reason, "autonomous_replan");
  assert.equal(result.delivery_boundary, "semantic_closeout");
});

test("runtime decoder rejects malformed projection facts", () => {
  assert.throws(
    () => evaluateDeliveryContinuity(request({ preemptions: ["urgent prose"] })),
    /unsupported reason/,
  );
  assert.throws(
    () => evaluateDeliveryContinuity(request({
      current_todo: {
        ...(request().current_todo as Record<string, unknown>),
        actionable: "true",
      },
    })),
    /actionable must be a boolean/,
  );
});

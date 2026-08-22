import assert from "node:assert/strict";
import test from "node:test";

import {
  buildVisionCheckpoint,
  VISION_CHECKPOINT_REQUEST_SCHEMA,
} from "../../loopx/control_plane/goals/vision_checkpoint.ts";

function request(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: VISION_CHECKPOINT_REQUEST_SCHEMA,
    agent_id: "codex-main",
    agent_vision: null,
    existing_agent_vision: null,
    vision_unchanged_reason: null,
    delivery_outcome: "outcome_progress",
    active_state_next_action_would_update: false,
    delivery_boundary: "semantic_closeout",
    todo_id: "todo_current001",
    completion_todo_id: null,
    autonomous_replan_recorded: false,
    ...overrides,
  };
}

test("semantic closeout retains the strict material vision checkpoint", () => {
  const result = buildVisionCheckpoint(request());
  assert.equal(result.required, true);
  assert.equal(result.satisfied, false);
  assert.equal(result.decision, "missing_required");
  assert.deepEqual(result.triggers, [
    { kind: "material_delivery_outcome", delivery_outcome: "outcome_progress" },
  ]);
});

test("explicit in-flight progress records continuity without vision repetition", () => {
  const result = buildVisionCheckpoint(request({
    delivery_boundary: "in_flight_continuation",
  }));
  assert.equal(result.required, false);
  assert.equal(result.satisfied, true);
  assert.equal(result.decision, "not_required");
  assert.deepEqual(result.triggers, [
    { kind: "in_flight_continuation", todo_id: "todo_current001" },
  ]);
});

test("non-material delivery remains valid without opening a vision checkpoint", () => {
  const result = buildVisionCheckpoint(request({
    delivery_outcome: "surface_only",
  }));
  assert.equal(result.required, false);
  assert.equal(result.satisfied, true);
  assert.equal(result.decision, "not_required");
  assert.deepEqual(result.triggers, []);
});

test("unchanged closeout binds the exact persisted vision revision", () => {
  const result = buildVisionCheckpoint(request({
    existing_agent_vision: {
      state: "vision_active",
      generated_at: "2026-08-22T18:30:17+08:00",
    },
    vision_unchanged_reason: "Validated evidence keeps the current route intact.",
  }));
  assert.equal(result.required, true);
  assert.equal(result.satisfied, true);
  assert.equal(result.decision, "unchanged_with_reason");
  assert.deepEqual(result.continuity_basis, {
    kind: "existing_vision_unchanged",
    vision_generated_at: "2026-08-22T18:30:17+08:00",
  });
});

test("legacy vision without a revision cannot claim outcome continuity", () => {
  const result = buildVisionCheckpoint(request({
    existing_agent_vision: { state: "vision_active" },
    vision_unchanged_reason: "The legacy route is still current.",
  }));
  assert.equal(result.decision, "unchanged_with_reason");
  assert.equal("continuity_basis" in result, false);
});

test("completion, replan, and durable route changes reject in-flight claims", () => {
  assert.throws(
    () => buildVisionCheckpoint(request({
      delivery_boundary: "in_flight_continuation",
      completion_todo_id: "todo_current001",
    })),
    /conflicts with Todo completion/,
  );
  assert.throws(
    () => buildVisionCheckpoint(request({
      delivery_boundary: "in_flight_continuation",
      autonomous_replan_recorded: true,
    })),
    /conflicts with autonomous replan/,
  );
  assert.throws(
    () => buildVisionCheckpoint(request({
      delivery_boundary: "in_flight_continuation",
      active_state_next_action_would_update: true,
    })),
    /conflicts with a durable Next Action update/,
  );
});

test("only accountable agent-bound progress may be in flight", () => {
  assert.throws(
    () => buildVisionCheckpoint(request({
      delivery_boundary: "in_flight_continuation",
      delivery_outcome: "outcome_gap",
    })),
    /requires delivery_outcome=outcome_progress/,
  );
  assert.throws(
    () => buildVisionCheckpoint(request({
      delivery_boundary: "in_flight_continuation",
      todo_id: null,
    })),
    /requires an agent-bound Todo settlement/,
  );
});

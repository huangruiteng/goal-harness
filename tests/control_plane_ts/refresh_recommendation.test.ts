import assert from "node:assert/strict";
import test from "node:test";

import {
  resolveRefreshRecommendation,
} from "../../loopx/control_plane/work_items/refresh_recommendation.ts";

const baseRequest = {
  schema_version: "refresh_recommendation_request_v0",
  explicit_action: null,
  agent_id: "agent-a",
  settlement_identity: {
    effect_id: "goal-shared:agent-a:todo_selected:turn-1",
    goal_id: "goal-shared",
    agent_id: "agent-a",
    todo_id: "todo_selected",
    turn_instance_id: "turn-1",
  },
  settlement_candidate: {
    todo_id: "todo_selected",
    text: "Continue the receipt-bound slice.",
    status: "open",
    task_class: "advancement_task",
    claimed_by: "agent-a",
    selection_binding: "heartbeat_receipt",
  },
  agent_lane_candidate: {
    todo_id: "todo_higher_priority",
    text: "Start a newer higher-priority slice.",
    status: "open",
    task_class: "advancement_task",
    claimed_by: "agent-a",
  },
  active_state_next_action: "Follow another agent's shared action.",
  unscoped_agent_todo_fallback: null,
  default_action: "Inspect refreshed state.",
};

test("exact settlement binding outranks lane re-selection and shared prose", () => {
  const result = resolveRefreshRecommendation(baseRequest);

  assert.equal(result.recommended_action, "Continue the receipt-bound slice.");
  assert.equal(result.recommended_action_source, "settlement_bound_todo");
  assert.equal(result.authority, "settlement");
  assert.equal(result.settlement_alignment, "exact");
  assert.equal(result.todo_id, "todo_selected");
});

test("ineligible settlement Todo falls through to a runnable lane candidate", () => {
  const result = resolveRefreshRecommendation({
    ...baseRequest,
    settlement_candidate: {
      ...baseRequest.settlement_candidate,
      status: "blocked",
    },
  });

  assert.equal(result.recommended_action, "Start a newer higher-priority slice.");
  assert.equal(result.recommended_action_source, "agent_lane_selected_todo");
  assert.equal(result.settlement_alignment, "unavailable");
  assert.equal(result.settlement_gap_reason, "candidate_ineligible");
});

test("a peer-claimed lane candidate cannot shadow the shared fallback", () => {
  const result = resolveRefreshRecommendation({
    ...baseRequest,
    settlement_identity: null,
    settlement_candidate: null,
    agent_lane_candidate: {
      ...baseRequest.agent_lane_candidate,
      claimed_by: "agent-b",
    },
  });

  assert.equal(result.recommended_action, "Follow another agent's shared action.");
  assert.equal(result.recommended_action_source, "active_state_next_action");
});

test("agent-scoped resolution never consumes the unscoped compatibility lane", () => {
  const result = resolveRefreshRecommendation({
    ...baseRequest,
    settlement_identity: null,
    settlement_candidate: null,
    agent_lane_candidate: null,
    active_state_next_action: null,
    unscoped_agent_todo_fallback: {
      todo_id: "todo_peer_only",
      text: "Run the peer-only Todo.",
      status: "open",
      task_class: "advancement_task",
      claimed_by: "agent-b",
    },
  });

  assert.equal(result.recommended_action, "Inspect refreshed state.");
  assert.equal(result.recommended_action_source, "default_refresh_action");
});

test("an unclaimed agent-lane candidate preserves its claim prerequisite", () => {
  const result = resolveRefreshRecommendation({
    ...baseRequest,
    settlement_identity: null,
    settlement_candidate: null,
    agent_lane_candidate: {
      ...baseRequest.agent_lane_candidate,
      claimed_by: undefined,
      claim_required_before_work: true,
    },
  });

  assert.equal(result.recommended_action_source, "agent_lane_selected_todo");
  assert.equal(result.claim_required_before_work, true);
});

test("missing settlement Todo is a typed gap before legal lane fallback", () => {
  const result = resolveRefreshRecommendation({
    ...baseRequest,
    settlement_candidate: null,
  });

  assert.equal(result.recommended_action_source, "agent_lane_selected_todo");
  assert.equal(result.settlement_alignment, "unavailable");
  assert.equal(result.settlement_gap_reason, "candidate_missing");
});

test("settlement identity drift is rejected instead of trusted as read-model input", () => {
  assert.throws(
    () =>
      resolveRefreshRecommendation({
        ...baseRequest,
        settlement_identity: {
          ...baseRequest.settlement_identity,
          effect_id: "goal-shared:agent-a:todo_other:turn-1",
        },
      }),
    /effect_id mismatch/,
  );
});

test("explicit recommendation remains authoritative", () => {
  const result = resolveRefreshRecommendation({
    ...baseRequest,
    explicit_action: "Record the validated successor.",
  });

  assert.equal(result.recommended_action, "Record the validated successor.");
  assert.equal(result.recommended_action_source, "explicit_arg");
  assert.equal(result.authority, "explicit");
  assert.equal(result.settlement_alignment, "not_applicable");
});

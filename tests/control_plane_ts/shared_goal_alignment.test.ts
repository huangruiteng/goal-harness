import assert from "node:assert/strict";
import test from "node:test";

import {
  SHARED_GOAL_ALIGNMENT_SCHEMA_VERSION,
  projectSharedGoalAlignment,
} from "../../loopx/control_plane/goals/shared_goal_alignment.ts";

const DIGEST = "sha256:" + "a".repeat(64);

function baseRequest(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "shared_goal_alignment_request_v0",
    goal_id: "goal-shared",
    agent_id: "agent-a",
    canonical_goal: {
      goal_revision: 42,
      intent_digest: DIGEST,
      revision_basis: "state_event_log",
      state_updated_at: "2026-09-01T00:00:00+00:00",
    },
    frontier_basis: {
      based_on_goal_revision: 42,
      basis_source: "state_event_log",
      last_agent_event_id: "evt_agent_a_last",
    },
    frontier_counts: {
      current_agent_claimed_advancement_count: 1,
      unclaimed_advancement_count: 2,
      other_agent_claimed_advancement_count: 0,
    },
    claims: [
      {
        todo_id: "todo_lane_a",
        claimed_by: "agent-a",
        lease_epoch: 2,
        lease_owner: "agent-a",
      },
    ],
    unclaimed_eligible: [
      { todo_id: "todo_lane_b", task_class: "advancement_task", action_kind: "run" },
      { todo_id: "todo_lane_c", task_class: "advancement_task" },
    ],
    peer_claimed_bound_todo_ids: [],
    open_lane_replan_obligation_required: false,
    ...overrides,
  };
}

test("projects the full read-only alignment from typed facts", () => {
  const result = projectSharedGoalAlignment(baseRequest());

  assert.equal(result.schema_version, SHARED_GOAL_ALIGNMENT_SCHEMA_VERSION);
  assert.equal(result.goal_id, "goal-shared");
  assert.equal(result.agent_id, "agent-a");
  assert.equal(result.canonical_goal.goal_revision, 42);
  assert.equal(result.canonical_goal.intent_digest, DIGEST);
  assert.equal(result.frontier_basis.based_on_goal_revision, 42);
  assert.equal(
    result.frontier_counts.unclaimed_advancement_count,
    2,
  );
  assert.deepEqual(result.unclaimed_eligible_work, [
    { todo_id: "todo_lane_b", claim_required_before_work: true },
    { todo_id: "todo_lane_c", claim_required_before_work: true },
  ]);
  assert.deepEqual(result.drift_facts, []);
  assert.deepEqual(result.conflict_facts, []);
  assert.equal(result.read_only, true);
});

test("a frontier basis behind the canonical revision drifts stale", () => {
  const result = projectSharedGoalAlignment(
    baseRequest({
      frontier_basis: {
        based_on_goal_revision: 39,
        basis_source: "state_event_log",
        last_agent_event_id: "evt_agent_a_39",
      },
    }),
  );

  assert.deepEqual(result.drift_facts, ["frontier_basis_stale"]);
  assert.deepEqual(result.conflict_facts, []);
});

test("an equal frontier basis never drifts stale", () => {
  const result = projectSharedGoalAlignment(baseRequest());

  assert.deepEqual(result.drift_facts, []);
});

test("an unbound frontier basis is unverifiable, never stale", () => {
  const result = projectSharedGoalAlignment(
    baseRequest({
      canonical_goal: {
        goal_revision: 0,
        intent_digest: DIGEST,
        revision_basis: "markdown_active_state",
        state_updated_at: null,
      },
      frontier_basis: {
        based_on_goal_revision: null,
        basis_source: "unbound",
        last_agent_event_id: null,
      },
    }),
  );

  assert.deepEqual(result.drift_facts, []);
  assert.deepEqual(result.conflict_facts, ["frontier_basis_unverifiable"]);
  assert.equal(result.canonical_goal.goal_revision, 0);
});

test("mixed revision bases are rejected instead of compared", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({
          canonical_goal: {
            goal_revision: 0,
            intent_digest: DIGEST,
            revision_basis: "markdown_active_state",
            state_updated_at: null,
          },
        }),
      ),
    /cannot be compared/,
  );
});

test("conflict facts project from lease, replan, and peer-claim facts", () => {
  const result = projectSharedGoalAlignment(
    baseRequest({
      claims: [
        {
          todo_id: "todo_lane_a",
          claimed_by: "agent-a",
          lease_epoch: 2,
          lease_owner: "agent-b",
        },
      ],
      peer_claimed_bound_todo_ids: ["todo_peer_claimed"],
      open_lane_replan_obligation_required: true,
    }),
  );

  assert.deepEqual(result.drift_facts, []);
  assert.deepEqual(result.conflict_facts, [
    "lease_owner_mismatch",
    "open_lane_replan_obligation",
    "peer_claimed_lane_conflict",
  ]);
});

test("a matching lease owner is not a conflict", () => {
  const result = projectSharedGoalAlignment(baseRequest());

  assert.ok(!result.conflict_facts.includes("lease_owner_mismatch"));
});

test("request schema mismatch is rejected", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({ schema_version: "shared_goal_alignment_request_v1" }),
      ),
    /schema mismatch/,
  );
});

test("unknown todo shape in unclaimed eligible work is rejected", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({
          unclaimed_eligible: [
            { todo_id: "todo_lane_b", task_class: "continuous_monitor" },
          ],
        }),
      ),
    /task_class must be advancement_task/,
  );
});

test("a claim owned by another agent is rejected", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({
          claims: [
            {
              todo_id: "todo_peer_claimed",
              claimed_by: "agent-b",
              lease_epoch: 1,
              lease_owner: "agent-b",
            },
          ],
        }),
      ),
    /claimed_by must match the projected agent/,
  );
});

test("a digest that is not a typed-facts sha256 envelope is rejected", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({
          canonical_goal: {
            goal_revision: 42,
            intent_digest: "md5:zz",
            revision_basis: "state_event_log",
            state_updated_at: null,
          },
        }),
      ),
    /intent_digest/,
  );
});

test("an unbound basis with a fabricated revision is rejected", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({
          frontier_basis: {
            based_on_goal_revision: 7,
            basis_source: "unbound",
            last_agent_event_id: null,
          },
        }),
      ),
    /must be null when basis_source is unbound/,
  );
});

test("a todo both claimed and unclaimed-eligible is rejected", () => {
  assert.throws(
    () =>
      projectSharedGoalAlignment(
        baseRequest({
          unclaimed_eligible: [
            { todo_id: "todo_lane_a", task_class: "advancement_task" },
          ],
        }),
      ),
    /already claimed/,
  );
});

import assert from "node:assert/strict";
import test from "node:test";

import {
  buildVisionCheckpoint,
  VISION_REFRESH_PREPARED_SCHEMA_VERSION,
  VISION_REFRESH_REQUEST_SCHEMA,
} from "../../loopx/control_plane/goals/vision_checkpoint.ts";

function finalizeRequest(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: VISION_REFRESH_REQUEST_SCHEMA,
    phase: "finalize",
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

function prepareRequest(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: VISION_REFRESH_REQUEST_SCHEMA,
    phase: "prepare",
    goal_id: "goal-main",
    agent_id: "codex-main",
    agent_vision_packet: {
      state: "vision_patch_proposed",
      vision_patch: {
        vision_summary: "Ship one bounded route.",
      },
    },
    existing_agent_vision: null,
    merge_patch: false,
    require_path_delta_for_durable_change: false,
    ...overrides,
  };
}

test("prepare owns packet normalization, budgets, and path delta", () => {
  const result = buildVisionCheckpoint(prepareRequest({
    agent_vision_packet: {
      goal_id: "goal-main",
      agent_id: "codex-main",
      state: "closed",
      vision_patch: {
        vision_summary: "  Ship   one bounded route.  ",
        role_scope: "Own the route.",
        acceptance_summary: "The route produces evidence.",
        advancement_policy: "repeat-until-closed",
      },
      path_delta: {
        outcome: "replan",
        prior_assumption: "The old route remained viable.",
        observed_reality: "Fresh evidence invalidated it.",
        changed: ["Use the bounded successor."],
      },
      todo_delta: [" create_successor "],
      validation: { write_correctness_checked: true },
    },
  }));

  assert.equal(result.schema_version, VISION_REFRESH_PREPARED_SCHEMA_VERSION);
  const vision = result.agent_vision as Record<string, unknown>;
  assert.equal(vision.state, "vision_closed");
  assert.deepEqual(vision.vision_patch, {
    vision_summary: "Ship one bounded route.",
    role_scope: "Own the route.",
    acceptance_summary: "The route produces evidence.",
    advancement_policy: "repeat_until_closed",
  });
  assert.deepEqual(vision.todo_delta, ["create_successor"]);
  assert.deepEqual(vision.path_delta, {
    schema_version: "goal_path_delta_v0",
    outcome: "replan",
    prior_assumption: "The old route remained viable.",
    observed_reality: "Fresh evidence invalidated it.",
    changed: ["Use the bounded successor."],
  });
  assert.deepEqual(vision.validation, {
    write_correctness_checked: true,
    budget_checked: true,
    budget_status: "ok",
  });
});

test("prepare preserves v0 JSON-to-text compatibility", () => {
  const result = buildVisionCheckpoint(prepareRequest({
    agent_vision_packet: {
      vision_summary: true,
      todo_delta: [["one", "two"], { route: "bounded" }, {}],
      path_delta: {
        outcome: "replan",
        prior_assumption: { route: "old" },
        observed_reality: "Fresh evidence invalidated it.",
        changed: ["Use the bounded successor."],
      },
    },
  }));

  const vision = result.agent_vision as Record<string, unknown>;
  assert.deepEqual(vision.vision_patch, { vision_summary: "True" });
  assert.deepEqual(vision.todo_delta, [
    "['one', 'two']",
    "{'route': 'bounded'}",
  ]);
  assert.equal(
    (vision.path_delta as Record<string, unknown>).prior_assumption,
    "{'route': 'old'}",
  );
});

test("prepare merges a patch and requires an explicit durable replan", () => {
  const existing = {
    state: "vision_active",
    vision_patch: {
      vision_summary: "Old route.",
      role_scope: "Own framing.",
      acceptance_summary: "Produce evidence.",
      advancement_policy: "as_needed",
    },
  };
  const agentVisionPacket = {
    vision_patch: { vision_summary: "New route." },
    path_delta: {
      outcome: "replan",
      prior_assumption: "The old route would hold.",
      observed_reality: "New evidence changed the route.",
      changed: ["Use the new route."],
    },
  };
  const result = buildVisionCheckpoint(prepareRequest({
    agent_vision_packet: agentVisionPacket,
    existing_agent_vision: existing,
    merge_patch: true,
    require_path_delta_for_durable_change: true,
  }));
  assert.deepEqual(
    (result.agent_vision as Record<string, unknown>).vision_patch,
    {
      vision_summary: "New route.",
      role_scope: "Own framing.",
      acceptance_summary: "Produce evidence.",
      advancement_policy: "as_needed",
    },
  );

  assert.throws(
    () => buildVisionCheckpoint(prepareRequest({
      agent_vision_packet: { vision_patch: { vision_summary: "New route." } },
      existing_agent_vision: existing,
      merge_patch: true,
      require_path_delta_for_durable_change: true,
    })),
    /provide goal_path_delta_v0 with outcome=replan/,
  );
});

test("prepare rejects identity drift, private text, and typed budget overflow", () => {
  assert.throws(
    () => buildVisionCheckpoint(prepareRequest({
      agent_vision_packet: {
        goal_id: "other-goal",
        vision_summary: "Bounded route.",
      },
    })),
    /does not match/,
  );
  assert.throws(
    () => buildVisionCheckpoint(prepareRequest({
      agent_vision_packet: {
        vision_summary: "Read \/Users\/owner\/private.txt",
      },
    })),
    /contains a private-looking value/,
  );
  assert.throws(
    () => buildVisionCheckpoint(prepareRequest({
      agent_vision_packet: { vision_summary: "x".repeat(421) },
    })),
    (error: unknown) => {
      const rejection = error as { code?: string; message?: string };
      assert.equal(
        rejection.code,
        "vision_budget_exceeded",
      );
      assert.match(rejection.message ?? "", /suggested compact value/);
      assert.ok((rejection.message ?? "").length <= 240);
      return true;
    },
  );
});

test("prepare rejects incomplete and over-wide path deltas", () => {
  assert.throws(
    () => buildVisionCheckpoint(prepareRequest({
      agent_vision_packet: {
        vision_summary: "Bounded route.",
        path_delta: { outcome: "replan" },
      },
    })),
    /requires prior_assumption and observed_reality/,
  );
  assert.throws(
    () => buildVisionCheckpoint(prepareRequest({
      agent_vision_packet: {
        vision_summary: "Bounded route.",
        path_delta: {
          outcome: "replan",
          prior_assumption: "Old assumption.",
          observed_reality: "New reality.",
          retained: ["one", "two", "three", "four"],
        },
      },
    })),
    /path_delta.retained has 4 items; limit is 3/,
  );
});

test("pure prepare and finalize reductions replay deterministically", () => {
  const prepare = prepareRequest();
  assert.deepEqual(
    buildVisionCheckpoint(prepare),
    buildVisionCheckpoint(prepare),
  );
  const finalize = finalizeRequest({
    agent_vision: (buildVisionCheckpoint(prepare) as Record<string, unknown>)
      .agent_vision,
  });
  assert.deepEqual(
    buildVisionCheckpoint(finalize),
    buildVisionCheckpoint(finalize),
  );
});

test("semantic closeout retains the strict material vision checkpoint", () => {
  const result = buildVisionCheckpoint(finalizeRequest());
  assert.equal(result.required, true);
  assert.equal(result.satisfied, false);
  assert.equal(result.decision, "missing_required");
  assert.deepEqual(result.triggers, [
    { kind: "material_delivery_outcome", delivery_outcome: "outcome_progress" },
  ]);
});

test("explicit in-flight progress records continuity without vision repetition", () => {
  const result = buildVisionCheckpoint(finalizeRequest({
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
  const result = buildVisionCheckpoint(finalizeRequest({
    delivery_outcome: "surface_only",
  }));
  assert.equal(result.required, false);
  assert.equal(result.satisfied, true);
  assert.equal(result.decision, "not_required");
  assert.deepEqual(result.triggers, []);
});

test("unchanged closeout binds the exact persisted vision revision", () => {
  const result = buildVisionCheckpoint(finalizeRequest({
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
  const result = buildVisionCheckpoint(finalizeRequest({
    existing_agent_vision: { state: "vision_active" },
    vision_unchanged_reason: "The legacy route is still current.",
  }));
  assert.equal(result.decision, "unchanged_with_reason");
  assert.equal("continuity_basis" in result, false);
});

test("completion, replan, and durable route changes reject in-flight claims", () => {
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      delivery_boundary: "in_flight_continuation",
      completion_todo_id: "todo_current001",
    })),
    /conflicts with Todo completion/,
  );
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      delivery_boundary: "in_flight_continuation",
      autonomous_replan_recorded: true,
    })),
    /conflicts with autonomous replan/,
  );
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      delivery_boundary: "in_flight_continuation",
      active_state_next_action_would_update: true,
    })),
    /conflicts with a durable Next Action update/,
  );
});

test("only accountable agent-bound progress may be in flight", () => {
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      delivery_boundary: "in_flight_continuation",
      delivery_outcome: "outcome_gap",
    })),
    /requires delivery_outcome=outcome_progress/,
  );
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      delivery_boundary: "in_flight_continuation",
      todo_id: null,
    })),
    /requires an agent-bound Todo settlement/,
  );
});

test("finalize owns unchanged-reason public safety and budget", () => {
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      vision_unchanged_reason: "Read \/Users\/owner\/private.txt",
    })),
    /contains a private-looking value/,
  );
  assert.throws(
    () => buildVisionCheckpoint(finalizeRequest({
      vision_unchanged_reason: "x".repeat(241),
    })),
    /vision_unchanged_reason exceeds 240 chars/,
  );
});

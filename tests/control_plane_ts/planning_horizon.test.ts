import assert from "node:assert/strict";
import test from "node:test";

import {
  PLANNING_HORIZON_REQUEST_SCHEMA_VERSION,
  projectQuotaPlanningHorizon,
} from "../../loopx/control_plane/work_items/planning_horizon.ts";

function todo(
  todoId: string,
  index: number,
  priority: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    todo_id: todoId,
    index,
    text: `Deliver ${todoId}.`,
    priority,
    status: "open",
    task_class: "advancement_task",
    action_kind: `deliver_${index}`,
    claimed_by: "codex-planning",
    ...overrides,
  };
}

function request(overrides: Record<string, unknown> = {}) {
  const selected = todo("todo_regression_gate", 5, "P1");
  return {
    schema_version: PLANNING_HORIZON_REQUEST_SCHEMA_VERSION,
    goal_id: "planning-horizon-fixture",
    agent_id: "codex-planning",
    selected_todo: selected,
    candidates: [selected],
    runnable_todo_ids: [selected.todo_id],
    source_context_todo_count: 1,
    acceptance_gaps: [],
    ...overrides,
  };
}

test("planning horizon preserves the typed strategic chain around local selected work", () => {
  const facts = todo("todo_facts_source", 1, "P0", {
    status: "deferred",
    resume_when: "pr_merged:#fixture-source",
    successor_todo_ids: ["todo_allowlist_policy"],
  });
  const allowlist = todo("todo_allowlist_policy", 2, "P0", {
    status: "deferred",
    resume_when: "todo_done:todo_facts_source",
    successor_todo_ids: ["todo_runtime_admission"],
  });
  const runtime = todo("todo_runtime_admission", 3, "P0", {
    status: "deferred",
    resume_when: "todo_done:todo_allowlist_policy",
    successor_todo_ids: ["todo_per_model_tests"],
  });
  const tests = todo("todo_per_model_tests", 4, "P1", {
    status: "deferred",
    resume_when: "todo_done:todo_runtime_admission",
    successor_todo_ids: ["todo_regression_gate"],
  });
  const selected = todo("todo_regression_gate", 5, "P1");
  const result = projectQuotaPlanningHorizon(request({
    selected_todo: selected,
    candidates: [selected, facts, allowlist, runtime, tests],
    source_context_todo_count: 5,
    acceptance_gaps: [{
      kind: "vision_acceptance_gap",
      source: "latest_agent_vision",
      acceptance_summary: "Prove policy, admission, and model coverage before treating the regression gate as sufficient.",
      replan_trigger_summary: "The local gate does not establish the upstream allowlist policy.",
      advancement_policy: "repeat_until_closed",
    }],
  }));

  assert.equal(result?.schema_version, "quota_planning_horizon_v0");
  assert.equal(result?.mode, "read_only");
  assert.deepEqual(
    (result?.work_items as Array<Record<string, unknown>>).map((item) => item.todo_id),
    [
      "todo_regression_gate",
      "todo_per_model_tests",
      "todo_runtime_admission",
      "todo_allowlist_policy",
      "todo_facts_source",
    ],
  );
  assert.deepEqual(result?.attention_todo_ids, [
    "todo_per_model_tests",
    "todo_runtime_admission",
    "todo_allowlist_policy",
  ]);
  assert.deepEqual(
    (result?.relations as Array<Record<string, unknown>>).filter(
      (relation) => relation.relation === "successor",
    ),
    [
      {
        from_todo_id: "todo_per_model_tests",
        to_ref: "todo_regression_gate",
        relation: "successor",
        enforcement: "lineage_only",
      },
      {
        from_todo_id: "todo_runtime_admission",
        to_ref: "todo_per_model_tests",
        relation: "successor",
        enforcement: "lineage_only",
      },
      {
        from_todo_id: "todo_allowlist_policy",
        to_ref: "todo_runtime_admission",
        relation: "successor",
        enforcement: "lineage_only",
      },
      {
        from_todo_id: "todo_facts_source",
        to_ref: "todo_allowlist_policy",
        relation: "successor",
        enforcement: "lineage_only",
      },
    ],
  );
  assert.deepEqual(result?.selection_contract, {
    selected_todo_authority: "$.selected_todo",
    action_choice_authority: "$.action_portfolio",
    horizon_changes_selection: false,
    explicit_selection_required_for_other_work: true,
  });
  assert.equal(
    (result?.completeness as Record<string, unknown>).complete,
    true,
  );
});

test("planning horizon reports every bounded omission instead of claiming completeness", () => {
  const selected = todo("todo_selected001", 9, "P2");
  const candidates = Array.from({ length: 9 }, (_, index) =>
    todo(`todo_context${String(index).padStart(3, "0")}`, index, "P0", {
      successor_todo_ids: index < 8
        ? [`todo_context${String(index + 1).padStart(3, "0")}`]
        : [selected.todo_id],
    })
  );
  const result = projectQuotaPlanningHorizon(request({
    selected_todo: selected,
    candidates: [selected, ...candidates],
    runnable_todo_ids: [selected.todo_id],
    source_context_todo_count: 13,
    acceptance_gaps: [
      { kind: "gap_one", acceptance_summary: "a".repeat(500) },
      { kind: "gap_two", acceptance_summary: "second" },
      { kind: "gap_three", acceptance_summary: "third" },
    ],
  }));
  const completeness = result?.completeness as Record<string, unknown>;

  assert.equal((result?.work_items as unknown[]).length, 5);
  assert.equal((result?.relations as unknown[]).length, 5);
  assert.equal((result?.acceptance_gaps as unknown[]).length, 2);
  assert.equal(completeness.source_unrepresented_todo_count, 3);
  assert.equal(completeness.omitted_candidate_todo_count, 5);
  assert.equal(completeness.omitted_relation_count, 4);
  assert.equal(completeness.omitted_acceptance_gap_count, 1);
  assert.equal(completeness.compact_field_truncation_count, 1);
  assert.equal(completeness.complete, false);
});

test("planning horizon never infers dependency edges from Todo prose", () => {
  const selected = todo("todo_selected001", 2, "P1");
  const proseOnly = todo("todo_prose001", 1, "P0", {
    text: "This prose says it depends on todo_selected001 but carries no typed relation.",
  });
  const result = projectQuotaPlanningHorizon(request({
    selected_todo: selected,
    candidates: [selected, proseOnly],
    runnable_todo_ids: [selected.todo_id, proseOnly.todo_id],
    source_context_todo_count: 2,
  }));

  assert.equal(result, null);
});

test("planning horizon omits flat runnable alternatives already owned by the action portfolio", () => {
  const selected = todo("todo_selected001", 2, "P1");
  const alternatives = Array.from({ length: 8 }, (_, index) =>
    todo(`todo_alternative${index}`, index, "P0")
  );

  const result = projectQuotaPlanningHorizon(request({
    selected_todo: selected,
    candidates: [selected, ...alternatives],
    runnable_todo_ids: [selected.todo_id, ...alternatives.map((item) => item.todo_id)],
    source_context_todo_count: 12,
  }));

  assert.equal(result, null);
});

test("planning horizon keeps waiting context ahead of flat runnable alternatives", () => {
  const selected = todo("todo_selected001", 20, "P1");
  const alternatives = Array.from({ length: 8 }, (_, index) =>
    todo(`todo_alternative${index}`, index, "P0")
  );
  const waiting = todo("todo_waiting001", 19, "P1", {
    status: "deferred",
    resume_when: "pr_merged:owner/repo#123",
  });

  const result = projectQuotaPlanningHorizon(request({
    selected_todo: selected,
    candidates: [selected, ...alternatives, waiting],
    runnable_todo_ids: [selected.todo_id, ...alternatives.map((item) => item.todo_id)],
    source_context_todo_count: 10,
  }));
  const projected = result?.work_items as Array<Record<string, unknown>>;

  assert.equal(projected[0].todo_id, selected.todo_id);
  assert.equal(projected[1].todo_id, waiting.todo_id);
  assert.equal(projected[1].planning_state, "waiting");
  assert.equal(
    (result?.relations as Array<Record<string, unknown>>)[0].relation,
    "resumes_when",
  );
  assert.equal(
    (result?.completeness as Record<string, unknown>).complete,
    false,
  );
});

test("planning horizon rejects malformed typed identities and unbounded source lists", () => {
  assert.throws(
    () => projectQuotaPlanningHorizon(request({
      candidates: [{ todo_id: "not-a-todo", text: "Malformed." }],
    })),
    /public Todo id/,
  );
  assert.throws(
    () => projectQuotaPlanningHorizon(request({
      candidates: Array.from({ length: 33 }, (_, index) =>
        todo(`todo_overflow${index}`, index, "P2")
      ),
    })),
    /at most 32 items/,
  );
});

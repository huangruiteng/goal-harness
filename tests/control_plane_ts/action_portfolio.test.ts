import assert from "node:assert/strict";
import test from "node:test";

import {
  ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
  ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
  projectQuotaActionPortfolio,
  qualifyActionSelection,
} from "../../loopx/control_plane/work_items/action_portfolio.ts";
import {
  TODO_PLANNING_INVENTORY_REQUEST_SCHEMA_VERSION,
  projectTodoPlanningInventory,
} from "../../loopx/control_plane/work_items/planning_inventory.ts";

function candidate(todoId: string, text: string, priority: string) {
  return {
    todo_id: todoId,
    text,
    priority,
    status: "open",
    task_class: "advancement_task",
    claimed_by: "codex-main",
    required_capabilities: [`capability_${todoId}`],
    required_write_scopes: [`artifacts/${todoId}/**`],
    continuation_hint: `Continue ${todoId} from its latest validated boundary.`,
  };
}

function request(
  primary: Record<string, unknown>,
  candidates: Record<string, unknown>[],
  unavailable: Record<string, unknown>[] = [],
  maxAlternativeActions?: number,
) {
  const sourceItems = [primary, ...candidates, ...unavailable];
  return {
    schema_version: ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION,
    planning_inventory: projectTodoPlanningInventory({
      schema_version: TODO_PLANNING_INVENTORY_REQUEST_SCHEMA_VERSION,
      goal_id: "action-portfolio-fixture",
      agent_id: "codex-main",
      selected_todo: primary,
      source_items: sourceItems,
      runnable_candidates: [primary, ...candidates],
      unavailable_higher_priority: unavailable,
      source_context_todo_count: new Set(sourceItems.map((item) => item.todo_id)).size,
    }),
    ...(maxAlternativeActions === undefined
      ? {}
      : { max_alternative_actions: maxAlternativeActions }),
  };
}

test("action portfolio exposes one recommendation and bounded selectable alternatives", () => {
  const primary = candidate("todo_primary001", "Run the primary slice.", "P0");
  const result = projectQuotaActionPortfolio(request(
    primary,
    [
      primary,
      candidate("todo_fallback001", "Run fallback one.", "P1"),
      candidate("todo_fallback001", "Duplicate fallback one.", "P1"),
      candidate("todo_fallback002", "Run fallback two.", "P2"),
      candidate("todo_fallback003", "Run fallback three.", "P3"),
    ],
    [],
    2,
  ));

  assert.equal(result?.schema_version, "quota_action_portfolio_v2");
  assert.deepEqual(result?.selection_policy, {
    decision_owner: "agent",
    mode: "explicit_turn_binding",
    recommendation_role: "default_not_binding",
    requires_explicit_turn_binding: true,
    direct_delivery_before_selection: false,
    max_alternative_actions: 2,
    candidate_scope: "current_authoritative_eligible_todos",
    suggestions_exhaustive: false,
  });
  assert.deepEqual(result?.suggested_actions, [
    {
      todo_id: "todo_primary001",
      text: "Run the primary slice.",
      priority: "P0",
      required_capabilities: ["capability_todo_primary001"],
      required_write_scopes: ["artifacts/todo_primary001/**"],
      continuation_hint: "Continue todo_primary001 from its latest validated boundary.",
      selection_role: "recommended",
    },
    {
      todo_id: "todo_fallback001",
      text: "Run fallback one.",
      priority: "P1",
      required_capabilities: ["capability_todo_fallback001"],
      required_write_scopes: ["artifacts/todo_fallback001/**"],
      continuation_hint: "Continue todo_fallback001 from its latest validated boundary.",
      selection_role: "alternative",
    },
    {
      todo_id: "todo_fallback002",
      text: "Run fallback two.",
      priority: "P2",
      required_capabilities: ["capability_todo_fallback002"],
      required_write_scopes: ["artifacts/todo_fallback002/**"],
      continuation_hint: "Continue todo_fallback002 from its latest validated boundary.",
      selection_role: "alternative",
    },
  ]);
});

test("future or blocked higher priority work keeps the portfolio visible", () => {
  const primary = candidate("todo_fallback001", "Run the ready fallback.", "P1");
  const result = projectQuotaActionPortfolio(request(primary, [], [
      {
        ...candidate("todo_monitor001", "Poll at the next window.", "P0"),
        task_class: "continuous_monitor",
        availability_reason: "scheduled_for_future",
        next_due_at: "2099-01-01T00:00:00Z",
      },
    ]));

  assert.equal(
    (result?.unavailable_higher_priority as Array<Record<string, unknown>>)[0]
      .availability_reason,
    "scheduled_for_future",
  );
  assert.equal(
    (result?.selection_policy as Record<string, unknown>)
      .requires_explicit_turn_binding,
    false,
  );
});

test("a single primary needs no redundant portfolio", () => {
  const primary = candidate("todo_primary001", "Run the only slice.", "P0");
  assert.equal(projectQuotaActionPortfolio(request(primary, [])), null);
});

test("an unclaimed selected action preserves the claim-before-work boundary", () => {
  const primary = {
    ...candidate("todo_primary001", "Run the unclaimed primary slice.", "P0"),
    claimed_by: undefined,
  };
  const result = projectQuotaActionPortfolio(request(primary, [
    candidate("todo_fallback001", "Run the claimed fallback.", "P1"),
  ]));
  const suggestions = result?.suggested_actions as Array<Record<string, unknown>>;

  assert.equal(suggestions[0].selection_role, "recommended");
  assert.equal(suggestions[0].claim_required_before_work, true);
  assert.equal("claim_required_before_work" in suggestions[1], false);
});

test("malformed candidates fail closed at the typed boundary", () => {
  assert.throws(
    () => projectQuotaActionPortfolio(request(
      candidate("todo_primary001", "Run the primary slice.", "P0"),
      [{ text: "missing typed identity" }],
    )),
    /todo_id/,
  );
  assert.throws(
    () => projectQuotaActionPortfolio(request(
      candidate("todo_primary001", "Run the primary slice.", "P0"),
      [
        {
          ...candidate("todo_blocked001", "Blocked work.", "P1"),
          status: "blocked",
        },
      ],
    )),
    /status must be open/,
  );
  assert.throws(
    () => projectQuotaActionPortfolio(request(
      candidate("todo_primary001", "Run the primary slice.", "P0"),
      [
        {
          ...candidate("todo_contract001", "Malformed contract.", "P1"),
          required_write_scopes: "artifacts/**",
        },
      ],
    )),
    /required_write_scopes must be an array of strings/,
  );
});

test("pending selection qualifies only after current hard-lane arbitration", () => {
  const successor = candidate(
    "todo_successor001",
    "Run the visible successor slice.",
    "P1",
  );
  const qualified = qualifyActionSelection({
    schema_version: ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
    requested_todo_id: successor.todo_id,
    candidate: successor,
    should_run: true,
    normal_delivery_allowed: true,
    delivery_preemptions: [],
  });
  assert.equal(qualified.state, "qualified");
  assert.deepEqual(qualified.selected_todo, {
    todo_id: successor.todo_id,
    text: successor.text,
    priority: successor.priority,
    required_capabilities: successor.required_capabilities,
    required_write_scopes: successor.required_write_scopes,
    continuation_hint: successor.continuation_hint,
    selection_binding: "pending_action_selection",
  });

  const deferred = qualifyActionSelection({
    schema_version: ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
    requested_todo_id: successor.todo_id,
    candidate: successor,
    should_run: true,
    normal_delivery_allowed: true,
    delivery_preemptions: ["blocking_work_lane"],
  });
  assert.deepEqual(deferred, {
    schema_version: "action_selection_qualification_v0",
    state: "deferred",
    requested_todo_id: successor.todo_id,
    reason: "blocking_work_lane",
    delivery_preemptions: ["blocking_work_lane"],
  });
});

test("pending selection rejects a Todo absent from the current eligible set", () => {
  assert.deepEqual(qualifyActionSelection({
    schema_version: ACTION_SELECTION_QUALIFICATION_REQUEST_SCHEMA_VERSION,
    requested_todo_id: "todo_missing001",
    candidate: null,
    should_run: true,
    normal_delivery_allowed: true,
    delivery_preemptions: [],
  }), {
    schema_version: "action_selection_qualification_v0",
    state: "rejected",
    requested_todo_id: "todo_missing001",
    reason: "candidate_not_currently_eligible",
  });
});

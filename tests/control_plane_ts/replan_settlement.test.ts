import assert from "node:assert/strict";
import test from "node:test";

import {
  projectReplanSettlementContract,
  REPLAN_SETTLEMENT_REQUEST_SCHEMA,
} from "../../loopx/control_plane/work_items/replan_settlement.ts";

function request(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: REPLAN_SETTLEMENT_REQUEST_SCHEMA,
    selected_todo_id: null,
    semantic_replan_obligation_id: "replan-0000000000000001",
    ...overrides,
  };
}

test("Todo-bound replan keeps semantic obligation outside settlement identity", () => {
  assert.deepEqual(
    projectReplanSettlementContract(request({
      selected_todo_id: "todo_current001",
    })),
    {
      schema_version: "replan_settlement_contract_v0",
      single_binding_required: true,
      settlement_binding: {
        kind: "todo",
        id: "todo_current001",
        cli_argument: "--todo-id",
      },
      semantic_obligation: {
        kind: "autonomous_replan",
        id: "replan-0000000000000001",
        settlement_bound: false,
        discharge: "todo_bound_writeback",
      },
    },
  );
});

test("Todo-less replan binds the semantic obligation directly", () => {
  const contract = projectReplanSettlementContract(request());
  assert.deepEqual(contract.settlement_binding, {
    kind: "autonomous_replan",
    id: "replan-0000000000000001",
    cli_argument: "--replan-obligation-id",
  });
  assert.deepEqual(contract.semantic_obligation, {
    kind: "autonomous_replan",
    id: "replan-0000000000000001",
    settlement_bound: true,
    discharge: "direct_settlement",
  });
});

test("typed projection rejects a missing semantic obligation", () => {
  assert.throws(
    () => projectReplanSettlementContract(
      request({
        semantic_replan_obligation_id: null,
      }),
    ),
    /semantic_replan_obligation_id must be a non-empty string/,
  );
});

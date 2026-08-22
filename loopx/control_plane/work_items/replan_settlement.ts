import type { JsonObject } from "../effect_program.ts";
import {
  optionalNonEmptyString,
  requireJsonObject,
  requireNonEmptyString,
} from "../runtime_decode.ts";

export const REPLAN_SETTLEMENT_REQUEST_SCHEMA =
  "loopx_replan_settlement_request_v0";
export const REPLAN_SETTLEMENT_CONTRACT_SCHEMA =
  "replan_settlement_contract_v0";

export function projectReplanSettlementContract(value: unknown): JsonObject {
  const request = requireJsonObject(value, "work_item.replan_settlement params");
  if (request.schema_version !== REPLAN_SETTLEMENT_REQUEST_SCHEMA) {
    throw new Error("Replan settlement request schema mismatch");
  }
  const selectedTodoId = optionalNonEmptyString(
    request.selected_todo_id,
    "selected_todo_id",
  );
  const semanticObligationId = requireNonEmptyString(
    request.semantic_replan_obligation_id,
    "semantic_replan_obligation_id",
  );
  const semanticObligationSettlementBound = selectedTodoId === null;
  const settlementBindingKind = semanticObligationSettlementBound
    ? "autonomous_replan"
    : "todo";
  const settlementBindingId = selectedTodoId ?? semanticObligationId;

  return {
    schema_version: REPLAN_SETTLEMENT_CONTRACT_SCHEMA,
    single_binding_required: true,
    settlement_binding: {
      kind: settlementBindingKind,
      id: settlementBindingId,
      cli_argument: semanticObligationSettlementBound
        ? "--replan-obligation-id"
        : "--todo-id",
    },
    semantic_obligation: {
      kind: "autonomous_replan",
      id: semanticObligationId,
      settlement_bound: semanticObligationSettlementBound,
      discharge: semanticObligationSettlementBound
        ? "direct_settlement"
        : "todo_bound_writeback",
    },
  };
}

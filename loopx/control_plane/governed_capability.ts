import type { JsonObject } from "./effect_program.ts";

export const EXTERNAL_EFFECT_RECEIPT_SCHEMA_VERSION =
  "loopx_external_effect_receipt_v0";

const RESULT_FIELDS = new Set([
  "schema_version",
  "invocation_id",
  "status",
  "observations",
  "domain_state_mutations",
  "domain_transition_receipts",
  "transition_proposals",
  "effect_receipt",
  "follow_up",
]);

const EFFECT_RECEIPT_FIELDS = new Set([
  "schema_version",
  "invocation_id",
  "idempotency_key",
  "status",
  "external_ref",
  "evidence_digest",
]);

function requiredObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return { ...(value as JsonObject) };
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function boundedArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value) || value.length > 64) {
    throw new Error(`${label} must be an array with at most 64 items`);
  }
  return [...value];
}

function requireExactFields(
  value: JsonObject,
  expected: ReadonlySet<string>,
  label: string,
): void {
  const actual = Object.keys(value);
  if (
    actual.length !== expected.size ||
    actual.some((field) => !expected.has(field))
  ) {
    throw new Error(`${label} fields are invalid`);
  }
}

function externalEffectReceipt(
  value: unknown,
  invocationId: string,
  effectId: string,
): JsonObject {
  const receipt = requiredObject(value, "external capability effect_receipt");
  requireExactFields(
    receipt,
    EFFECT_RECEIPT_FIELDS,
    "external capability effect_receipt",
  );
  if (receipt.schema_version !== EXTERNAL_EFFECT_RECEIPT_SCHEMA_VERSION) {
    throw new Error("external capability effect_receipt schema is invalid");
  }
  if (receipt.invocation_id !== invocationId) {
    throw new Error("external capability effect_receipt invocation_id is invalid");
  }
  if (receipt.idempotency_key !== effectId) {
    throw new Error(
      "external capability effect_receipt idempotency_key is invalid",
    );
  }
  if (receipt.status !== "committed" && receipt.status !== "no_change") {
    throw new Error("external capability effect_receipt status is invalid");
  }
  requiredString(
    receipt.external_ref,
    "external capability effect_receipt external_ref",
  );
  requiredString(
    receipt.evidence_digest,
    "external capability effect_receipt evidence_digest",
  );
  return receipt;
}

export function validateGovernedCapabilityAdmission(input: {
  admission: unknown;
  todo_id: string;
  todo_contract: unknown;
}): JsonObject {
  const admission = requiredObject(
    input.admission,
    "governed capability admission",
  );
  const selectedTodo = requiredObject(
    admission.selected_todo,
    "governed capability selected_todo",
  );
  if (selectedTodo.todo_id !== input.todo_id) {
    throw new Error(
      "governed capability selected_todo does not match the settlement Todo",
    );
  }
  if (selectedTodo.role !== "agent" || selectedTodo.status !== "open") {
    throw new Error(
      "governed capability selected_todo must be an open agent Todo",
    );
  }
  const todoContract = requiredObject(
    input.todo_contract,
    "governed capability todo_contract",
  );
  requireExactFields(
    todoContract,
    new Set(["action_kinds", "target_key_prefixes"]),
    "governed capability todo_contract",
  );
  const actionKinds = boundedArray(
    todoContract.action_kinds,
    "governed capability todo_contract action_kinds",
  );
  const targetKeyPrefixes = boundedArray(
    todoContract.target_key_prefixes,
    "governed capability todo_contract target_key_prefixes",
  );
  if (
    actionKinds.length === 0 ||
    actionKinds.some((value) => typeof value !== "string") ||
    !actionKinds.includes(selectedTodo.action_kind)
  ) {
    throw new Error(
      "governed capability operation is not authorized by selected_todo action_kind",
    );
  }
  const targetKey = requiredString(
    selectedTodo.target_key,
    "governed capability selected_todo target_key",
  );
  if (
    targetKeyPrefixes.length === 0 ||
    targetKeyPrefixes.some((value) => typeof value !== "string") ||
    !targetKeyPrefixes.some((prefix) => targetKey.startsWith(prefix as string))
  ) {
    throw new Error(
      "governed capability operation is not authorized by selected_todo target_key",
    );
  }
  return selectedTodo;
}

export function validateGovernedCapabilityResult(input: {
  value: unknown;
  invocation_id: string;
  effect_id: string;
  result_schema: string;
  effect_class: string;
}): { result: JsonObject; journal_status: "running" | "ready_to_settle" } {
  if (input.effect_class !== "external_write") {
    throw new Error("governed capability execution requires external_write");
  }
  const result = requiredObject(input.value, "external capability result");
  requireExactFields(result, RESULT_FIELDS, "external capability result");
  if (result.schema_version !== input.result_schema) {
    throw new Error("external capability result schema_version is invalid");
  }
  if (result.invocation_id !== input.invocation_id) {
    throw new Error("external capability result invocation_id is invalid");
  }
  if (
    result.status !== "running" &&
    result.status !== "succeeded" &&
    result.status !== "no_change"
  ) {
    throw new Error("external capability result status is invalid");
  }
  for (const field of [
    "observations",
    "domain_state_mutations",
    "domain_transition_receipts",
    "transition_proposals",
  ]) {
    result[field] = boundedArray(result[field], `external capability result ${field}`);
  }
  result.follow_up = requiredObject(
    result.follow_up,
    "external capability result follow_up",
  );
  if (result.status === "running") {
    if (result.effect_receipt !== null) {
      throw new Error(
        "running external capability cannot claim an effect receipt",
      );
    }
    for (const field of [
      "domain_state_mutations",
      "domain_transition_receipts",
      "transition_proposals",
    ]) {
      if ((result[field] as unknown[]).length > 0) {
        throw new Error(
          `running external capability must leave ${field} empty`,
        );
      }
    }
    return { result, journal_status: "running" };
  }
  const receipt = externalEffectReceipt(
    result.effect_receipt,
    input.invocation_id,
    input.effect_id,
  );
  if (result.status === "no_change") {
    if (receipt.status !== "no_change") {
      throw new Error(
        "no-change external capability requires a no-change effect receipt",
      );
    }
    for (const field of [
      "domain_state_mutations",
      "domain_transition_receipts",
      "transition_proposals",
    ]) {
      if ((result[field] as unknown[]).length > 0) {
        throw new Error(
          `no-change external capability must leave ${field} empty`,
        );
      }
    }
  } else if (receipt.status !== "committed") {
    throw new Error(
      "succeeded external capability requires a committed effect receipt",
    );
  }
  result.effect_receipt = receipt;
  return { result, journal_status: "ready_to_settle" };
}

export function validateGovernedCapabilitySettlementCallback(input: {
  payload: unknown;
  effect_id: string;
  effect_receipt_digest: string;
  require_receipt_digest: boolean;
}): JsonObject {
  const payload = requiredObject(
    input.payload,
    "governed capability settlement callback",
  );
  const identity = requiredObject(
    payload.settlement_identity,
    "governed capability settlement identity",
  );
  if (identity.effect_id !== input.effect_id) {
    return {
      ok: false,
      appended: false,
      reason: "settlement identity mismatch",
    };
  }
  if (
    input.require_receipt_digest &&
    payload.effect_receipt_digest !== input.effect_receipt_digest
  ) {
    return {
      ok: false,
      appended: false,
      reason: "effect receipt was not written back",
    };
  }
  return payload;
}

export function governedCapabilitySettlementStatus(
  failure: unknown,
): "settlement_failed" | "committed" {
  return failure === null ? "committed" : "settlement_failed";
}

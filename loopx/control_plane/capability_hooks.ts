import type { JsonObject } from "./effect_program.ts";
import {
  requireInteger,
  requireJsonObject as requiredObject,
  requireNonEmptyString as requiredString,
  requireStringArray,
} from "./runtime_decode.ts";
import { projectRepositoryDeliveryGate } from "./work_items/repository_delivery.ts";

export const CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION =
  "loopx_capability_hook_registration_v0";
export const INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION =
  "loopx_interaction_projection_hook_result_v0";

const REGISTRATION_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "projection_slots",
  "budget",
  "failure_policy",
  "requested_read_scope",
  "requested_write_scope",
]);
const BUDGET_FIELDS = new Set([
  "max_invocations_per_dispatch",
  "max_result_bytes",
]);
const RESULT_FIELDS = new Set([
  "schema_version",
  "hook_id",
  "capability_id",
  "phase",
  "status",
  "projection_slot",
  "payload",
]);
const TOKEN_RE = /^[a-z][a-z0-9_.:-]{2,95}$/;

function requireExactFields(
  value: JsonObject,
  expected: ReadonlySet<string>,
  label: string,
): void {
  const fields = Object.keys(value);
  if (
    fields.length !== expected.size ||
    fields.some((field) => !expected.has(field))
  ) {
    throw new Error(`${label} fields are invalid`);
  }
}

function boundedTokens(
  value: unknown,
  label: string,
  limit: number,
): string[] {
  const tokens = requireStringArray(value, label);
  if (
    tokens.length > limit ||
    new Set(tokens).size !== tokens.length ||
    tokens.some((token) => !TOKEN_RE.test(token))
  ) {
    throw new Error(`${label} contains invalid tokens`);
  }
  return tokens;
}

export function validateInteractionProjectionHookRegistration(
  value: unknown,
): JsonObject & {
  hook_id: string;
  capability_id: string;
  projection_slots: string[];
  max_result_bytes: number;
} {
  const registration = requiredObject(value, "capability hook registration");
  requireExactFields(
    registration,
    REGISTRATION_FIELDS,
    "capability hook registration",
  );
  if (
    registration.schema_version !==
      CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION ||
    registration.phase !== "interaction_projection" ||
    registration.failure_policy !== "isolate"
  ) {
    throw new Error("capability hook registration contract is invalid");
  }
  const hookId = requiredString(registration.hook_id, "capability hook hook_id");
  const capabilityId = requiredString(
    registration.capability_id,
    "capability hook capability_id",
  );
  if (!TOKEN_RE.test(hookId) || !TOKEN_RE.test(capabilityId)) {
    throw new Error("capability hook identity is invalid");
  }
  const projectionSlots = boundedTokens(
    registration.projection_slots,
    "capability hook projection_slots",
    8,
  );
  if (projectionSlots.length === 0) {
    throw new Error("capability hook projection_slots cannot be empty");
  }
  boundedTokens(
    registration.requested_read_scope,
    "capability hook requested_read_scope",
    16,
  );
  const writeScope = boundedTokens(
    registration.requested_write_scope,
    "capability hook requested_write_scope",
    16,
  );
  if (writeScope.length > 0) {
    throw new Error("interaction projection hooks cannot request write scope");
  }
  const budget = requiredObject(registration.budget, "capability hook budget");
  requireExactFields(budget, BUDGET_FIELDS, "capability hook budget");
  const maxInvocations = requireInteger(
    budget.max_invocations_per_dispatch,
    "capability hook max_invocations_per_dispatch",
  );
  const maxResultBytes = requireInteger(
    budget.max_result_bytes,
    "capability hook max_result_bytes",
  );
  if (maxInvocations !== 1 || maxResultBytes < 1024 || maxResultBytes > 65_536) {
    throw new Error("capability hook budget is outside the admitted envelope");
  }
  return {
    ...registration,
    hook_id: hookId,
    capability_id: capabilityId,
    projection_slots: projectionSlots,
    max_result_bytes: maxResultBytes,
  };
}

export function validateInteractionProjectionHookInvocation(input: {
  registration: unknown;
  result: unknown;
}): JsonObject {
  const registration = validateInteractionProjectionHookRegistration(
    input.registration,
  );
  const result = requiredObject(input.result, "capability hook result");
  requireExactFields(result, RESULT_FIELDS, "capability hook result");
  if (
    result.schema_version !== INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION ||
    result.hook_id !== registration.hook_id ||
    result.capability_id !== registration.capability_id ||
    result.phase !== "interaction_projection"
  ) {
    throw new Error("capability hook result identity is invalid");
  }
  if (
    new TextEncoder().encode(JSON.stringify(result)).byteLength >
      registration.max_result_bytes
  ) {
    throw new Error("capability hook result exceeds its budget");
  }
  if (result.status === "not_applicable") {
    if (result.projection_slot !== null || result.payload !== null) {
      throw new Error("not-applicable capability hook result must be empty");
    }
    return {
      schema_version: INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
      hook_id: registration.hook_id,
      capability_id: registration.capability_id,
      phase: "interaction_projection",
      status: "not_applicable",
      projection_slot: null,
      projection: null,
    };
  }
  if (result.status !== "candidate") {
    throw new Error("capability hook result status is invalid");
  }
  const slot = requiredString(
    result.projection_slot,
    "capability hook projection_slot",
  );
  if (!registration.projection_slots.includes(slot)) {
    throw new Error("capability hook projection_slot is not registered");
  }
  let projection: JsonObject | null;
  switch (slot) {
    case "repository_delivery":
      projection = projectRepositoryDeliveryGate(result.payload);
      break;
    default:
      throw new Error("capability hook projection_slot is unsupported");
  }
  return {
    schema_version: INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    hook_id: registration.hook_id,
    capability_id: registration.capability_id,
    phase: "interaction_projection",
    status: projection ? "projected" : "not_applicable",
    projection_slot: projection ? slot : null,
    projection,
  };
}

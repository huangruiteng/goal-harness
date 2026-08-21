import type { JsonObject } from "../effect_program.ts";

export const DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION =
  "delivery_workspace_causality_v0";
export const DELIVERY_WORKSPACE_CAUSALITY_REQUEST_SCHEMA =
  "loopx_delivery_workspace_causality_request_v0";
export const DELIVERY_WORKSPACE_CAUSALITY_RESULT_SCHEMA =
  "loopx_delivery_workspace_causality_result_v0";

export const DELIVERY_WORKSPACE_REQUIREMENTS = [
  "required",
  "not_required",
  "unknown",
] as const;

export type DeliveryWorkspaceRequirement =
  (typeof DELIVERY_WORKSPACE_REQUIREMENTS)[number];

export interface DeliveryWorkspaceCausality extends JsonObject {
  schema_version: typeof DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION;
  todo_id: string;
  requirement: DeliveryWorkspaceRequirement;
  source: string;
  reason: string;
}

type DeliveryWorkspaceCausalityOperation =
  | "classify"
  | "normalize"
  | "event_fields"
  | "from_event";

function requiredObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function optionalObject(value: unknown, label: string): JsonObject | null {
  if (value === null || value === undefined) return null;
  return requiredObject(value, label);
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`${label} must be a string`);
  return value;
}

function optionalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return requiredString(value, label);
}

function stringArray(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} must be an array of strings`);
  }
  return value;
}

function operation(value: unknown): DeliveryWorkspaceCausalityOperation {
  if (
    value === "classify" || value === "normalize" ||
    value === "event_fields" || value === "from_event"
  ) return value;
  throw new Error("delivery workspace causality operation is unsupported");
}

function requestObject(value: unknown): JsonObject {
  const request = requiredObject(value, "delivery workspace causality request");
  if (request.schema_version !== DELIVERY_WORKSPACE_CAUSALITY_REQUEST_SCHEMA) {
    throw new Error("delivery workspace causality request schema mismatch");
  }
  return request;
}

function result(values: JsonObject): JsonObject {
  return {
    schema_version: DELIVERY_WORKSPACE_CAUSALITY_RESULT_SCHEMA,
    ...values,
  };
}

export function classifyDeliveryWorkspaceCausality(
  value: unknown,
): DeliveryWorkspaceCausality | null {
  // Missing write metadata stays unknown. Only an explicit non-delivery
  // contract with no repository-write evidence can omit workspace validation.
  const contract = requiredObject(value, "normalized_todo_contract");
  const todoId = optionalString(contract.todo_id, "todo_id");
  if (!todoId) return null;
  const taskRepository = optionalString(
    contract.task_repository,
    "task_repository",
  );
  const writeScopes = stringArray(
    contract.required_write_scopes,
    "required_write_scopes",
  );
  const capabilities = stringArray(
    contract.required_capabilities,
    "required_capabilities",
  );
  const continuationPolicy = optionalString(
    contract.continuation_policy,
    "continuation_policy",
  );
  const source = requiredString(contract.source, "source");

  let requirement: DeliveryWorkspaceRequirement;
  let reason: string;
  if (
    taskRepository || writeScopes.length > 0 ||
    capabilities.includes("filesystem_write")
  ) {
    requirement = "required";
    reason = "declared_repository_or_write_contract";
  } else if (continuationPolicy === "same_agent_non_delivery") {
    requirement = "not_required";
    reason = "explicit_non_delivery_without_repository_writes";
  } else {
    requirement = "unknown";
    reason = "todo_write_contract_not_explicit";
  }
  return {
    schema_version: DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION,
    todo_id: todoId,
    requirement,
    source,
    reason,
  };
}

export function normalizeDeliveryWorkspaceCausality(
  value: unknown,
  expectedTodoId: string | null,
): DeliveryWorkspaceCausality | null {
  const candidate = optionalObject(value, "causality");
  if (
    candidate === null ||
    candidate.schema_version !== DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION
  ) return null;
  const todoId = optionalString(candidate.todo_id, "causality.todo_id");
  if (!todoId || (expectedTodoId && todoId !== expectedTodoId)) return null;
  const rawRequirement = optionalString(
    candidate.requirement,
    "causality.requirement",
  );
  const requirement = DELIVERY_WORKSPACE_REQUIREMENTS.find(
    (item) => item === rawRequirement,
  );
  if (!requirement) return null;
  const source = optionalString(candidate.source, "causality.source")?.trim();
  const reason = optionalString(candidate.reason, "causality.reason")?.trim();
  if (!source || !reason) return null;
  return {
    schema_version: DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION,
    todo_id: todoId,
    requirement,
    source,
    reason,
  };
}

export function deliveryWorkspaceCausalityEventFields(
  value: unknown,
): JsonObject {
  const causality = normalizeDeliveryWorkspaceCausality(value, null);
  if (!causality) return {};
  return {
    delivery_workspace_causality_schema_version: causality.schema_version,
    delivery_workspace_causality_todo_id: causality.todo_id,
    delivery_workspace_requirement: causality.requirement,
    delivery_workspace_causality_source: causality.source,
    delivery_workspace_causality_reason: causality.reason,
  };
}

export function evaluateDeliveryWorkspaceCausality(value: unknown): JsonObject {
  const request = requestObject(value);
  const selectedOperation = operation(request.operation);
  const expectedTodoId = optionalString(
    request.expected_todo_id,
    "expected_todo_id",
  );
  if (selectedOperation === "classify") {
    return result({
      causality: classifyDeliveryWorkspaceCausality(
        request.normalized_todo_contract,
      ),
    });
  }
  if (selectedOperation === "normalize") {
    return result({
      causality: normalizeDeliveryWorkspaceCausality(
        request.causality,
        expectedTodoId,
      ),
    });
  }
  if (selectedOperation === "event_fields") {
    return result({
      fields: deliveryWorkspaceCausalityEventFields(request.causality),
    });
  }
  const nested = normalizeDeliveryWorkspaceCausality(
    request.nested_causality,
    expectedTodoId,
  );
  return result({
    causality: (nested ?? normalizeDeliveryWorkspaceCausality(
      request.flat_causality,
      expectedTodoId,
    )),
  });
}

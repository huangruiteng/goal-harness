import type { JsonObject } from "../effect_program.ts";
import {
  decodeOptionalMaterialDeliveryOutcome,
  type MaterialDeliveryOutcome,
} from "../work_items/delivery_outcome.ts";

export const DELIVERY_CONTINUITY_REQUEST_SCHEMA =
  "loopx_delivery_continuity_request_v0";
export const DELIVERY_CONTINUITY_RESULT_SCHEMA =
  "loopx_delivery_continuity_result_v0";
export const DELIVERY_BOUNDARY_REQUEST_SCHEMA =
  "loopx_delivery_boundary_request_v0";
export const DELIVERY_BOUNDARY_RESULT_SCHEMA =
  "loopx_delivery_boundary_result_v0";

export const DELIVERY_BOUNDARIES = [
  "in_flight_continuation",
  "semantic_closeout",
] as const;

export const DELIVERY_CONTINUITY_PREEMPTIONS = [
  "heartbeat_receipt",
  "blocking_work_lane",
  "autonomous_replan",
  "control_repair",
  "delivery_not_allowed",
] as const;

export type DeliveryBoundary = (typeof DELIVERY_BOUNDARIES)[number];
export type DeliveryContinuityPreemption =
  (typeof DELIVERY_CONTINUITY_PREEMPTIONS)[number];

type TodoStatus = "open" | "done" | "blocked" | "deferred";

export interface DeliveryContinuityTodo {
  todo_id: string;
  status: TodoStatus;
  task_class: string;
  claimed_by: string | null;
  actionable: boolean;
  capability_ready: boolean;
}

export interface DeliveryContinuityRequest {
  schema_version: typeof DELIVERY_CONTINUITY_REQUEST_SCHEMA;
  agent_id: string;
  previous_todo_id: string | null;
  previous_delivery_outcome: MaterialDeliveryOutcome | null;
  current_todo: DeliveryContinuityTodo | null;
  preemptions: readonly DeliveryContinuityPreemption[];
}

export type DeliveryContinuityDecision =
  | "resume_in_flight"
  | "release_for_reselection"
  | "preempt";

export type DeliveryContinuityReason =
  | DeliveryContinuityPreemption
  | "no_previous_todo"
  | "previous_delivery_not_progress"
  | "current_todo_missing"
  | "todo_identity_changed"
  | "todo_not_open"
  | "todo_not_advancement"
  | "todo_not_actionable"
  | "todo_capability_blocked"
  | "todo_claimed_by_other_agent"
  | "same_open_todo_after_progress";

export type DeliveryContinuityResult = JsonObject & {
  schema_version: typeof DELIVERY_CONTINUITY_RESULT_SCHEMA;
  decision: DeliveryContinuityDecision;
  reason: DeliveryContinuityReason;
  todo_id: string | null;
  delivery_boundary: DeliveryBoundary;
};

interface DeliveryBoundaryRequest {
  schema_version: typeof DELIVERY_BOUNDARY_REQUEST_SCHEMA;
  agent_id: string;
  current_todo: DeliveryContinuityTodo | null;
  preemptions: readonly DeliveryContinuityPreemption[];
}

export type DeliveryBoundaryReason =
  | DeliveryContinuityPreemption
  | "no_selected_todo"
  | "todo_not_open"
  | "todo_not_advancement"
  | "todo_not_actionable"
  | "todo_capability_blocked"
  | "todo_claimed_by_other_agent"
  | "open_advancement_todo";

export type DeliveryBoundaryResult = JsonObject & {
  schema_version: typeof DELIVERY_BOUNDARY_RESULT_SCHEMA;
  delivery_boundary: DeliveryBoundary;
  reason: DeliveryBoundaryReason;
  todo_id: string | null;
};

function requiredObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value.trim();
}

function optionalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  return requiredString(value, label);
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function todoStatus(value: unknown): TodoStatus {
  if (
    value === "open" || value === "done" || value === "blocked" ||
    value === "deferred"
  ) {
    return value;
  }
  throw new Error("current_todo.status is unsupported");
}

function preemptions(value: unknown): DeliveryContinuityPreemption[] {
  if (!Array.isArray(value)) {
    throw new Error("preemptions must be an array");
  }
  const result: DeliveryContinuityPreemption[] = [];
  for (const item of value) {
    if (
      typeof item !== "string" ||
      !DELIVERY_CONTINUITY_PREEMPTIONS.some((candidate) => candidate === item)
    ) {
      throw new Error("preemptions contains an unsupported reason");
    }
    const reason = item as DeliveryContinuityPreemption;
    if (!result.includes(reason)) result.push(reason);
  }
  return result;
}

function currentTodo(value: unknown): DeliveryContinuityTodo | null {
  if (value === null || value === undefined) return null;
  const todo = requiredObject(value, "current_todo");
  return {
    todo_id: requiredString(todo.todo_id, "current_todo.todo_id"),
    status: todoStatus(todo.status),
    task_class: requiredString(todo.task_class, "current_todo.task_class"),
    claimed_by: optionalString(todo.claimed_by, "current_todo.claimed_by"),
    actionable: requiredBoolean(todo.actionable, "current_todo.actionable"),
    capability_ready: requiredBoolean(
      todo.capability_ready,
      "current_todo.capability_ready",
    ),
  };
}

export function decodeDeliveryContinuityRequest(
  value: unknown,
): DeliveryContinuityRequest {
  const request = requiredObject(value, "turn.delivery_continuity params");
  if (request.schema_version !== DELIVERY_CONTINUITY_REQUEST_SCHEMA) {
    throw new Error("Delivery continuity request schema mismatch");
  }
  return {
    schema_version: DELIVERY_CONTINUITY_REQUEST_SCHEMA,
    agent_id: requiredString(request.agent_id, "agent_id"),
    previous_todo_id: optionalString(
      request.previous_todo_id,
      "previous_todo_id",
    ),
    previous_delivery_outcome: decodeOptionalMaterialDeliveryOutcome(
      request.previous_delivery_outcome,
      "previous_delivery_outcome",
    ),
    current_todo: currentTodo(request.current_todo),
    preemptions: preemptions(request.preemptions),
  };
}

function decodeDeliveryBoundaryRequest(value: unknown): DeliveryBoundaryRequest {
  const request = requiredObject(value, "turn.delivery_boundary params");
  if (request.schema_version !== DELIVERY_BOUNDARY_REQUEST_SCHEMA) {
    throw new Error("Delivery boundary request schema mismatch");
  }
  return {
    schema_version: DELIVERY_BOUNDARY_REQUEST_SCHEMA,
    agent_id: requiredString(request.agent_id, "agent_id"),
    current_todo: currentTodo(request.current_todo),
    preemptions: preemptions(request.preemptions),
  };
}

function result(
  decision: DeliveryContinuityDecision,
  reason: DeliveryContinuityReason,
  todoId: string | null,
): DeliveryContinuityResult {
  return {
    schema_version: DELIVERY_CONTINUITY_RESULT_SCHEMA,
    decision,
    reason,
    todo_id: todoId,
    delivery_boundary: decision === "resume_in_flight"
      ? "in_flight_continuation"
      : "semantic_closeout",
  };
}

export function evaluateDeliveryContinuity(
  value: unknown,
): DeliveryContinuityResult {
  const request = decodeDeliveryContinuityRequest(value);
  const todoId = request.previous_todo_id;
  const preemption = request.preemptions[0];
  if (preemption !== undefined) {
    return result("preempt", preemption, todoId);
  }
  if (todoId === null) {
    return result("release_for_reselection", "no_previous_todo", null);
  }
  if (request.previous_delivery_outcome !== "outcome_progress") {
    return result(
      "release_for_reselection",
      "previous_delivery_not_progress",
      todoId,
    );
  }
  const todo = request.current_todo;
  if (todo === null) {
    return result("release_for_reselection", "current_todo_missing", todoId);
  }
  if (todo.todo_id !== todoId) {
    return result("release_for_reselection", "todo_identity_changed", todoId);
  }
  if (todo.status !== "open") {
    return result("release_for_reselection", "todo_not_open", todoId);
  }
  if (todo.task_class !== "advancement_task") {
    return result("release_for_reselection", "todo_not_advancement", todoId);
  }
  if (!todo.actionable) {
    return result("release_for_reselection", "todo_not_actionable", todoId);
  }
  if (!todo.capability_ready) {
    return result("release_for_reselection", "todo_capability_blocked", todoId);
  }
  if (todo.claimed_by !== null && todo.claimed_by !== request.agent_id) {
    return result(
      "release_for_reselection",
      "todo_claimed_by_other_agent",
      todoId,
    );
  }
  return result(
    "resume_in_flight",
    "same_open_todo_after_progress",
    todoId,
  );
}

function boundaryResult(
  deliveryBoundary: DeliveryBoundary,
  reason: DeliveryBoundaryReason,
  todoId: string | null,
): DeliveryBoundaryResult {
  return {
    schema_version: DELIVERY_BOUNDARY_RESULT_SCHEMA,
    delivery_boundary: deliveryBoundary,
    reason,
    todo_id: todoId,
  };
}

export function evaluateDeliveryBoundary(value: unknown): DeliveryBoundaryResult {
  const request = decodeDeliveryBoundaryRequest(value);
  const todo = request.current_todo;
  const todoId = todo?.todo_id ?? null;
  const preemption = request.preemptions[0];
  if (preemption !== undefined) {
    return boundaryResult("semantic_closeout", preemption, todoId);
  }
  if (todo === null) {
    return boundaryResult("semantic_closeout", "no_selected_todo", null);
  }
  if (todo.status !== "open") {
    return boundaryResult("semantic_closeout", "todo_not_open", todoId);
  }
  if (todo.task_class !== "advancement_task") {
    return boundaryResult("semantic_closeout", "todo_not_advancement", todoId);
  }
  if (!todo.actionable) {
    return boundaryResult("semantic_closeout", "todo_not_actionable", todoId);
  }
  if (!todo.capability_ready) {
    return boundaryResult("semantic_closeout", "todo_capability_blocked", todoId);
  }
  if (todo.claimed_by !== null && todo.claimed_by !== request.agent_id) {
    return boundaryResult(
      "semantic_closeout",
      "todo_claimed_by_other_agent",
      todoId,
    );
  }
  return boundaryResult(
    "in_flight_continuation",
    "open_advancement_todo",
    todoId,
  );
}

import type { JsonObject } from "../effect_program.ts";

export const TODO_COMPLETION_FENCE_REQUEST_SCHEMA =
  "loopx_todo_completion_fence_request_v0";
export const TODO_COMPLETION_FENCE_RESULT_SCHEMA =
  "loopx_todo_completion_fence_result_v0";

const TODO_STATUSES = ["open", "done", "blocked", "deferred"] as const;
const COMPLETION_CONTINUATIONS = [
  "active_goal",
  "successor",
  "no_followup",
] as const;
const TODO_ID_PATTERN = /^todo_[a-z0-9_-]{3,64}$/;

export type TodoStatus = (typeof TODO_STATUSES)[number];
export type TodoCompletionContinuation =
  (typeof COMPLETION_CONTINUATIONS)[number];
export type TodoCompletionProjectionSource = "materialized" | "event_log";

export interface TodoCompletionFenceRequest {
  schema_version: typeof TODO_COMPLETION_FENCE_REQUEST_SCHEMA;
  projection_source: TodoCompletionProjectionSource;
  todo: {
    status: TodoStatus;
    no_followup: boolean | string | null;
    completion_continuation: string | null;
    completion_turn_key: string | null;
    successor_todo_ids: readonly string[];
  };
  requested_no_followup: boolean;
  requested_completion_turn_key: string | null;
}

export type TodoCompletionFenceContinueReason =
  | "not_terminal"
  | "same_turn_terminal_upgrade"
  | "untyped_completion_repair";

export type TodoCompletionFenceResult =
  | (JsonObject & {
      schema_version: typeof TODO_COMPLETION_FENCE_RESULT_SCHEMA;
      outcome: "continue";
      reason: TodoCompletionFenceContinueReason;
      status: TodoStatus;
      terminal_before_request: boolean;
      completion_continuation: TodoCompletionContinuation | null;
    })
  | (JsonObject & {
      schema_version: typeof TODO_COMPLETION_FENCE_RESULT_SCHEMA;
      outcome: "replay";
      reason: "already_terminal";
      status: "done" | "deferred";
      terminal_before_request: true;
      completion_continuation: TodoCompletionContinuation | null;
    });

function requiredObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function optionalOpaqueString(value: unknown, label: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string or null`);
  }
  return value;
}

function todoStatus(value: unknown): TodoStatus {
  if (typeof value !== "string") {
    throw new Error("todo.status must be a supported string");
  }
  const normalized = value.trim().toLowerCase();
  if (!TODO_STATUSES.some((status) => status === normalized)) {
    throw new Error("todo.status is unsupported");
  }
  return normalized as TodoStatus;
}

function projectionSource(value: unknown): TodoCompletionProjectionSource {
  if (value === "materialized" || value === "event_log") return value;
  throw new Error("projection_source is unsupported");
}

function normalizeNoFollowup(value: unknown): boolean | null {
  if (typeof value === "boolean") return value;
  if (value === null || value === undefined) return null;
  if (typeof value !== "string") {
    throw new Error("todo.no_followup must be a boolean, string, or null");
  }
  const candidate = value.trim().toLowerCase();
  if (["1", "true", "yes", "y", "no_followup", "no-followup"].includes(candidate)) {
    return true;
  }
  if (["0", "false", "no", "n"].includes(candidate)) return false;
  return null;
}

function normalizeCompletionContinuation(
  value: unknown,
): TodoCompletionContinuation | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string") {
    throw new Error("todo.completion_continuation must be a string or null");
  }
  const candidate = value.trim().toLowerCase();
  return COMPLETION_CONTINUATIONS.some((item) => item === candidate)
    ? candidate as TodoCompletionContinuation
    : null;
}

function successorTodoIds(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  const values = Array.isArray(value) ? value : [value];
  if (values.some((item) => typeof item !== "string")) {
    throw new Error("todo.successor_todo_ids must contain only strings");
  }
  const result: string[] = [];
  for (const raw of values as string[]) {
    for (const match of raw.matchAll(/\btodo_[A-Za-z0-9_-]+\b/g)) {
      const todoId = match[0].toLowerCase();
      if (TODO_ID_PATTERN.test(todoId) && !result.includes(todoId)) {
        result.push(todoId);
      }
    }
    const todoId = raw.trim().toLowerCase();
    if (TODO_ID_PATTERN.test(todoId) && !result.includes(todoId)) {
      result.push(todoId);
    }
  }
  return result;
}

export function decodeTodoCompletionFenceRequest(
  value: unknown,
): TodoCompletionFenceRequest {
  const request = requiredObject(value, "todo.completion_fence params");
  if (request.schema_version !== TODO_COMPLETION_FENCE_REQUEST_SCHEMA) {
    throw new Error("Todo completion fence request schema mismatch");
  }
  const todo = requiredObject(request.todo, "todo.completion_fence todo");
  return {
    schema_version: TODO_COMPLETION_FENCE_REQUEST_SCHEMA,
    projection_source: projectionSource(request.projection_source),
    todo: {
      status: todoStatus(todo.status),
      no_followup: normalizeNoFollowup(todo.no_followup),
      completion_continuation: optionalOpaqueString(
        todo.completion_continuation,
        "todo.completion_continuation",
      ),
      completion_turn_key: optionalOpaqueString(
        todo.completion_turn_key,
        "todo.completion_turn_key",
      ),
      successor_todo_ids: successorTodoIds(todo.successor_todo_ids),
    },
    requested_no_followup: requiredBoolean(
      request.requested_no_followup,
      "requested_no_followup",
    ),
    requested_completion_turn_key: optionalOpaqueString(
      request.requested_completion_turn_key,
      "requested_completion_turn_key",
    ),
  };
}

export function evaluateTodoCompletionFence(
  value: unknown,
): TodoCompletionFenceResult {
  const request = decodeTodoCompletionFenceRequest(value);
  const status = request.todo.status;
  const continuation = normalizeCompletionContinuation(
    request.todo.completion_continuation,
  );
  const done = status === "done";
  const terminalBeforeRequest = done ||
    (request.projection_source === "event_log" && status === "deferred");

  if (
    done && request.requested_completion_turn_key !== null &&
    request.requested_completion_turn_key !== request.todo.completion_turn_key
  ) {
    throw new Error(
      "todo is already completed under a different completion_turn_key",
    );
  }

  const terminalUpgrade = done && request.requested_no_followup &&
    normalizeNoFollowup(request.todo.no_followup) !== true;
  if (terminalUpgrade) {
    if (request.todo.successor_todo_ids.length > 0) {
      throw new Error(
        "todo terminal closeout cannot replace an existing successor",
      );
    }
    if (continuation === null) {
      throw new Error(
        "completed todo is missing completion_continuation; repair the " +
          "Todo with `loopx todo complete` without --no-follow-up before terminal " +
          "closeout",
      );
    }
    if (continuation !== "active_goal") {
      throw new Error(
        "todo terminal closeout recovery requires " +
          "completion_continuation=active_goal",
      );
    }
    if (
      request.requested_completion_turn_key === null ||
      request.requested_completion_turn_key !== request.todo.completion_turn_key
    ) {
      throw new Error(
        "todo terminal closeout requires the original completion_turn_key",
      );
    }
    return {
      schema_version: TODO_COMPLETION_FENCE_RESULT_SCHEMA,
      outcome: "continue",
      reason: "same_turn_terminal_upgrade",
      status,
      terminal_before_request: true,
      completion_continuation: continuation,
    };
  }

  if (done && continuation === null) {
    return {
      schema_version: TODO_COMPLETION_FENCE_RESULT_SCHEMA,
      outcome: "continue",
      reason: "untyped_completion_repair",
      status,
      terminal_before_request: true,
      completion_continuation: null,
    };
  }

  if (terminalBeforeRequest) {
    return {
      schema_version: TODO_COMPLETION_FENCE_RESULT_SCHEMA,
      outcome: "replay",
      reason: "already_terminal",
      status,
      terminal_before_request: true,
      completion_continuation: continuation,
    };
  }

  return {
    schema_version: TODO_COMPLETION_FENCE_RESULT_SCHEMA,
    outcome: "continue",
    reason: "not_terminal",
    status,
    terminal_before_request: false,
    completion_continuation: continuation,
  };
}

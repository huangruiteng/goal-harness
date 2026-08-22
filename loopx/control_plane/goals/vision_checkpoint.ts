import type { JsonObject } from "../effect_program.ts";
import {
  DELIVERY_BOUNDARIES,
  type DeliveryBoundary,
} from "../turn_driver/delivery_continuity.ts";
import {
  decodeOptionalDeliveryOutcome,
  isMaterialDeliveryOutcome,
  type DeliveryOutcome,
} from "../work_items/delivery_outcome.ts";

export const VISION_CHECKPOINT_REQUEST_SCHEMA =
  "loopx_vision_checkpoint_request_v0";
export const VISION_CHECKPOINT_SCHEMA_VERSION = "vision_checkpoint_v0";

interface VisionCheckpointRequest {
  schema_version: typeof VISION_CHECKPOINT_REQUEST_SCHEMA;
  agent_id: string | null;
  agent_vision: JsonObject | null;
  existing_agent_vision: JsonObject | null;
  vision_unchanged_reason: string | null;
  delivery_outcome: DeliveryOutcome | null;
  active_state_next_action_would_update: boolean;
  delivery_boundary: DeliveryBoundary;
  todo_id: string | null;
  completion_todo_id: string | null;
  autonomous_replan_recorded: boolean;
}

export type VisionCheckpointDecision =
  | "patched"
  | "unchanged_with_reason"
  | "missing_required"
  | "not_required";

interface ExistingVisionContinuityBasis extends JsonObject {
  kind: "existing_vision_unchanged";
  vision_generated_at: string;
}

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

function optionalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be a non-empty string or null`);
  }
  return value.trim();
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}

function existingVisionContinuityBasis(
  vision: JsonObject | null,
): ExistingVisionContinuityBasis | null {
  if (vision === null) return null;
  const generatedAt = vision.generated_at;
  if (typeof generatedAt !== "string" || !generatedAt.trim()) return null;
  return {
    kind: "existing_vision_unchanged",
    vision_generated_at: generatedAt.trim(),
  };
}

function deliveryBoundary(value: unknown): DeliveryBoundary {
  if (value === null || value === undefined || value === "") {
    return "semantic_closeout";
  }
  if (DELIVERY_BOUNDARIES.some((candidate) => candidate === value)) {
    return value as DeliveryBoundary;
  }
  throw new Error("delivery_boundary is unsupported");
}

export function decodeVisionCheckpointRequest(
  value: unknown,
): VisionCheckpointRequest {
  const request = requiredObject(value, "goal.vision_checkpoint params");
  if (request.schema_version !== VISION_CHECKPOINT_REQUEST_SCHEMA) {
    throw new Error("Vision checkpoint request schema mismatch");
  }
  return {
    schema_version: VISION_CHECKPOINT_REQUEST_SCHEMA,
    agent_id: optionalString(request.agent_id, "agent_id"),
    agent_vision: optionalObject(request.agent_vision, "agent_vision"),
    existing_agent_vision: optionalObject(
      request.existing_agent_vision,
      "existing_agent_vision",
    ),
    vision_unchanged_reason: optionalString(
      request.vision_unchanged_reason,
      "vision_unchanged_reason",
    ),
    delivery_outcome: decodeOptionalDeliveryOutcome(request.delivery_outcome),
    active_state_next_action_would_update: requiredBoolean(
      request.active_state_next_action_would_update,
      "active_state_next_action_would_update",
    ),
    delivery_boundary: deliveryBoundary(request.delivery_boundary),
    todo_id: optionalString(request.todo_id, "todo_id"),
    completion_todo_id: optionalString(
      request.completion_todo_id,
      "completion_todo_id",
    ),
    autonomous_replan_recorded: requiredBoolean(
      request.autonomous_replan_recorded,
      "autonomous_replan_recorded",
    ),
  };
}

function validateInFlightBoundary(request: VisionCheckpointRequest): void {
  if (request.delivery_boundary !== "in_flight_continuation") return;
  if (request.delivery_outcome !== "outcome_progress") {
    throw new Error(
      "in_flight_continuation requires delivery_outcome=outcome_progress",
    );
  }
  if (request.agent_id === null || request.todo_id === null) {
    throw new Error(
      "in_flight_continuation requires an agent-bound Todo settlement",
    );
  }
  if (request.completion_todo_id !== null) {
    throw new Error(
      "in_flight_continuation conflicts with Todo completion closeout",
    );
  }
  if (request.active_state_next_action_would_update) {
    throw new Error(
      "in_flight_continuation conflicts with a durable Next Action update",
    );
  }
  if (request.autonomous_replan_recorded) {
    throw new Error(
      "in_flight_continuation conflicts with autonomous replan writeback",
    );
  }
}

export function buildVisionCheckpoint(value: unknown): JsonObject {
  const request = decodeVisionCheckpointRequest(value);
  validateInFlightBoundary(request);
  const triggers: JsonObject[] = [];
  if (
    isMaterialDeliveryOutcome(request.delivery_outcome) &&
    request.delivery_boundary === "semantic_closeout"
  ) {
    triggers.push({
      kind: "material_delivery_outcome",
      delivery_outcome: request.delivery_outcome,
    });
  } else if (request.delivery_boundary === "in_flight_continuation") {
    triggers.push({
      kind: "in_flight_continuation",
      todo_id: request.todo_id,
    });
  }
  if (request.active_state_next_action_would_update) {
    triggers.push({ kind: "durable_next_action_update" });
  }

  const unchanged = request.vision_unchanged_reason;
  const requiredTriggers = triggers.filter((trigger) =>
    trigger.kind !== "in_flight_continuation"
  );
  const required = requiredTriggers.length > 0 || unchanged !== null;
  let decision: VisionCheckpointDecision;
  let satisfied: boolean;
  if (request.agent_vision !== null) {
    decision = "patched";
    satisfied = true;
  } else if (unchanged !== null && request.existing_agent_vision !== null) {
    decision = "unchanged_with_reason";
    satisfied = true;
  } else if (unchanged !== null || required) {
    decision = "missing_required";
    satisfied = false;
  } else {
    decision = "not_required";
    satisfied = true;
  }

  const checkpoint: JsonObject = {
    schema_version: VISION_CHECKPOINT_SCHEMA_VERSION,
    agent_id: request.agent_id,
    required,
    satisfied,
    decision,
    triggers,
    delivery_boundary: request.delivery_boundary,
  };
  if (request.agent_vision !== null) {
    checkpoint.agent_vision_state = request.agent_vision.state;
  }
  if (unchanged !== null && request.existing_agent_vision !== null) {
    checkpoint.unchanged_reason = unchanged;
    checkpoint.agent_vision_state = request.existing_agent_vision.state;
    const continuityBasis = existingVisionContinuityBasis(
      request.existing_agent_vision,
    );
    if (continuityBasis !== null) {
      checkpoint.continuity_basis = continuityBasis;
    }
  } else if (unchanged !== null) {
    checkpoint.missing_baseline = true;
    checkpoint.rejected_unchanged_reason = unchanged;
  }
  if (!satisfied) {
    checkpoint.required_resolution = ["write_vision_patch"];
    if (checkpoint.missing_baseline !== true) {
      (checkpoint.required_resolution as string[]).push(
        "record_unchanged_reason",
      );
    }
  }
  return checkpoint;
}

import {
  settlementIdentity as buildSettlementIdentity,
  type JsonObject,
  type SettlementIdentity,
} from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  optionalNonEmptyString,
  requireJsonObject,
  requireNonEmptyString,
} from "../runtime_decode.ts";

export const REFRESH_RECOMMENDATION_REQUEST_SCHEMA_VERSION =
  "refresh_recommendation_request_v0";
export const REFRESH_RECOMMENDATION_SCHEMA_VERSION =
  "refresh_recommendation_v0";

const TODO_ID_PATTERN = /^todo_[a-z0-9_-]{3,64}$/;

type RecommendationSource =
  | "explicit_arg"
  | "settlement_bound_todo"
  | "agent_lane_selected_todo"
  | "active_state_next_action"
  | "agent_todo_fallback"
  | "default_refresh_action";

type SettlementAlignment = "not_applicable" | "exact" | "unavailable";
type SettlementGapReason =
  | "identity_mismatch"
  | "candidate_missing"
  | "candidate_mismatch"
  | "candidate_ineligible";

interface RecommendationCandidate extends JsonObject {
  todo_id: string;
  text: string;
  status: string;
  task_class: string;
  claimed_by?: string;
  resume_when?: string;
  resume_ready?: boolean;
  selection_binding?: string;
  claim_required_before_work?: boolean;
}

export interface RefreshRecommendation extends JsonObject {
  schema_version: typeof REFRESH_RECOMMENDATION_SCHEMA_VERSION;
  recommended_action: string;
  recommended_action_source: RecommendationSource;
  authority: "explicit" | "settlement" | "agent_lane" | "shared_goal" | "compatibility" | "default";
  settlement_alignment: SettlementAlignment;
  settlement_gap_reason?: SettlementGapReason;
  todo_id?: string;
  selection_binding?: string;
  claim_required_before_work?: boolean;
}

function todoId(value: unknown, label: string): string {
  const normalized = requireNonEmptyString(value, label).trim().toLowerCase();
  if (!TODO_ID_PATTERN.test(normalized)) {
    throw new EffectRuntimeRequestError(`${label} must be a valid Todo id`);
  }
  return normalized;
}

function optionalBoolean(value: unknown, label: string): boolean | undefined {
  if (value === null || value === undefined) return undefined;
  if (typeof value !== "boolean") {
    throw new EffectRuntimeRequestError(`${label} must be a boolean`);
  }
  return value;
}

function candidate(value: unknown, label: string): RecommendationCandidate | null {
  if (value === null || value === undefined) return null;
  const raw = requireJsonObject(value, label);
  const decoded: RecommendationCandidate = {
    todo_id: todoId(raw.todo_id, `${label}.todo_id`),
    text: requireNonEmptyString(raw.text, `${label}.text`),
    status: requireNonEmptyString(raw.status, `${label}.status`).trim().toLowerCase(),
    task_class: requireNonEmptyString(raw.task_class, `${label}.task_class`)
      .trim()
      .toLowerCase(),
  };
  for (const field of [
    "claimed_by",
    "resume_when",
    "selection_binding",
  ] as const) {
    const normalized = optionalNonEmptyString(raw[field], `${label}.${field}`);
    if (normalized !== null) decoded[field] = normalized;
  }
  const resumeReady = optionalBoolean(raw.resume_ready, `${label}.resume_ready`);
  if (resumeReady !== undefined) decoded.resume_ready = resumeReady;
  const claimRequired = optionalBoolean(
    raw.claim_required_before_work,
    `${label}.claim_required_before_work`,
  );
  if (claimRequired !== undefined) {
    decoded.claim_required_before_work = claimRequired;
  }
  return decoded;
}

function settlementIdentity(value: unknown): SettlementIdentity | null {
  if (value === null || value === undefined) return null;
  const raw = requireJsonObject(value, "refresh_recommendation.settlement_identity");
  const effectId = requireNonEmptyString(
    raw.effect_id,
    "refresh_recommendation.settlement_identity.effect_id",
  );
  const identity = buildSettlementIdentity({
    goal_id: requireNonEmptyString(
      raw.goal_id,
      "refresh_recommendation.settlement_identity.goal_id",
    ),
    agent_id: requireNonEmptyString(
      raw.agent_id,
      "refresh_recommendation.settlement_identity.agent_id",
    ),
    todo_id: todoId(
      raw.todo_id,
      "refresh_recommendation.settlement_identity.todo_id",
    ),
    turn_instance_id: requireNonEmptyString(
      raw.turn_instance_id,
      "refresh_recommendation.settlement_identity.turn_instance_id",
    ),
  });
  if (identity.effect_id !== effectId) {
    throw new EffectRuntimeRequestError(
      "refresh_recommendation.settlement_identity.effect_id mismatch",
    );
  }
  return identity;
}

function candidateIsRunnable(
  value: RecommendationCandidate,
  agentId: string | null,
): boolean {
  if (value.status !== "open" || value.task_class !== "advancement_task") {
    return false;
  }
  if (value.resume_when && value.resume_ready !== true) return false;
  if (agentId && value.claimed_by && value.claimed_by !== agentId) return false;
  return true;
}

function recommendation(
  action: string,
  source: RecommendationSource,
  authority: RefreshRecommendation["authority"],
  settlementAlignment: SettlementAlignment,
  selected: RecommendationCandidate | null = null,
  settlementGapReason?: SettlementGapReason,
): RefreshRecommendation {
  const result: RefreshRecommendation = {
    schema_version: REFRESH_RECOMMENDATION_SCHEMA_VERSION,
    recommended_action: action,
    recommended_action_source: source,
    authority,
    settlement_alignment: settlementAlignment,
  };
  if (settlementGapReason) {
    result.settlement_gap_reason = settlementGapReason;
  }
  if (selected) {
    result.todo_id = selected.todo_id;
    if (selected.selection_binding) {
      result.selection_binding = selected.selection_binding;
    }
    result.claim_required_before_work =
      selected.claim_required_before_work === true || !selected.claimed_by;
  }
  return result;
}

/** Resolve one refresh recommendation without recreating quota eligibility. */
export function resolveRefreshRecommendation(value: unknown): RefreshRecommendation {
  const request = requireJsonObject(value, "refresh_recommendation request");
  if (request.schema_version !== REFRESH_RECOMMENDATION_REQUEST_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("refresh recommendation request schema mismatch");
  }

  const agentId = optionalNonEmptyString(request.agent_id, "refresh_recommendation.agent_id");
  const explicitAction = optionalNonEmptyString(
    request.explicit_action,
    "refresh_recommendation.explicit_action",
  );
  const sharedAction = optionalNonEmptyString(
    request.active_state_next_action,
    "refresh_recommendation.active_state_next_action",
  );
  const defaultAction = requireNonEmptyString(
    request.default_action,
    "refresh_recommendation.default_action",
  );
  if (explicitAction) {
    return recommendation(
      explicitAction,
      "explicit_arg",
      "explicit",
      "not_applicable",
    );
  }
  const settlement = settlementIdentity(request.settlement_identity);
  const settlementCandidate = candidate(
    request.settlement_candidate,
    "refresh_recommendation.settlement_candidate",
  );
  const laneCandidate = candidate(
    request.agent_lane_candidate,
    "refresh_recommendation.agent_lane_candidate",
  );
  const compatibilityCandidate = candidate(
    request.unscoped_agent_todo_fallback,
    "refresh_recommendation.unscoped_agent_todo_fallback",
  );

  let settlementAlignment: SettlementAlignment = "not_applicable";
  let settlementGapReason: SettlementGapReason | undefined;
  let exactSettlementCandidate = false;
  if (settlement) {
    settlementAlignment = "unavailable";
    if (!agentId || settlement.agent_id !== agentId) {
      settlementGapReason = "identity_mismatch";
    } else if (!settlementCandidate) {
      settlementGapReason = "candidate_missing";
    } else if (
      settlementCandidate.todo_id !== settlement.todo_id ||
      settlementCandidate.selection_binding !== "heartbeat_receipt"
    ) {
      settlementGapReason = "candidate_mismatch";
    } else if (!candidateIsRunnable(settlementCandidate, agentId)) {
      settlementGapReason = "candidate_ineligible";
    } else {
      settlementAlignment = "exact";
      exactSettlementCandidate = true;
    }
  }
  if (exactSettlementCandidate && settlementCandidate) {
    return recommendation(
      settlementCandidate.text,
      "settlement_bound_todo",
      "settlement",
      settlementAlignment,
      settlementCandidate,
    );
  }
  if (agentId && laneCandidate && candidateIsRunnable(laneCandidate, agentId)) {
    return recommendation(
      laneCandidate.text,
      "agent_lane_selected_todo",
      "agent_lane",
      settlementAlignment,
      laneCandidate,
      settlementGapReason,
    );
  }
  if (sharedAction) {
    return recommendation(
      sharedAction,
      "active_state_next_action",
      "shared_goal",
      settlementAlignment,
      null,
      settlementGapReason,
    );
  }
  if (
    !agentId &&
    compatibilityCandidate &&
    candidateIsRunnable(compatibilityCandidate, null)
  ) {
    return recommendation(
      compatibilityCandidate.text,
      "agent_todo_fallback",
      "compatibility",
      settlementAlignment,
      compatibilityCandidate,
      settlementGapReason,
    );
  }
  return recommendation(
    defaultAction,
    "default_refresh_action",
    "default",
    settlementAlignment,
    null,
    settlementGapReason,
  );
}

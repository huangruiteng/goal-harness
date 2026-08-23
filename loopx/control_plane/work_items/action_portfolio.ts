import {
  optionalNonEmptyString,
  requireInteger,
  requireJsonObject,
  requireNonEmptyString,
} from "../runtime_decode.ts";

import type { JsonObject } from "../effect_program.ts";

export const ACTION_PORTFOLIO_SCHEMA_VERSION = "quota_action_portfolio_v0";
export const ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION =
  "quota_action_portfolio_request_v0";

const MAX_FALLBACK_ACTIONS = 3;

interface ActionCandidate extends JsonObject {
  todo_id: string;
  text: string;
}

function actionCandidate(value: unknown, label: string): ActionCandidate {
  const raw = requireJsonObject(value, label);
  const candidate: ActionCandidate = {
    todo_id: requireNonEmptyString(raw.todo_id, `${label}.todo_id`),
    text: requireNonEmptyString(raw.text, `${label}.text`),
  };
  for (const field of [
    "priority",
    "status",
    "task_class",
    "action_kind",
    "claimed_by",
    "source",
    "selected_by",
    "availability_reason",
    "next_due_at",
  ] as const) {
    const normalized = optionalNonEmptyString(raw[field], `${label}.${field}`);
    if (normalized !== null) candidate[field] = normalized;
  }
  if (raw.index !== null && raw.index !== undefined) {
    candidate.index = requireInteger(raw.index, `${label}.index`);
  }
  if (raw.claim_required_before_work === true) {
    candidate.claim_required_before_work = true;
  }
  return candidate;
}

function candidateIdentity(candidate: ActionCandidate): string {
  return candidate.todo_id || candidate.text;
}

function requireRunnableAdvancement(
  candidate: ActionCandidate,
  label: string,
): void {
  if (candidate.status !== "open") {
    throw new Error(`${label}.status must be open`);
  }
  if (candidate.task_class !== "advancement_task") {
    throw new Error(`${label}.task_class must be advancement_task`);
  }
}

function primaryProjection(candidate: ActionCandidate): JsonObject {
  return { todo_id: candidate.todo_id };
}

function fallbackProjection(candidate: ActionCandidate): JsonObject {
  const projected: JsonObject = {
    todo_id: candidate.todo_id,
    text: candidate.text,
  };
  for (const field of ["priority", "action_kind", "claimed_by"] as const) {
    if (candidate[field] !== undefined) projected[field] = candidate[field];
  }
  if (candidate.claim_required_before_work === true) {
    projected.claim_required_before_work = true;
  }
  return projected;
}

function unavailableProjection(candidate: ActionCandidate): JsonObject {
  const projected: JsonObject = {
    todo_id: candidate.todo_id,
    text: candidate.text,
    availability_reason: candidate.availability_reason,
  };
  for (const field of [
    "priority",
    "status",
    "task_class",
    "action_kind",
    "next_due_at",
  ] as const) {
    if (candidate[field] !== undefined) projected[field] = candidate[field];
  }
  return projected;
}

/**
 * Build the bounded, model-facing action set for one quota decision.
 *
 * Python owns repository/status projection and supplies only candidates that
 * already passed agent-scope and capability gates. TypeScript owns the stable
 * portfolio semantics: validation, identity de-duplication, ordering, and the
 * fallback trigger exposed to hosts and models.
 */
export function projectQuotaActionPortfolio(value: unknown): JsonObject | null {
  const request = requireJsonObject(value, "action_portfolio_request");
  if (request.schema_version !== ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION) {
    throw new Error(
      `action_portfolio_request.schema_version must be ${ACTION_PORTFOLIO_REQUEST_SCHEMA_VERSION}`,
    );
  }
  const primary = actionCandidate(request.primary, "action_portfolio_request.primary");
  requireRunnableAdvancement(primary, "action_portfolio_request.primary");
  const maximum = request.max_fallback_actions === undefined
    ? 2
    : requireInteger(
      request.max_fallback_actions,
      "action_portfolio_request.max_fallback_actions",
    );
  if (maximum < 1 || maximum > MAX_FALLBACK_ACTIONS) {
    throw new Error(
      `action_portfolio_request.max_fallback_actions must be between 1 and ${MAX_FALLBACK_ACTIONS}`,
    );
  }

  const rawCandidates = Array.isArray(request.candidates) ? request.candidates : [];
  const seen = new Set<string>([candidateIdentity(primary)]);
  const fallbackActions: ActionCandidate[] = [];
  for (const [index, rawCandidate] of rawCandidates.entries()) {
    const candidate = actionCandidate(
      rawCandidate,
      `action_portfolio_request.candidates[${index}]`,
    );
    requireRunnableAdvancement(
      candidate,
      `action_portfolio_request.candidates[${index}]`,
    );
    const identity = candidateIdentity(candidate);
    if (seen.has(identity)) continue;
    seen.add(identity);
    fallbackActions.push(candidate);
    if (fallbackActions.length >= maximum) break;
  }

  const rawUnavailable = Array.isArray(request.unavailable_higher_priority)
    ? request.unavailable_higher_priority
    : [];
  const unavailableHigherPriority: ActionCandidate[] = [];
  const seenUnavailable = new Set<string>();
  for (const [index, rawCandidate] of rawUnavailable.entries()) {
    const candidate = actionCandidate(
      rawCandidate,
      `action_portfolio_request.unavailable_higher_priority[${index}]`,
    );
    if (!candidate.availability_reason) {
      throw new Error(
        `action_portfolio_request.unavailable_higher_priority[${index}].availability_reason must be a non-empty string`,
      );
    }
    const identity = candidateIdentity(candidate);
    if (identity === candidateIdentity(primary) || seenUnavailable.has(identity)) {
      continue;
    }
    seenUnavailable.add(identity);
    unavailableHigherPriority.push(candidate);
    if (unavailableHigherPriority.length >= MAX_FALLBACK_ACTIONS) break;
  }

  if (fallbackActions.length === 0 && unavailableHigherPriority.length === 0) {
    return null;
  }
  return {
    schema_version: ACTION_PORTFOLIO_SCHEMA_VERSION,
    primary: primaryProjection(primary),
    fallback_policy: {
      trigger: "primary_unavailable_at_execution",
      selection: "first_still_runnable_in_order",
      preserve_primary_blocker: true,
      max_fallback_actions: maximum,
    },
    fallback_actions: fallbackActions.map(fallbackProjection),
    unavailable_higher_priority: unavailableHigherPriority.map(
      unavailableProjection,
    ),
  };
}

import type { JsonObject } from "../effect_program.ts";
import {
  requireBoolean,
  requireJsonObject as requiredObject,
  requireNonEmptyString as requiredString,
  requireStringLiteral,
} from "../runtime_decode.ts";

export const REPOSITORY_DELIVERY_GATE_SCHEMA_VERSION =
  "repository_delivery_gate_v0";
export const REPOSITORY_CHANGE_WINDOW_STATUS_SCHEMA_VERSION =
  "repository_change_window_git_hook_status_v2";
export const REPOSITORY_CHANGE_WINDOW_DECISION_SCHEMA_VERSION =
  "repository_change_window_decision_v0";

const ENFORCEMENT_LEVELS = ["hook_only", "reference_guard"] as const;

function verifiedDecision(status: JsonObject): {
  decision: JsonObject;
  enforcementLevel: typeof ENFORCEMENT_LEVELS[number];
} | null {
  if (
    status.schema_version !== REPOSITORY_CHANGE_WINDOW_STATUS_SCHEMA_VERSION ||
    status.provider_id !== "git-hook"
  ) {
    throw new Error("repository change-window status contract is invalid");
  }
  if (status.installed !== true) return null;
  if (
    status.ok !== true ||
    status.enabled !== true ||
    status.status !== "ready" ||
    status.contains_personal_path !== false
  ) return null;
  const enforcementLevel = requireStringLiteral(
    status.enforcement_level,
    ENFORCEMENT_LEVELS,
    "repository change-window enforcement_level",
  );
  if (!Array.isArray(status.checks) || status.checks.length === 0) {
    throw new Error("repository change-window checks are required");
  }
  for (const rawCheck of status.checks) {
    const check = requiredObject(rawCheck, "repository change-window check");
    if (check.ok !== true) return null;
  }
  const decision = requiredObject(
    status.decision,
    "repository change-window decision",
  );
  if (
    decision.schema_version !==
      REPOSITORY_CHANGE_WINDOW_DECISION_SCHEMA_VERSION
  ) {
    throw new Error("repository change-window decision schema is invalid");
  }
  requireBoolean(decision.allowed, "repository change-window decision allowed");
  requiredString(decision.reason, "repository change-window decision reason");
  requiredString(
    decision.observed_at,
    "repository change-window decision observed_at",
  );
  requiredString(
    decision.next_eligible_at,
    "repository change-window decision next_eligible_at",
  );
  return { decision, enforcementLevel };
}

export function projectRepositoryDeliveryGate(
  value: unknown,
): JsonObject | null {
  const status = requiredObject(value, "repository change-window status");
  const verified = verifiedDecision(status);
  if (!verified) return null;
  const admitted = verified.decision.allowed === true;
  const gate: JsonObject = {
    schema_version: REPOSITORY_DELIVERY_GATE_SCHEMA_VERSION,
    provider_id: "git-hook",
    provider_verified: true,
    authority_scope: "local_repository_change_window",
    enforcement_level: verified.enforcementLevel,
    state: admitted ? "admitted" : "blocked",
    change_window_admission: {
      prepare_dirty_worktree: true,
      validate_dirty_worktree: true,
      commit: admitted,
      push: admitted,
    },
    reason: verified.decision.reason,
    linked_worktrees_share_provider: true,
    separate_clones_in_scope: false,
    path_free: true,
    remote_write_authority_granted: false,
  };
  if (!admitted) {
    gate.next_eligible_at = verified.decision.next_eligible_at;
  }
  return gate;
}

import assert from "node:assert/strict";
import test from "node:test";

import {
  CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION,
  INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
  TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION,
  TURN_START_HOOK_RESULT_SCHEMA_VERSION,
  validateInteractionProjectionHookInvocation,
  validateTurnStartHookInvocation,
} from "../../loopx/control_plane/capability_hooks.ts";

function registration(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: CAPABILITY_HOOK_REGISTRATION_SCHEMA_VERSION,
    hook_id: "repository_change_window.repository_delivery",
    capability_id: "repository-change-window",
    phase: "interaction_projection",
    projection_slots: ["repository_delivery"],
    budget: {
      max_invocations_per_dispatch: 1,
      max_result_bytes: 16 * 1024,
    },
    failure_policy: "isolate",
    requested_read_scope: ["repository_status"],
    requested_write_scope: [],
    ...overrides,
  };
}

function status(allowed: boolean) {
  return {
    ok: true,
    schema_version: "repository_change_window_git_hook_status_v2",
    status: "ready",
    installed: true,
    enabled: true,
    provider_id: "git-hook",
    enforcement_level: "reference_guard",
    contains_personal_path: false,
    checks: [{ check: "provider_schema", ok: true, status: "current" }],
    decision: {
      schema_version: "repository_change_window_decision_v0",
      allowed,
      reason: allowed ? "outside_blocked_window" : "inside_blocked_window",
      observed_at: "2026-08-24T11:00:00+08:00",
      next_eligible_at: allowed
        ? "2026-08-24T11:00:00+08:00"
        : "2026-08-24T12:00:00+08:00",
    },
  };
}

function candidate(payload: unknown, overrides: Record<string, unknown> = {}) {
  return {
    schema_version: INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    hook_id: "repository_change_window.repository_delivery",
    capability_id: "repository-change-window",
    phase: "interaction_projection",
    status: "candidate",
    projection_slot: "repository_delivery",
    payload,
    ...overrides,
  };
}

test("verified capability candidate projects separate preparation and delivery admission", () => {
  const blocked = validateInteractionProjectionHookInvocation({
    registration: registration(),
    result: candidate(status(false)),
  });
  assert.equal(blocked.status, "projected");
  assert.deepEqual(blocked.projection, {
    schema_version: "repository_delivery_gate_v0",
    provider_id: "git-hook",
    provider_verified: true,
    authority_scope: "local_repository_change_window",
    enforcement_level: "reference_guard",
    state: "blocked",
    change_window_admission: {
      prepare_dirty_worktree: true,
      validate_dirty_worktree: true,
      commit: false,
      push: false,
    },
    reason: "inside_blocked_window",
    linked_worktrees_share_provider: true,
    separate_clones_in_scope: false,
    path_free: true,
    remote_write_authority_granted: false,
    next_eligible_at: "2026-08-24T12:00:00+08:00",
  });

  const admitted = validateInteractionProjectionHookInvocation({
    registration: registration(),
    result: candidate(status(true)),
  });
  assert.equal(
    (admitted.projection as Record<string, unknown>).state,
    "admitted",
  );
  assert.equal(
    Object.hasOwn(admitted.projection as object, "next_eligible_at"),
    false,
  );
});

test("uninstalled or drifted provider is diagnostic-only", () => {
  const external = {
    ...status(true),
    installed: false,
    enabled: false,
    status: "effective_external_guard_detected",
  };
  const result = validateInteractionProjectionHookInvocation({
    registration: registration(),
    result: candidate(external),
  });
  assert.equal(result.status, "not_applicable");
  assert.equal(result.projection, null);

  const failedCheck = status(true);
  failedCheck.checks[0].ok = false;
  assert.equal(validateInteractionProjectionHookInvocation({
    registration: registration(),
    result: candidate(failedCheck),
  }).status, "not_applicable");
});

test("registration denies effects and candidates cannot escape declared slots", () => {
  assert.throws(
    () => validateInteractionProjectionHookInvocation({
      registration: registration({ requested_write_scope: ["git_config"] }),
      result: candidate(status(true)),
    }),
    /cannot request write scope/,
  );
  assert.throws(
    () => validateInteractionProjectionHookInvocation({
      registration: registration(),
      result: candidate(status(true), { projection_slot: "other_slot" }),
    }),
    /not registered/,
  );
});

function turnStartRegistration(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: TURN_START_HOOK_REGISTRATION_SCHEMA_VERSION,
    hook_id: "operator_inbox.turn_start_sync",
    capability_id: "operator-inbox",
    phase: "turn_start",
    budget: {
      max_invocations_per_dispatch: 1,
      max_result_bytes: 16 * 1024,
    },
    failure_policy: "isolate",
    requested_read_scope: ["provider_history"],
    requested_write_scope: ["owner_private_inbox", "owner_private_cursor"],
    ...overrides,
  };
}

function turnStartResult(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: TURN_START_HOOK_RESULT_SCHEMA_VERSION,
    hook_id: "operator_inbox.turn_start_sync",
    capability_id: "operator-inbox",
    phase: "turn_start",
    status: "observed",
    observation_count: 2,
    agent_read_required: true,
    external_reads_performed: true,
    local_private_state_mutated: true,
    private_content_returned: false,
    provider_payload_returned: false,
    error_code: null,
    ...overrides,
  };
}

test("turn-start observations require Agent reading without returning private content", () => {
  const observed = validateTurnStartHookInvocation({
    registration: turnStartRegistration(),
    result: turnStartResult(),
  });
  assert.equal(observed.status, "observed");
  assert.equal(observed.agent_read_required, true);
  assert.equal(observed.observation_count, 2);

  assert.throws(
    () => validateTurnStartHookInvocation({
      registration: turnStartRegistration(),
      result: turnStartResult({ agent_read_required: false }),
    }),
    /Agent reading|inconsistent/,
  );
  assert.throws(
    () => validateTurnStartHookInvocation({
      registration: turnStartRegistration(),
      result: turnStartResult({ private_content_returned: true }),
    }),
    /private provider content/,
  );
});

test("turn-start empty, provider failure, and owner-private write scopes stay distinct", () => {
  const empty = validateTurnStartHookInvocation({
    registration: turnStartRegistration(),
    result: turnStartResult({
      status: "empty",
      observation_count: 0,
      agent_read_required: false,
      local_private_state_mutated: true,
    }),
  });
  assert.equal(empty.status, "empty");

  const failed = validateTurnStartHookInvocation({
    registration: turnStartRegistration(),
    result: turnStartResult({
      status: "failed",
      observation_count: 0,
      agent_read_required: false,
      local_private_state_mutated: false,
      error_code: "provider_contract_error",
    }),
  });
  assert.equal(failed.error_code, "provider_contract_error");

  assert.throws(
    () => validateTurnStartHookInvocation({
      registration: turnStartRegistration({
        requested_write_scope: ["repository_write"],
      }),
      result: turnStartResult(),
    }),
    /not owner-private/,
  );
});

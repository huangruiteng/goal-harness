import {
  commitStepPayload,
  requireMatchingEffectId,
  seedCommittedSteps,
  settlementFailed,
  settlementIdentityFromPlan,
  settlementNextAction,
  settlementPure,
  settlementResultPayload,
  type JsonObject,
  type SettlementFailureResult,
  type SettlementIdentity,
  type SettlementResult,
  type SettlementStepKind,
} from "../effect_program.ts";
import {
  optionalNonEmptyString,
  requireBoolean,
  requireJsonObject,
  requireStringArray,
  requireStringLiteral,
} from "../runtime_decode.ts";

export const TURN_SETTLEMENT_TRANSACTION_SCHEMA_VERSION =
  "loopx_turn_settlement_transaction_v0";
export const TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION =
  "loopx_turn_settlement_reduction_v0";

const BASE_SETTLEMENT_STEPS = [
  "validation",
  "durable_writeback",
  "quota_spend",
] as const satisfies readonly SettlementStepKind[];

const PROVIDER_STEP_KINDS = [
  "durable_writeback",
  "quota_spend",
  "terminal_closeout",
] as const;
type ProviderStepKind = (typeof PROVIDER_STEP_KINDS)[number];

interface FailedProviderAttempt {
  step_kind: ProviderStepKind;
  payload: JsonObject;
}

interface ProviderEffect {
  step_kind: ProviderStepKind;
  completed_phases: readonly string[];
}

interface TurnSettlementRequest {
  schema_version: typeof TURN_SETTLEMENT_TRANSACTION_SCHEMA_VERSION;
  transaction_plan: JsonObject;
  transaction_phases: readonly string[];
  completed_phases: readonly string[];
  committed_effect_id: string | null;
  writeback_payload: JsonObject | null;
  quota_spend_payload: JsonObject | null;
  terminal_closeout_required: boolean;
  terminal_closeout_payload: JsonObject | null;
  failed_provider_attempt: FailedProviderAttempt | null;
}

export interface TurnSettlementState {
  completed_phases: readonly string[];
  writeback: JsonObject | null;
  quota_spend: JsonObject | null;
}

interface TurnSettlementExecution {
  schema_version: typeof TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION;
  decision: "execute";
  provider_effects: readonly ProviderEffect[];
  result: null;
  settlement_result: null;
}

interface TurnSettlementOutcome {
  schema_version: typeof TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION;
  decision: "complete" | "failed";
  provider_effects: readonly [];
  result: SettlementResult<TurnSettlementState>;
  settlement_result: JsonObject;
}

export type TurnSettlementReduction =
  | TurnSettlementExecution
  | TurnSettlementOutcome;

function optionalObject(value: unknown, label: string): JsonObject | null {
  if (value === null || value === undefined) return null;
  return requireJsonObject(value, label);
}

function decodeFailedProviderAttempt(
  value: unknown,
): FailedProviderAttempt | null {
  if (value === null || value === undefined) return null;
  const attempt = requireJsonObject(value, "failed_provider_attempt");
  return {
    step_kind: requireStringLiteral(
      attempt.step_kind,
      PROVIDER_STEP_KINDS,
      "failed_provider_attempt.step_kind",
    ),
    payload: requireJsonObject(
      attempt.payload,
      "failed_provider_attempt.payload",
    ),
  };
}

function decodeRequest(value: unknown): TurnSettlementRequest {
  const request = requireJsonObject(value, "Turn settlement request");
  const schemaVersion = requireStringLiteral(
    request.schema_version,
    [TURN_SETTLEMENT_TRANSACTION_SCHEMA_VERSION] as const,
    "schema_version",
  );
  return {
    schema_version: schemaVersion,
    transaction_plan: requireJsonObject(
      request.transaction_plan,
      "transaction_plan",
    ),
    transaction_phases: requireStringArray(
      request.transaction_phases,
      "transaction_phases",
    ),
    completed_phases: requireStringArray(
      request.completed_phases,
      "completed_phases",
    ),
    committed_effect_id: optionalNonEmptyString(
      request.committed_effect_id,
      "committed_effect_id",
    ),
    writeback_payload: optionalObject(
      request.writeback_payload,
      "writeback_payload",
    ),
    quota_spend_payload: optionalObject(
      request.quota_spend_payload,
      "quota_spend_payload",
    ),
    terminal_closeout_required: requireBoolean(
      request.terminal_closeout_required,
      "terminal_closeout_required",
    ),
    terminal_closeout_payload: optionalObject(
      request.terminal_closeout_payload,
      "terminal_closeout_payload",
    ),
    failed_provider_attempt: decodeFailedProviderAttempt(
      request.failed_provider_attempt,
    ),
  };
}

function reduction(
  result: SettlementResult<TurnSettlementState>,
): TurnSettlementOutcome {
  return {
    schema_version: TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION,
    decision: result.failure === null ? "complete" : "failed",
    provider_effects: [],
    result,
    settlement_result: settlementResultPayload(result),
  };
}

function execution(
  providerEffects: readonly ProviderEffect[],
): TurnSettlementExecution {
  return {
    schema_version: TURN_SETTLEMENT_REDUCTION_SCHEMA_VERSION,
    decision: "execute",
    provider_effects: providerEffects,
    result: null,
    settlement_result: null,
  };
}

function failedState(
  failure: SettlementFailureResult,
): TurnSettlementOutcome {
  return reduction(failure);
}

function providerFailure(
  identity: SettlementIdentity,
  request: TurnSettlementRequest,
  stepKind: ProviderStepKind,
  receipts: SettlementResult<unknown>["receipts"],
): TurnSettlementOutcome {
  const attempt = request.failed_provider_attempt;
  if (!attempt || attempt.step_kind !== stepKind) {
    return reduction(
      settlementFailed({
        kind: "receipt_missing",
        step_kind: stepKind,
        reason: `Turn settlement is missing its ${stepKind} provider outcome`,
        receipts,
      }),
    );
  }
  const committed = commitStepPayload({
    identity,
    step_kind: stepKind,
    transaction_phases:
      stepKind === "terminal_closeout"
        ? ["terminal_closeout"]
        : request.transaction_phases,
    payload: attempt.payload,
  });
  if (committed.result.failure === null) {
    throw new Error(
      `failed_provider_attempt for ${stepKind} unexpectedly committed`,
    );
  }
  return reduction({
    value: null,
    receipts: [...receipts, ...committed.result.receipts],
    failure: committed.result.failure,
  });
}

function pendingProviderEffects(
  request: TurnSettlementRequest,
  firstStep: ProviderStepKind,
): readonly ProviderEffect[] {
  const completed = new Set(request.completed_phases);
  const effects: ProviderEffect[] = [];
  for (const step of BASE_SETTLEMENT_STEPS) {
    if (step === "validation" || completed.has(step)) continue;
    const phaseIndex = request.transaction_phases.indexOf(step);
    if (phaseIndex < 0) {
      throw new Error(`transaction phases do not contain ${step}`);
    }
    effects.push({
      step_kind: step,
      completed_phases: request.transaction_phases.slice(0, phaseIndex + 1),
    });
  }
  if (effects[0]?.step_kind !== firstStep) {
    throw new Error(`Turn settlement next provider is not ${firstStep}`);
  }
  if (request.terminal_closeout_required) {
    effects.push({
      step_kind: "terminal_closeout",
      completed_phases: [...request.completed_phases],
    });
  }
  return effects;
}

/**
 * Reduce one complete Turn settlement snapshot.
 *
 * The first reduction validates identity, replay, and the committed journal
 * prefix before authorizing still-Python provider effects. The second reduces
 * their checkpointed outcomes into the canonical receipt chain and result.
 * A replay that needs no provider effect completes in one reduction.
 */
export function reduceTurnSettlementTransaction(
  value: unknown,
): TurnSettlementReduction {
  const request = decodeRequest(value);
  const identityResult = settlementIdentityFromPlan(request.transaction_plan);
  if (identityResult.failure !== null) return failedState(identityResult);

  const identity = identityResult.value;
  const matching = requireMatchingEffectId(
    request.committed_effect_id,
    identity.effect_id,
  );
  if (matching.failure !== null) return failedState(matching);

  const base = settlementNextAction({
    identity,
    ordered_steps: BASE_SETTLEMENT_STEPS,
    committed_payloads: {
      validation: {},
      durable_writeback: request.writeback_payload,
      quota_spend: request.quota_spend_payload,
    },
    completed_phases: request.completed_phases,
    transaction_phases: request.transaction_phases,
    require_validation: true,
    source_ref_prefix: "turn_journal",
  });
  if (base.decision === "failed") return failedState(base.result);
  if (base.decision === "execute") {
    if (base.step_kind === "validation" || base.step_kind === "terminal_closeout") {
      throw new Error(`unsupported base settlement step ${base.step_kind}`);
    }
    return request.failed_provider_attempt === null
      ? execution(pendingProviderEffects(request, base.step_kind))
      : providerFailure(
          identity,
          request,
          base.step_kind,
          base.result.receipts,
        );
  }

  let receipts = [...base.result.receipts];
  if (request.terminal_closeout_required) {
    if (request.terminal_closeout_payload === null) {
      return request.failed_provider_attempt === null
        ? execution([
            {
              step_kind: "terminal_closeout",
              completed_phases: [...request.completed_phases],
            },
          ])
        : providerFailure(
            identity,
            request,
            "terminal_closeout",
            receipts,
          );
    }
    const terminal = seedCommittedSteps({
      identity,
      ordered_steps: ["terminal_closeout"],
      committed_payloads: {
        terminal_closeout: request.terminal_closeout_payload,
      },
      completed_phases: ["terminal_closeout"],
      transaction_phases: ["terminal_closeout"],
      require_validation: false,
      source_ref_prefix: "turn_journal",
    });
    if (terminal.failure !== null) return failedState(terminal);
    receipts = [...receipts, ...terminal.receipts];
  } else if (request.terminal_closeout_payload !== null) {
    return reduction(
      settlementFailed({
        kind: "terminal_closeout_rejected",
        step_kind: "terminal_closeout",
        reason: "Turn settlement contains an unrequested terminal closeout",
        receipts,
      }),
    );
  }

  if (request.failed_provider_attempt !== null) {
    throw new Error(
      "failed_provider_attempt remains after all required settlement effects committed",
    );
  }
  return reduction(
    settlementPure(
      {
        completed_phases: [...request.completed_phases],
        writeback: request.writeback_payload,
        quota_spend: request.quota_spend_payload,
      },
      receipts,
    ),
  );
}

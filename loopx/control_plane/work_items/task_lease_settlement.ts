import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  settlementFailed,
  settlementIdentity,
  settlementPlanPayload,
  settlementPure,
  settlementReceipt,
  settlementResultPayload,
  type JsonObject,
  type SettlementFailureKind,
  type SettlementIdentity,
  type SettlementPlan,
  type SettlementResult,
  type SettlementStepKind,
} from "../effect_program.ts";
import {
  requireJsonObject,
  requireStringLiteral,
} from "../runtime_decode.ts";

export const TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION =
  "loopx_task_lease_acquire_transaction_v0";
export const TASK_LEASE_ACQUIRE_REDUCTION_SCHEMA_VERSION =
  "loopx_task_lease_acquire_reduction_v0";

const PHASES = ["preflight", "finalize"] as const;
type TaskLeaseAcquirePhase = (typeof PHASES)[number];

interface TaskLeaseAcquireInput {
  goal_id: string;
  owner: string;
  todo_id: string;
  idempotency_key: string;
  write_scopes: readonly string[];
  ttl_seconds: number | null;
  expected_version: number | null;
}

interface TaskLeaseAcquireTransaction extends TaskLeaseAcquireInput {
  schema_version: typeof TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION;
  identity: SettlementIdentity;
}

interface TaskLeaseProviderResult {
  effect_id: string;
  ok: boolean;
  acquired: boolean | null;
  idempotent: boolean | null;
  lease: JsonObject | null;
  lease_path: string | null;
  error: string | null;
  error_code: string | null;
  task_lease_payload: JsonObject | null;
}

interface TaskLeaseProviderEffect {
  step_kind: "durable_writeback";
  action: "acquire";
  effect_id: string;
  effect_ref: string;
  parameters: TaskLeaseAcquireInput;
}

interface TaskLeaseAcquireReduction {
  schema_version: typeof TASK_LEASE_ACQUIRE_REDUCTION_SCHEMA_VERSION;
  decision: "execute" | "complete" | "failed";
  transaction: TaskLeaseAcquireTransaction | null;
  settlement_plan: JsonObject | null;
  provider_effect: TaskLeaseProviderEffect | null;
  result: SettlementResult<JsonObject> | null;
  settlement_result: JsonObject | null;
}

const INVALID_IDENTITY_CODES = new Set([
  "invalid_goal_id",
  "invalid_todo_id",
  "invalid_owner",
  "invalid_idempotency_key",
  "invalid_ttl",
  "idempotency_key_reuse",
]);

const PERMISSION_DENIED_CODES = new Set([
  "owner_not_registered",
  "todo_not_found",
  "todo_not_open",
  "owner_excluded_from_todo",
  "owner_conflicts_with_claim",
]);

const VALIDATION_FAILURE_CODES = new Set([
  "owner_not_registered",
  "todo_not_found",
  "todo_not_open",
  "owner_excluded_from_todo",
  "owner_conflicts_with_claim",
  "todo_lease_conflict",
  "write_scope_conflict",
]);

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new EffectRuntimeRequestError(`${label} must be a string`);
  }
  return value;
}

function nullableInteger(value: unknown, label: string): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new EffectRuntimeRequestError(`${label} must be an integer or null`);
  }
  return value;
}

function stringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new EffectRuntimeRequestError(`${label} must be an array`);
  }
  return value.map((item, index) =>
    stringValue(item, `${label}[${index}]`)
  );
}

function compact(value: string): string {
  return value.trim().split(/\s+/u).filter(Boolean).join(" ");
}

function invalidIdentity(
  reason: string,
  code: string,
): SettlementResult<JsonObject> {
  return settlementFailed({
    kind: "invalid_identity",
    step_kind: "validation",
    reason,
    details: { task_lease_error_code: code },
  });
}

function normalizeInput(
  value: JsonObject,
): TaskLeaseAcquireInput | SettlementResult<JsonObject> {
  const rawGoalId = stringValue(value.goal_id, "goal_id");
  const goalId = rawGoalId.trim();
  if (
    goalId.length === 0 || goalId === "." || goalId === ".." ||
    goalId.includes("/") || goalId.includes("\\")
  ) {
    return invalidIdentity("goal id must be a single path segment", "invalid_goal_id");
  }

  const owner = compact(stringValue(value.owner, "owner"))
    .toLowerCase()
    .replaceAll(" ", "-");
  if (!/^[a-z][a-z0-9_.:@-]{0,79}$/u.test(owner)) {
    return invalidIdentity("owner must be a public-safe agent id", "invalid_owner");
  }

  const todoId = stringValue(value.todo_id, "todo_id").trim().toLowerCase();
  if (!/^todo_[a-z0-9_-]{3,64}$/u.test(todoId)) {
    return invalidIdentity(
      "todo id must use the todo_<token> shape",
      "invalid_todo_id",
    );
  }

  const idempotencyKey = stringValue(
    value.idempotency_key,
    "idempotency_key",
  ).trim();
  if (!/^[A-Za-z0-9_.:@/-]{1,160}$/u.test(idempotencyKey)) {
    return invalidIdentity(
      "idempotency key must be a public-safe token",
      "invalid_idempotency_key",
    );
  }

  return {
    goal_id: goalId,
    owner,
    todo_id: todoId,
    idempotency_key: idempotencyKey,
    write_scopes: stringList(value.write_scopes, "write_scopes"),
    ttl_seconds: nullableInteger(value.ttl_seconds, "ttl_seconds"),
    expected_version: nullableInteger(value.expected_version, "expected_version"),
  };
}

function shellArgument(value: string | number): string {
  const rendered = String(value);
  if (/^[A-Za-z0-9_./:@*?=-]+$/u.test(rendered)) return rendered;
  const escaped = rendered.replaceAll("'", "'\"'\"'");
  return "'" + escaped + "'";
}

function settlementPlan(
  identity: SettlementIdentity,
  input: TaskLeaseAcquireInput,
): SettlementPlan {
  const scopes = [...new Set(input.write_scopes)].sort((left, right) =>
    left.localeCompare(right)
  );
  const ttl = input.ttl_seconds ?? 2700;
  const command = [
    "loopx task-lease acquire",
    `--goal-id ${shellArgument(identity.goal_id)}`,
    `--todo-id ${shellArgument(identity.todo_id ?? "")}`,
    `--owner ${shellArgument(identity.agent_id)}`,
    `--idempotency-key ${shellArgument(identity.turn_instance_id)}`,
    `--ttl-seconds ${shellArgument(ttl)}`,
    ...scopes.map((scope) => `--write-scope ${shellArgument(scope)}`),
    ...(input.expected_version === null
      ? []
      : [`--expected-version ${shellArgument(input.expected_version)}`]),
  ].join(" ");
  return {
    identity,
    steps: [
      {
        kind: "validation",
        owner: "agent",
        precondition:
          "task-lease identity is normalized before the atomic provider is invoked",
        idempotency_key_ref: "$.identity.effect_id",
        expected_receipt: "task_lease_validation_receipt",
      },
      {
        kind: "durable_writeback",
        owner: "agent",
        precondition:
          "the atomic task-lease provider owns eligibility, conflict, CAS, " +
          "and file persistence checks",
        idempotency_key_ref: "$.identity.effect_id",
        expected_receipt: "task_lease_acquire_receipt",
        command_template: command,
      },
    ],
  };
}

function outcome(
  result: SettlementResult<JsonObject>,
  transaction: TaskLeaseAcquireTransaction | null = null,
  plan: JsonObject | null = null,
): TaskLeaseAcquireReduction {
  return {
    schema_version: TASK_LEASE_ACQUIRE_REDUCTION_SCHEMA_VERSION,
    decision: result.failure === null ? "complete" : "failed",
    transaction,
    settlement_plan: plan,
    provider_effect: null,
    result,
    settlement_result: settlementResultPayload(result),
  };
}

function preflight(request: JsonObject): TaskLeaseAcquireReduction {
  const input = normalizeInput(request);
  if ("failure" in input) return outcome(input);
  const identity = settlementIdentity({
    goal_id: input.goal_id,
    agent_id: input.owner,
    todo_id: input.todo_id,
    turn_instance_id: input.idempotency_key,
  });
  const transaction: TaskLeaseAcquireTransaction = {
    schema_version: TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION,
    ...input,
    identity,
  };
  const plan = settlementPlanPayload(settlementPlan(identity, input));
  return {
    schema_version: TASK_LEASE_ACQUIRE_REDUCTION_SCHEMA_VERSION,
    decision: "execute",
    transaction,
    settlement_plan: plan,
    provider_effect: {
      step_kind: "durable_writeback",
      action: "acquire",
      effect_id: identity.effect_id,
      effect_ref: `${identity.effect_id}#durable_writeback`,
      parameters: input,
    },
    result: null,
    settlement_result: null,
  };
}

function decodeTransaction(value: unknown): TaskLeaseAcquireTransaction {
  const transaction = requireJsonObject(value, "transaction");
  if (transaction.schema_version !== TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("Task-lease transaction schema mismatch");
  }
  const input = normalizeInput(transaction);
  if ("failure" in input) {
    throw new EffectRuntimeRequestError("Task-lease transaction identity is invalid");
  }
  const identityValue = requireJsonObject(transaction.identity, "transaction.identity");
  const identity = settlementIdentity({
    goal_id: input.goal_id,
    agent_id: input.owner,
    todo_id: input.todo_id,
    turn_instance_id: input.idempotency_key,
  });
  if (identityValue.effect_id !== identity.effect_id) {
    throw new EffectRuntimeRequestError("Task-lease transaction identity mismatch");
  }
  return { schema_version: TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION, ...input, identity };
}

function decodeProviderResult(value: unknown): TaskLeaseProviderResult {
  const result = requireJsonObject(value, "provider_result");
  const ok = result.ok;
  if (typeof ok !== "boolean") {
    throw new EffectRuntimeRequestError("provider_result.ok must be a boolean");
  }
  const optionalBoolean = (candidate: unknown, label: string): boolean | null => {
    if (candidate === null || candidate === undefined) return null;
    if (typeof candidate !== "boolean") {
      throw new EffectRuntimeRequestError(`${label} must be a boolean or null`);
    }
    return candidate;
  };
  const optionalString = (candidate: unknown, label: string): string | null => {
    if (candidate === null || candidate === undefined) return null;
    const rendered = stringValue(candidate, label);
    return rendered.trim().length > 0 ? rendered : null;
  };
  return {
    effect_id: stringValue(result.effect_id, "provider_result.effect_id"),
    ok,
    acquired: optionalBoolean(result.acquired, "provider_result.acquired"),
    idempotent: optionalBoolean(result.idempotent, "provider_result.idempotent"),
    lease: result.lease === null || result.lease === undefined
      ? null
      : requireJsonObject(result.lease, "provider_result.lease"),
    lease_path: optionalString(result.lease_path, "provider_result.lease_path"),
    error: optionalString(result.error, "provider_result.error"),
    error_code: optionalString(result.error_code, "provider_result.error_code"),
    task_lease_payload:
      result.task_lease_payload === null || result.task_lease_payload === undefined
        ? null
        : requireJsonObject(
          result.task_lease_payload,
          "provider_result.task_lease_payload",
        ),
  };
}

function providerFailureKind(code: string): SettlementFailureKind {
  if (INVALID_IDENTITY_CODES.has(code)) return "invalid_identity";
  if (PERMISSION_DENIED_CODES.has(code)) return "permission_denied";
  return "writeback_rejected";
}

function providerFailureStep(code: string): SettlementStepKind {
  return VALIDATION_FAILURE_CODES.has(code) ? "validation" : "durable_writeback";
}

function finalize(request: JsonObject): TaskLeaseAcquireReduction {
  const transaction = decodeTransaction(request.transaction);
  const plan = settlementPlanPayload(settlementPlan(transaction.identity, transaction));
  const provider = decodeProviderResult(request.provider_result);
  const validationReceipt = settlementReceipt(
    transaction.identity,
    "validation",
    provider.lease_path ?? undefined,
  );
  if (provider.effect_id !== transaction.identity.effect_id) {
    return outcome(
      settlementFailed({
        kind: "identity_mismatch",
        step_kind: "durable_writeback",
        reason: "task-lease provider result does not match the current transaction",
        receipts: [validationReceipt],
      }),
      transaction,
      plan,
    );
  }
  if (!provider.ok) {
    const code = provider.error_code ?? "task_lease_writeback_rejected";
    const stepKind = providerFailureStep(code);
    return outcome(
      settlementFailed({
        kind: providerFailureKind(code),
        step_kind: stepKind,
        reason: provider.error ?? "task lease acquire was rejected",
        receipts: stepKind === "validation" ? [] : [validationReceipt],
        details: {
          task_lease_error_code: code,
          ...(provider.task_lease_payload
            ? { task_lease_payload: provider.task_lease_payload }
            : {}),
        },
      }),
      transaction,
      plan,
    );
  }
  if (provider.lease === null || provider.lease_path === null) {
    return outcome(
      settlementFailed({
        kind: "writeback_missing",
        step_kind: "durable_writeback",
        reason: "task-lease provider committed without a lease and durable path",
        receipts: [validationReceipt],
      }),
      transaction,
      plan,
    );
  }
  const status = provider.idempotent === true || provider.acquired === false
    ? "idempotent"
    : "committed";
  const receipts = [
    { ...validationReceipt, status },
    {
      ...settlementReceipt(
        transaction.identity,
        "durable_writeback",
        provider.lease_path,
      ),
      status,
    },
  ];
  return outcome(
    settlementPure(provider.lease, receipts),
    transaction,
    plan,
  );
}

export function reduceTaskLeaseAcquire(
  value: unknown,
): TaskLeaseAcquireReduction {
  const request = requireJsonObject(value, "task_lease.acquire params");
  if (request.schema_version !== TASK_LEASE_ACQUIRE_TRANSACTION_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("Task-lease acquire request schema mismatch");
  }
  const phase: TaskLeaseAcquirePhase = requireStringLiteral(
    request.phase,
    PHASES,
    "phase",
  );
  return phase === "preflight" ? preflight(request) : finalize(request);
}

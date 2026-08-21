import {
  commitStepPayload,
  effectIdsMatch,
  effectProgramFromOrderedSteps,
  requireMatchingEffectId,
  interpretQuotaShouldRunPacket,
  interpretTurnResultPacket,
  seedCommittedSteps,
  settlementBindGate,
  settlementBindReduce,
  settlementReceipt,
  isCommittedPayload,
  settlementIdentity,
  settlementIdentityPayload,
  settlementIdentityFromPlan,
  settlementNextAction,
  settlementPlanPayload,
  settlementResultPayload,
  SETTLEMENT_FAILURE_KINDS,
  SETTLEMENT_STEP_KINDS,
  type JsonObject,
  type SettlementFailure,
  type SettlementFailureKind,
  type SettlementIdentityInput,
  type SettlementPlan,
  type SettlementReceipt,
  type SettlementResult,
  type SettlementStep,
  type SettlementStepKind,
} from "./effect_program.ts";
import {
  governedCapabilitySettlementStatus,
  validateGovernedCapabilityAdmission,
  validateGovernedCapabilityResult,
  validateGovernedCapabilitySettlementCallback,
} from "./governed_capability.ts";
import {
  interpretTurnJournal,
  type TurnJournalInspectionRequest,
} from "./turn_driver/turn_journal.ts";
import { commitTurnJournal } from "./turn_driver/turn_journal_effects.ts";
import { evaluateTodoCompletionFence } from "./todos/completion_fence.ts";
import {
  buildTodoCompletionMetadataUpdates,
  normalizeTodoCompletionValue,
  requireTodoCompletionMetadataValue,
  selectTodoCompletionContinuation,
  selectTodoCompletionState,
} from "./todos/completion_state.ts";
import { transitionTodoNextAction } from "./todos/next_action.ts";

type EffectRuntimeHandler = (params: JsonObject) => unknown | Promise<unknown>;

export interface EffectRuntimeHandlerContext {
  fingerprint: string;
  requestShutdown: () => void;
}

function asObject(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

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
  return value;
}

function optionalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  return requiredString(value, label);
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} must be an array of strings`);
  }
  return [...value];
}

function settlementStepKind(value: unknown, label: string): SettlementStepKind {
  const candidate = requiredString(value, label);
  if (!SETTLEMENT_STEP_KINDS.includes(candidate as SettlementStepKind)) {
    throw new Error(`${label} has an unsupported settlement step kind`);
  }
  return candidate as SettlementStepKind;
}

function settlementFailureKind(
  value: unknown,
  label: string,
): SettlementFailureKind {
  const candidate = requiredString(value, label);
  if (!SETTLEMENT_FAILURE_KINDS.includes(candidate as SettlementFailureKind)) {
    throw new Error(`${label} has an unsupported settlement failure kind`);
  }
  return candidate as SettlementFailureKind;
}

function settlementIdentityInput(
  value: unknown,
  label = "identity",
): SettlementIdentityInput {
  const input = requiredObject(value, label);
  return {
    goal_id: requiredString(input.goal_id, `${label}.goal_id`),
    agent_id: requiredString(input.agent_id, `${label}.agent_id`),
    todo_id: optionalString(input.todo_id, `${label}.todo_id`),
    turn_instance_id: requiredString(
      input.turn_instance_id,
      `${label}.turn_instance_id`,
    ),
    replan_obligation_id: optionalString(
      input.replan_obligation_id,
      `${label}.replan_obligation_id`,
    ),
  };
}

function settlementReceiptInput(
  value: unknown,
  label: string,
): SettlementReceipt {
  const receipt = requiredObject(value, label);
  return {
    step_kind: settlementStepKind(receipt.step_kind, `${label}.step_kind`),
    status: requiredString(receipt.status, `${label}.status`),
    effect_id: requiredString(receipt.effect_id, `${label}.effect_id`),
    ...(optionalString(receipt.source_ref, `${label}.source_ref`)
      ? { source_ref: optionalString(receipt.source_ref, `${label}.source_ref`)! }
      : {}),
  };
}

function settlementFailureInput(value: unknown, label: string): SettlementFailure {
  const failure = requiredObject(value, label);
  const details = failure.details === undefined
    ? undefined
    : requiredObject(failure.details, `${label}.details`);
  return {
    kind: settlementFailureKind(failure.kind, `${label}.kind`),
    step_kind: settlementStepKind(failure.step_kind, `${label}.step_kind`),
    reason: requiredString(failure.reason, `${label}.reason`),
    ...(details ? { details } : {}),
  };
}

function settlementResultInput(value: unknown, label: string): SettlementResult {
  const result = requiredObject(value, label);
  if (!Array.isArray(result.receipts)) {
    throw new Error(`${label}.receipts must be an array`);
  }
  const receipts = result.receipts.map((receipt, index) =>
    settlementReceiptInput(receipt, `${label}.receipts[${index}]`)
  );
  if (result.failure === null) {
    return { value: result.value, receipts, failure: null };
  }
  if (result.value !== null) {
    throw new Error(`${label} cannot carry both a value and a failure`);
  }
  return {
    value: null,
    receipts,
    failure: settlementFailureInput(result.failure, `${label}.failure`),
  };
}

function settlementStepInput(value: unknown, label: string): SettlementStep {
  const step = requiredObject(value, label);
  if (step.conditional !== undefined && step.conditional !== true) {
    throw new Error(`${label}.conditional must be true when present`);
  }
  return {
    kind: settlementStepKind(step.kind, `${label}.kind`),
    owner: requiredString(step.owner, `${label}.owner`),
    precondition: requiredString(step.precondition, `${label}.precondition`),
    idempotency_key_ref: requiredString(
      step.idempotency_key_ref,
      `${label}.idempotency_key_ref`,
    ),
    expected_receipt: requiredString(
      step.expected_receipt,
      `${label}.expected_receipt`,
    ),
    ...(optionalString(step.command_template, `${label}.command_template`)
      ? {
          command_template: optionalString(
            step.command_template,
            `${label}.command_template`,
          )!,
        }
      : {}),
    ...(step.conditional === true ? { conditional: true } : {}),
  };
}

function settlementPlanInput(value: unknown, label: string): SettlementPlan {
  const plan = requiredObject(value, label);
  if (!Array.isArray(plan.steps)) {
    throw new Error(`${label}.steps must be an array`);
  }
  return {
    identity: settlementIdentity(settlementIdentityInput(plan.identity, `${label}.identity`)),
    steps: plan.steps.map((step, index) =>
      settlementStepInput(step, `${label}.steps[${index}]`)
    ),
  };
}

function turnJournalInspectionRequest(
  value: unknown,
): TurnJournalInspectionRequest {
  const request = requiredObject(value, "turn_journal.inspect params");
  if (
    request.schema_version !==
      "loopx_turn_journal_interpretation_request_v0"
  ) {
    throw new Error("Turn-journal interpretation request schema mismatch");
  }
  return {
    schema_version: request.schema_version,
    journal: requiredObject(request.journal, "turn_journal.inspect journal"),
    goal_id: requiredString(request.goal_id, "turn_journal.inspect goal_id"),
    agent_id: requiredString(request.agent_id, "turn_journal.inspect agent_id"),
    turn_key: requiredString(request.turn_key, "turn_journal.inspect turn_key"),
  };
}

function settlementStepKinds(value: unknown, label: string): SettlementStepKind[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value.map((step, index) =>
    settlementStepKind(step, `${label}[${index}]`)
  );
}

function missingFailureKinds(value: unknown): Partial<
  Record<SettlementStepKind, SettlementFailureKind>
> {
  const source = requiredObject(value, "missing_failure_kinds");
  const decoded: Partial<Record<SettlementStepKind, SettlementFailureKind>> = {};
  for (const [step, kind] of Object.entries(source)) {
    decoded[settlementStepKind(step, "missing_failure_kinds key")] =
      settlementFailureKind(kind, `missing_failure_kinds.${step}`);
  }
  return decoded;
}

export function createEffectRuntimeHandlers(
  context: EffectRuntimeHandlerContext,
): ReadonlyMap<string, EffectRuntimeHandler> {
  return new Map<string, EffectRuntimeHandler>([
    [
      "runtime.ping",
      () => ({ ready: true, pid: process.pid, fingerprint: context.fingerprint }),
    ],
    [
      "runtime.shutdown",
      () => {
        context.requestShutdown();
        return { stopped: true };
      },
    ],
    [
      "turn_journal.inspect",
      (params) => interpretTurnJournal(turnJournalInspectionRequest(params)),
    ],
    ["turn_journal.write", commitTurnJournal],
    ["todo.completion_fence.evaluate", evaluateTodoCompletionFence],
    ["todo.completion_state.normalize", normalizeTodoCompletionValue],
    ["todo.completion_state.require_metadata", requireTodoCompletionMetadataValue],
    ["todo.completion_state.continuation_for_write", selectTodoCompletionContinuation],
    ["todo.completion_state.evaluate", selectTodoCompletionState],
    ["todo.completion_state.metadata_updates", buildTodoCompletionMetadataUpdates],
    ["todo.next_action.transition", transitionTodoNextAction],
    [
      "effect.program_from_ordered_steps",
      (params) => effectProgramFromOrderedSteps(
        Array.isArray(params.ordered_steps) ? params.ordered_steps : [],
        typeof params.execution_mode === "string" ? params.execution_mode : null,
      ),
    ],
    [
      "effect.interpret_quota",
      (params) => interpretQuotaShouldRunPacket(
        asObject(params.packet),
        asObject(params.identity),
      ),
    ],
    [
      "effect.interpret_turn_result",
      (params) => interpretTurnResultPacket(
        asObject(params.packet),
        asObject(params.identity),
      ),
    ],
    [
      "governed_capability.validate_admission",
      (params) => validateGovernedCapabilityAdmission({
        admission: params.admission,
        todo_id: requiredString(params.todo_id, "todo_id"),
        todo_contract: params.todo_contract,
      }),
    ],
    [
      "governed_capability.validate_result",
      (params) => validateGovernedCapabilityResult({
        value: params.value,
        invocation_id: requiredString(params.invocation_id, "invocation_id"),
        effect_id: requiredString(params.effect_id, "effect_id"),
        result_schema: requiredString(params.result_schema, "result_schema"),
        effect_class: requiredString(params.effect_class, "effect_class"),
      }),
    ],
    [
      "governed_capability.validate_settlement_callback",
      (params) => validateGovernedCapabilitySettlementCallback({
        payload: params.payload,
        effect_id: requiredString(params.effect_id, "effect_id"),
        effect_receipt_digest: requiredString(
          params.effect_receipt_digest,
          "effect_receipt_digest",
        ),
        require_receipt_digest: params.require_receipt_digest === true,
      }),
    ],
    [
      "governed_capability.settlement_status",
      (params) => governedCapabilitySettlementStatus(params.failure),
    ],
    [
      "settlement.identity",
      (params) => settlementIdentity(settlementIdentityInput(params)),
    ],
    [
      "settlement.identity_full",
      (params) => {
        const identity = settlementIdentity(
          settlementIdentityInput(params),
        );
        return { identity, payload: settlementIdentityPayload(identity) };
      },
    ],
    ["settlement.identity_from_plan", settlementIdentityFromPlan],
    [
      "settlement.match_effect",
      (params) => requireMatchingEffectId(
        typeof params.committed_effect_id === "string"
          ? params.committed_effect_id
          : null,
        requiredString(params.expected_effect_id, "expected_effect_id"),
      ),
    ],
    [
      "settlement.effect_ids_match",
      (params) => effectIdsMatch(
        typeof params.committed_effect_id === "string"
          ? params.committed_effect_id
          : null,
        requiredString(params.expected_effect_id, "expected_effect_id"),
      ),
    ],
    [
      "settlement.receipt",
      (params) => settlementReceipt(
        settlementIdentityInput(params.identity),
        settlementStepKind(params.step_kind, "step_kind"),
        typeof params.source_ref === "string" ? params.source_ref : undefined,
      ),
    ],
    ["settlement.is_committed_payload", (params) => isCommittedPayload(params.payload)],
    [
      "settlement.bind_gate",
      (params) => settlementBindGate(settlementResultInput(params.result, "result")),
    ],
    [
      "settlement.bind_reduce",
      (params) => settlementBindReduce(
        settlementResultInput(params.current, "current"),
        settlementResultInput(params.next, "next"),
      ),
    ],
    [
      "settlement.plan_payload",
      (params) => settlementPlanPayload(settlementPlanInput(params.plan, "plan")),
    ],
    [
      "settlement.result_payload",
      (params) => settlementResultPayload(
        settlementResultInput(params.result, "result"),
      ),
    ],
    [
      "settlement.seed",
      (params) => seedCommittedSteps({
        identity: settlementIdentityInput(params.identity),
        ordered_steps: settlementStepKinds(params.ordered_steps, "ordered_steps"),
        committed_payloads: asObject(params.committed_payloads),
        completed_phases: Array.isArray(params.completed_phases)
          ? stringArray(params.completed_phases, "completed_phases")
          : null,
        transaction_phases: Array.isArray(params.transaction_phases)
          ? stringArray(params.transaction_phases, "transaction_phases")
          : null,
        require_validation: params.require_validation !== false,
        missing_failure_kinds: missingFailureKinds(params.missing_failure_kinds),
        source_ref_prefix: typeof params.source_ref_prefix === "string"
          ? params.source_ref_prefix
          : undefined,
      }),
    ],
    [
      "settlement.next_action",
      (params) => settlementNextAction({
        identity: settlementIdentityInput(params.identity),
        ordered_steps: settlementStepKinds(params.ordered_steps, "ordered_steps"),
        committed_payloads: asObject(params.committed_payloads),
        completed_phases: Array.isArray(params.completed_phases)
          ? stringArray(params.completed_phases, "completed_phases")
          : null,
        transaction_phases: Array.isArray(params.transaction_phases)
          ? stringArray(params.transaction_phases, "transaction_phases")
          : null,
        require_validation: params.require_validation !== false,
        missing_failure_kinds: missingFailureKinds(params.missing_failure_kinds),
        source_ref_prefix: typeof params.source_ref_prefix === "string"
          ? params.source_ref_prefix
          : undefined,
      }),
    ],
    [
      "settlement.commit_reduction",
      (params) => commitStepPayload({
        identity: settlementIdentityInput(params.identity),
        step_kind: settlementStepKind(params.step_kind, "step_kind"),
        transaction_phases: Array.isArray(params.transaction_phases)
          ? stringArray(params.transaction_phases, "transaction_phases")
          : [],
        payload: params.payload,
        source_ref_prefix: typeof params.source_ref_prefix === "string"
          ? params.source_ref_prefix
          : undefined,
      }),
    ],
  ]);
}

export async function dispatchEffectRuntimeMethod(
  handlers: ReadonlyMap<string, EffectRuntimeHandler>,
  method: string,
  params: JsonObject,
): Promise<unknown> {
  const handler = handlers.get(method);
  if (!handler) throw new Error("unsupported Effect runtime method");
  return await handler(params);
}

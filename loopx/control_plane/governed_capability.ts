import type { JsonObject } from "./effect_program.ts";
import { EffectRuntimeRequestError } from "./effect_runtime_errors.ts";
import {
  assertNever,
  requireNonEmptyString as requiredString,
  requireStringLiteral,
} from "./runtime_decode.ts";

export const EXTERNAL_EFFECT_RECEIPT_SCHEMA_VERSION =
  "loopx_external_effect_receipt_v0";
export const CONTINUOUS_MONITOR_PROPOSAL_SCHEMA_VERSION =
  "loopx_continuous_monitor_proposal_v0";

const RESULT_FIELDS = new Set([
  "schema_version",
  "invocation_id",
  "status",
  "observations",
  "domain_state_mutations",
  "domain_transition_receipts",
  "transition_proposals",
  "effect_receipt",
  "follow_up",
]);

const EFFECT_RECEIPT_FIELDS = new Set([
  "schema_version",
  "invocation_id",
  "idempotency_key",
  "status",
  "external_ref",
  "evidence_digest",
]);

const TRANSITION_CONTRACT_FIELDS = new Set([
  "proposal_kinds",
  "monitor_key_prefixes",
  "monitor_action_kinds",
  "monitor_target_key_prefixes",
  "monitor_required_capabilities",
]);
const MONITOR_UPSERT_FIELDS = new Set([
  "schema_version",
  "proposal_id",
  "kind",
  "monitor_key",
  "text",
  "action_kind",
  "target_key",
  "cadence",
  "next_due_at",
  "expires_at",
  "required_capabilities",
]);
const MONITOR_COMPLETE_FIELDS = new Set([
  "schema_version",
  "proposal_id",
  "kind",
  "monitor_key",
  "evidence",
]);
const TRANSITION_PROPOSAL_KINDS = [
  "continuous_monitor_upsert",
  "continuous_monitor_complete",
] as const;
type TransitionProposalKind = typeof TRANSITION_PROPOSAL_KINDS[number];
type ValidatedTransitionProposal =
  | (JsonObject & {
    kind: "continuous_monitor_upsert";
    proposal_id: string;
    monitor_key: string;
    required_capabilities: string[];
  })
  | (JsonObject & {
    kind: "continuous_monitor_complete";
    proposal_id: string;
    monitor_key: string;
  });
const PROPOSAL_ID_RE = /^[a-z][a-z0-9_.:-]{2,95}$/;
const MONITOR_KEY_RE = /^[a-z][a-z0-9_.-]{0,31}:[a-z][a-z0-9_.:-]{2,95}$/;
const ACTION_KIND_RE = /^[a-z][a-z0-9_]{0,63}$/;

function requiredObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EffectRuntimeRequestError(`${label} must be an object`);
  }
  return { ...(value as JsonObject) };
}

function boundedArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value) || value.length > 64) {
    throw new EffectRuntimeRequestError(`${label} must be an array with at most 64 items`);
  }
  return [...value];
}

function boundedString(value: unknown, label: string, limit: number): string {
  const result = requiredString(value, label);
  if (result.length > limit || result.includes("\n") || result.includes("\r")) {
    throw new EffectRuntimeRequestError(`${label} must be bounded single-line text`);
  }
  return result;
}

function boundedStringArray(
  value: unknown,
  label: string,
  limit: number,
): string[] {
  const result = boundedArray(value, label);
  if (
    result.length > limit ||
    result.some((item) => typeof item !== "string" || item.length === 0)
  ) {
    throw new EffectRuntimeRequestError(`${label} must contain bounded non-empty strings`);
  }
  return result as string[];
}

function requireExactFields(
  value: JsonObject,
  expected: ReadonlySet<string>,
  label: string,
): void {
  const actual = Object.keys(value);
  if (
    actual.length !== expected.size ||
    actual.some((field) => !expected.has(field))
  ) {
    throw new EffectRuntimeRequestError(`${label} fields are invalid`);
  }
}

function externalEffectReceipt(
  value: unknown,
  invocationId: string,
  effectId: string,
): JsonObject {
  const receipt = requiredObject(value, "external capability effect_receipt");
  requireExactFields(
    receipt,
    EFFECT_RECEIPT_FIELDS,
    "external capability effect_receipt",
  );
  if (receipt.schema_version !== EXTERNAL_EFFECT_RECEIPT_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError("external capability effect_receipt schema is invalid");
  }
  if (receipt.invocation_id !== invocationId) {
    throw new EffectRuntimeRequestError("external capability effect_receipt invocation_id is invalid");
  }
  if (receipt.idempotency_key !== effectId) {
    throw new EffectRuntimeRequestError(
      "external capability effect_receipt idempotency_key is invalid",
    );
  }
  if (receipt.status !== "committed" && receipt.status !== "no_change") {
    throw new EffectRuntimeRequestError("external capability effect_receipt status is invalid");
  }
  requiredString(
    receipt.external_ref,
    "external capability effect_receipt external_ref",
  );
  requiredString(
    receipt.evidence_digest,
    "external capability effect_receipt evidence_digest",
  );
  return receipt;
}

function validateTransitionProposals(input: {
  value: unknown;
  status: string;
  transition_contract: unknown;
}): ValidatedTransitionProposal[] {
  const proposals = boundedArray(
    input.value,
    "external capability result transition_proposals",
  );
  if (proposals.length === 0) {
    return [];
  }
  const contract = requiredObject(
    input.transition_contract,
    "governed capability transition_contract",
  );
  requireExactFields(
    contract,
    TRANSITION_CONTRACT_FIELDS,
    "governed capability transition_contract",
  );
  const allowedKinds = boundedStringArray(
    contract.proposal_kinds,
    "governed capability transition_contract proposal_kinds",
    8,
  );
  const allowedActions = boundedStringArray(
    contract.monitor_action_kinds,
    "governed capability transition_contract monitor_action_kinds",
    32,
  );
  const allowedMonitorKeyPrefixes = boundedStringArray(
    contract.monitor_key_prefixes,
    "governed capability transition_contract monitor_key_prefixes",
    32,
  );
  const allowedTargetPrefixes = boundedStringArray(
    contract.monitor_target_key_prefixes,
    "governed capability transition_contract monitor_target_key_prefixes",
    32,
  );
  const allowedCapabilities = boundedStringArray(
    contract.monitor_required_capabilities,
    "governed capability transition_contract monitor_required_capabilities",
    32,
  );
  const seenProposalIds = new Set<string>();
  return proposals.map((raw, index) => {
    const label = `external capability transition_proposals[${index}]`;
    const proposal = requiredObject(raw, label);
    const kind: TransitionProposalKind = requireStringLiteral(
      proposal.kind,
      TRANSITION_PROPOSAL_KINDS,
      `${label} kind`,
      `${label} kind is unsupported`,
    );
    if (!allowedKinds.includes(kind)) {
      throw new EffectRuntimeRequestError(`${label} kind is not admitted by transition_contract`);
    }
    if (input.status === "running" && kind !== "continuous_monitor_upsert") {
      throw new EffectRuntimeRequestError(`${label} running result may only upsert a monitor`);
    }
    if (proposal.schema_version !== CONTINUOUS_MONITOR_PROPOSAL_SCHEMA_VERSION) {
      throw new EffectRuntimeRequestError(`${label} schema_version is invalid`);
    }
    const proposalId = boundedString(
      proposal.proposal_id,
      `${label} proposal_id`,
      96,
    );
    if (!PROPOSAL_ID_RE.test(proposalId) || seenProposalIds.has(proposalId)) {
      throw new EffectRuntimeRequestError(`${label} proposal_id is invalid or duplicated`);
    }
    seenProposalIds.add(proposalId);
    const monitorKey = boundedString(
      proposal.monitor_key,
      `${label} monitor_key`,
      128,
    );
    if (!MONITOR_KEY_RE.test(monitorKey)) {
      throw new EffectRuntimeRequestError(`${label} monitor_key is invalid`);
    }
    if (!allowedMonitorKeyPrefixes.some((prefix) => monitorKey.startsWith(prefix))) {
      throw new EffectRuntimeRequestError(`${label} monitor_key is not admitted`);
    }
    switch (kind) {
      case "continuous_monitor_upsert": {
        requireExactFields(proposal, MONITOR_UPSERT_FIELDS, label);
        const actionKind = boundedString(
          proposal.action_kind,
          `${label} action_kind`,
          64,
        );
        if (!ACTION_KIND_RE.test(actionKind) || !allowedActions.includes(actionKind)) {
          throw new EffectRuntimeRequestError(`${label} action_kind is not admitted`);
        }
        const targetKey = boundedString(
          proposal.target_key,
          `${label} target_key`,
          128,
        );
        if (!allowedTargetPrefixes.some((prefix) => targetKey.startsWith(prefix))) {
          throw new EffectRuntimeRequestError(`${label} target_key is not admitted`);
        }
        const requiredCapabilities = boundedStringArray(
          proposal.required_capabilities,
          `${label} required_capabilities`,
          16,
        );
        if (
          new Set(requiredCapabilities).size !== requiredCapabilities.length ||
          requiredCapabilities.some((capability) =>
            !ACTION_KIND_RE.test(capability) || !allowedCapabilities.includes(capability)
          )
        ) {
          throw new EffectRuntimeRequestError(`${label} required_capabilities are not admitted`);
        }
        return {
          ...proposal,
          kind,
          proposal_id: proposalId,
          monitor_key: monitorKey,
          text: boundedString(proposal.text, `${label} text`, 240),
          action_kind: actionKind,
          target_key: targetKey,
          cadence: boundedString(proposal.cadence, `${label} cadence`, 32),
          next_due_at: boundedString(
            proposal.next_due_at,
            `${label} next_due_at`,
            64,
          ),
          expires_at: boundedString(
            proposal.expires_at,
            `${label} expires_at`,
            64,
          ),
          required_capabilities: requiredCapabilities,
        };
      }
      case "continuous_monitor_complete":
        requireExactFields(proposal, MONITOR_COMPLETE_FIELDS, label);
        return {
          ...proposal,
          kind,
          proposal_id: proposalId,
          monitor_key: monitorKey,
          evidence: boundedString(proposal.evidence, `${label} evidence`, 240),
        };
      default:
        return assertNever(kind, `${label} kind dispatch is incomplete`);
    }
  });
}

export function validateGovernedCapabilityAdmission(input: {
  admission: unknown;
  todo_id: string;
  todo_contract: unknown;
}): JsonObject {
  const admission = requiredObject(
    input.admission,
    "governed capability admission",
  );
  const selectedTodo = requiredObject(
    admission.selected_todo,
    "governed capability selected_todo",
  );
  if (selectedTodo.todo_id !== input.todo_id) {
    throw new EffectRuntimeRequestError(
      "governed capability selected_todo does not match the settlement Todo",
    );
  }
  if (selectedTodo.role !== "agent" || selectedTodo.status !== "open") {
    throw new EffectRuntimeRequestError(
      "governed capability selected_todo must be an open agent Todo",
    );
  }
  const todoContract = requiredObject(
    input.todo_contract,
    "governed capability todo_contract",
  );
  requireExactFields(
    todoContract,
    new Set(["action_kinds", "target_key_prefixes"]),
    "governed capability todo_contract",
  );
  const actionKinds = boundedArray(
    todoContract.action_kinds,
    "governed capability todo_contract action_kinds",
  );
  const targetKeyPrefixes = boundedArray(
    todoContract.target_key_prefixes,
    "governed capability todo_contract target_key_prefixes",
  );
  if (
    actionKinds.length === 0 ||
    actionKinds.some((value) => typeof value !== "string") ||
    !actionKinds.includes(selectedTodo.action_kind)
  ) {
    throw new EffectRuntimeRequestError(
      "governed capability operation is not authorized by selected_todo action_kind",
    );
  }
  const targetKey = requiredString(
    selectedTodo.target_key,
    "governed capability selected_todo target_key",
  );
  if (
    targetKeyPrefixes.length === 0 ||
    targetKeyPrefixes.some((value) => typeof value !== "string") ||
    !targetKeyPrefixes.some((prefix) => targetKey.startsWith(prefix as string))
  ) {
    throw new EffectRuntimeRequestError(
      "governed capability operation is not authorized by selected_todo target_key",
    );
  }
  return selectedTodo;
}

export function validateGovernedCapabilityResult(input: {
  value: unknown;
  invocation_id: string;
  effect_id: string;
  result_schema: string;
  effect_class: string;
  transition_contract?: unknown;
}): { result: JsonObject; journal_status: "running" | "ready_to_settle" } {
  if (input.effect_class !== "external_write") {
    throw new EffectRuntimeRequestError("governed capability execution requires external_write");
  }
  const result = requiredObject(input.value, "external capability result");
  requireExactFields(result, RESULT_FIELDS, "external capability result");
  if (result.schema_version !== input.result_schema) {
    throw new EffectRuntimeRequestError("external capability result schema_version is invalid");
  }
  if (result.invocation_id !== input.invocation_id) {
    throw new EffectRuntimeRequestError("external capability result invocation_id is invalid");
  }
  if (
    result.status !== "running" &&
    result.status !== "succeeded" &&
    result.status !== "no_change"
  ) {
    throw new EffectRuntimeRequestError("external capability result status is invalid");
  }
  for (const field of [
    "observations",
    "domain_state_mutations",
    "domain_transition_receipts",
  ]) {
    result[field] = boundedArray(result[field], `external capability result ${field}`);
  }
  result.transition_proposals = validateTransitionProposals({
    value: result.transition_proposals,
    status: result.status as string,
    transition_contract: input.transition_contract,
  });
  result.follow_up = requiredObject(
    result.follow_up,
    "external capability result follow_up",
  );
  if (result.status === "running") {
    if (result.effect_receipt !== null) {
      throw new EffectRuntimeRequestError(
        "running external capability cannot claim an effect receipt",
      );
    }
    for (const field of [
      "domain_state_mutations",
      "domain_transition_receipts",
    ]) {
      if ((result[field] as unknown[]).length > 0) {
        throw new EffectRuntimeRequestError(
          `running external capability must leave ${field} empty`,
        );
      }
    }
    return { result, journal_status: "running" };
  }
  const receipt = externalEffectReceipt(
    result.effect_receipt,
    input.invocation_id,
    input.effect_id,
  );
  if (result.status === "no_change") {
    if (receipt.status !== "no_change") {
      throw new EffectRuntimeRequestError(
        "no-change external capability requires a no-change effect receipt",
      );
    }
    for (const field of [
      "domain_state_mutations",
      "domain_transition_receipts",
      "transition_proposals",
    ]) {
      if ((result[field] as unknown[]).length > 0) {
        throw new EffectRuntimeRequestError(
          `no-change external capability must leave ${field} empty`,
        );
      }
    }
  } else if (receipt.status !== "committed") {
    throw new EffectRuntimeRequestError(
      "succeeded external capability requires a committed effect receipt",
    );
  }
  result.effect_receipt = receipt;
  return { result, journal_status: "ready_to_settle" };
}

export function validateGovernedCapabilitySettlementCallback(input: {
  payload: unknown;
  effect_id: string;
  effect_receipt_digest: string;
  require_receipt_digest: boolean;
}): JsonObject {
  const payload = requiredObject(
    input.payload,
    "governed capability settlement callback",
  );
  const identity = requiredObject(
    payload.settlement_identity,
    "governed capability settlement identity",
  );
  if (identity.effect_id !== input.effect_id) {
    return {
      ok: false,
      appended: false,
      reason: "settlement identity mismatch",
    };
  }
  if (
    input.require_receipt_digest &&
    payload.effect_receipt_digest !== input.effect_receipt_digest
  ) {
    return {
      ok: false,
      appended: false,
      reason: "effect receipt was not written back",
    };
  }
  return payload;
}

export function governedCapabilitySettlementStatus(
  failure: unknown,
): "settlement_failed" | "committed" {
  return failure === null ? "committed" : "settlement_failed";
}

import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import { basename, isAbsolute, join } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  appendJsonLine,
  atomicWriteJson,
  atomicWriteText,
  withFileMutationLock,
} from "../effect_runtime_io.ts";
import {
  jsonObject,
  optionalNonEmptyString as optionalString,
  requireBoolean as requiredBoolean,
  requireInteger as requiredInteger,
  requireJsonObject as requiredObject,
  requireNonEmptyString as requiredString,
  requireStringLiteral,
} from "../runtime_decode.ts";

export const QUOTA_SPEND_COMMIT_REQUEST_SCHEMA =
  "loopx_quota_spend_commit_request_v0";
export const QUOTA_SPEND_COMMIT_RESULT_SCHEMA =
  "loopx_quota_spend_commit_result_v0";
export const QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA =
  "quota_spend_commit_receipt_v0";
export const QUOTA_SLOT_SPENT_CLASSIFICATION = "quota_slot_spent";

export const QUOTA_SPEND_SOURCES = [
  "heartbeat",
  "controller",
  "adapter",
  "visible-goal",
] as const;
export type QuotaSpendSource = (typeof QUOTA_SPEND_SOURCES)[number];

const SELF_REPAIR_SPEND_ACTIONS = new Set([
  "control_plane_health_repair",
  "control_plane_projection_repair",
  "state_projection_gap_repair",
  "boundary_projection_repair",
  "todo_decision_scope_projection_repair",
]);

type QuotaSpendCommitStatus =
  | "preview"
  | "written"
  | "replayed"
  | "repaired"
  | "conflict";

interface CompactQuotaDecision extends JsonObject {
  should_run: boolean;
  normal_delivery_allowed: boolean;
  recovery_delivery_allowed: boolean;
  effective_action: string | null;
  self_repair_allowed: boolean;
  capability_repair_allowed: boolean;
  workspace_repair_allowed: boolean;
  state: string;
  safe_bypass_allowed: boolean;
  safe_bypass_kind: string | null;
  blocked_action_scope: string | null;
  compute: unknown;
  window_hours: unknown;
  slot_minutes: unknown;
  spent_slots: number;
  allowed_slots: unknown;
}

interface QuotaSpendCommitRequest {
  schema_version: typeof QUOTA_SPEND_COMMIT_REQUEST_SCHEMA;
  effect_id: string;
  runtime_root: string | null;
  goal_id: string;
  source: QuotaSpendSource;
  generated_at: string;
  execute: boolean;
  expected_index_digest: string | null;
  preview: JsonObject;
  before: CompactQuotaDecision;
  after: CompactQuotaDecision;
  resolved_agent_id: string | null;
}

interface QuotaSpendReplayRequest {
  schema_version: typeof QUOTA_SPEND_COMMIT_REQUEST_SCHEMA;
  operation: "replay";
  runtime_root: string;
  goal_id: string;
  effect_id: string;
  resolved_agent_id: string | null;
  read_only: boolean;
}

type SpendDisposition =
  | "delivery_completion"
  | "eligible"
  | "outcome_floor_recovery"
  | "control_plane_self_repair"
  | "capability_repair"
  | "safe_bypass";

interface QuotaSpendCommitReceipt extends JsonObject {
  schema_version: typeof QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA;
  effect_id: string;
  request_digest: string;
  status: "prepared" | "committed";
  json_path: string;
  markdown_path: string;
  index_path: string;
  expected_index_digest: string | null;
  expected_index_bytes: number;
  record: JsonObject;
  index_record: JsonObject;
  markdown: string;
  payload: JsonObject;
}

export interface QuotaSpendCommitResult extends JsonObject {
  schema_version: typeof QUOTA_SPEND_COMMIT_RESULT_SCHEMA;
  effect_id: string;
  status: QuotaSpendCommitStatus;
  written: boolean;
  replayed: boolean;
  repaired: boolean;
  conflict: boolean;
  request_digest: string;
  index_digest: string | null;
  reason: string;
  record: JsonObject | null;
  payload: JsonObject;
  reason_code?: string;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  const object = jsonObject(value);
  if (!object) return value;
  return Object.fromEntries(
    Object.entries(object)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, stableValue(child)]),
  );
}

function canonicalJson(value: unknown): string {
  return JSON.stringify(stableValue(value));
}

function sha256(value: string): string {
  return `sha256:${createHash("sha256").update(value, "utf8").digest("hex")}`;
}

function sha256Bytes(value: Uint8Array): string {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function safeGoalId(value: unknown): string {
  const goalId = requiredString(value, "goal_id").trim();
  if (goalId === "." || goalId === ".." || goalId.includes("/") || goalId.includes("\\")) {
    throw new EffectRuntimeRequestError("goal_id must be a single path segment");
  }
  if (basename(goalId) !== goalId) {
    throw new EffectRuntimeRequestError("goal_id must not include path traversal");
  }
  return goalId;
}

function optionalInteger(value: unknown, label: string): number | null {
  if (value === null || value === undefined) return null;
  return requiredInteger(value, label);
}

function compactDecision(value: unknown, label: string): CompactQuotaDecision {
  const decision = requiredObject(value, label);
  return {
    should_run: requiredBoolean(decision.should_run, `${label}.should_run`),
    normal_delivery_allowed: requiredBoolean(
      decision.normal_delivery_allowed,
      `${label}.normal_delivery_allowed`,
    ),
    recovery_delivery_allowed: requiredBoolean(
      decision.recovery_delivery_allowed,
      `${label}.recovery_delivery_allowed`,
    ),
    effective_action: optionalString(
      decision.effective_action,
      `${label}.effective_action`,
    ),
    self_repair_allowed: requiredBoolean(
      decision.self_repair_allowed,
      `${label}.self_repair_allowed`,
    ),
    capability_repair_allowed: requiredBoolean(
      decision.capability_repair_allowed,
      `${label}.capability_repair_allowed`,
    ),
    workspace_repair_allowed: requiredBoolean(
      decision.workspace_repair_allowed,
      `${label}.workspace_repair_allowed`,
    ),
    state: typeof decision.state === "string" ? decision.state : "",
    safe_bypass_allowed: requiredBoolean(
      decision.safe_bypass_allowed,
      `${label}.safe_bypass_allowed`,
    ),
    safe_bypass_kind: optionalString(
      decision.safe_bypass_kind,
      `${label}.safe_bypass_kind`,
    ),
    blocked_action_scope: optionalString(
      decision.blocked_action_scope,
      `${label}.blocked_action_scope`,
    ),
    compute: decision.compute ?? null,
    window_hours: decision.window_hours ?? null,
    slot_minutes: decision.slot_minutes ?? null,
    spent_slots: optionalInteger(decision.spent_slots, `${label}.spent_slots`) ?? 0,
    allowed_slots: decision.allowed_slots ?? null,
  };
}

function replayRequestObject(value: unknown): QuotaSpendReplayRequest {
  const request = requiredObject(value, "quota.spend.commit replay params");
  if (request.schema_version !== QUOTA_SPEND_COMMIT_REQUEST_SCHEMA) {
    throw new EffectRuntimeRequestError("Quota spend commit request schema mismatch");
  }
  if (request.operation !== "replay") {
    throw new EffectRuntimeRequestError("quota spend replay operation is invalid");
  }
  const runtimeRoot = requiredString(request.runtime_root, "runtime_root").trim();
  if (!isAbsolute(runtimeRoot)) {
    throw new EffectRuntimeRequestError("runtime_root must be absolute");
  }
  return {
    schema_version: QUOTA_SPEND_COMMIT_REQUEST_SCHEMA,
    operation: "replay",
    runtime_root: runtimeRoot,
    goal_id: safeGoalId(request.goal_id),
    effect_id: requiredString(request.effect_id, "effect_id").trim(),
    resolved_agent_id: optionalString(
      request.resolved_agent_id,
      "resolved_agent_id",
    )?.trim() ?? null,
    read_only: request.read_only === undefined
      ? false
      : requiredBoolean(request.read_only, "read_only"),
  };
}

function requestObject(value: unknown): QuotaSpendCommitRequest {
  const request = requiredObject(value, "quota.spend.commit params");
  if (request.schema_version !== QUOTA_SPEND_COMMIT_REQUEST_SCHEMA) {
    throw new EffectRuntimeRequestError("Quota spend commit request schema mismatch");
  }
  const execute = requiredBoolean(request.execute, "execute");
  const runtimeRoot = optionalString(request.runtime_root, "runtime_root")?.trim() ?? null;
  if (execute && !runtimeRoot) {
    throw new EffectRuntimeRequestError("executing quota spend commit requires runtime_root");
  }
  const preview = requiredObject(request.preview, "preview");
  const before = compactDecision(request.before, "before");
  const after = compactDecision(request.after, "after");
  const goalId = safeGoalId(request.goal_id);
  const source = requireStringLiteral(
    request.source,
    QUOTA_SPEND_SOURCES,
    "source",
    `quota slot spend source must be one of: ${QUOTA_SPEND_SOURCES.join(", ")}`,
  );
  const requestedEffectId = optionalString(request.effect_id, "effect_id")?.trim();
  return {
    schema_version: QUOTA_SPEND_COMMIT_REQUEST_SCHEMA,
    effect_id: requestedEffectId || derivedEffectId(
      preview,
      goalId,
      source,
      before,
      after,
    ),
    runtime_root: runtimeRoot,
    goal_id: goalId,
    source,
    generated_at: requiredString(request.generated_at, "generated_at").trim(),
    execute,
    expected_index_digest: optionalString(
      request.expected_index_digest,
      "expected_index_digest",
    ),
    preview,
    before,
    after,
    resolved_agent_id: optionalString(
      request.resolved_agent_id,
      "resolved_agent_id",
    )?.trim() ?? null,
  };
}

function derivedEffectId(
  preview: JsonObject,
  goalId: string,
  source: QuotaSpendSource,
  before: CompactQuotaDecision,
  after: CompactQuotaDecision,
): string {
  const effectRef = optionalString(preview.effect_ref, "preview.effect_ref")?.trim();
  if (effectRef) return effectRef;
  const identity = jsonObject(preview.settlement_identity);
  const settlementEffectId = identity
    ? optionalString(identity.effect_id, "preview.settlement_identity.effect_id")?.trim()
    : null;
  if (settlementEffectId) return `${settlementEffectId}#quota_spend`;
  const digest = sha256(canonicalJson({
    goal_id: goalId,
    agent_id: preview.agent_id ?? null,
    todo_id: preview.todo_id ?? null,
    replan_obligation_id: preview.replan_obligation_id ?? null,
    turn_instance_id: preview.turn_instance_id ?? null,
    source,
    slots: preview.slots,
    before,
    after,
    delivery_completion_spend: preview.delivery_completion_spend === true,
    delivery_run_generated_at: preview.delivery_run_generated_at ?? null,
    delivery_run_classification: preview.delivery_run_classification ?? null,
  }));
  return `quota-spend:${digest.slice("sha256:".length)}`;
}

function requestDigest(request: QuotaSpendCommitRequest): string {
  return sha256(canonicalJson({
    schema_version: request.schema_version,
    effect_id: request.effect_id,
    runtime_root: request.runtime_root,
    goal_id: request.goal_id,
    source: request.source,
    // generated_at, execute, and the CAS observation are transport facts.
    // A retry of the same semantic effect may observe a later clock/index
    // after a response loss; the prepared receipt must remain repairable.
    preview: request.preview,
    before: request.before,
    after: request.after,
    resolved_agent_id: request.resolved_agent_id,
  }));
}

function positiveSlots(preview: JsonObject): number {
  const value = preview.slots;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw new EffectRuntimeRequestError("preview.slots must be a positive integer");
  }
  return value;
}

function spendDisposition(request: QuotaSpendCommitRequest): SpendDisposition {
  if (request.preview.ok !== true) {
    throw new EffectRuntimeRequestError(
      typeof request.preview.reason === "string"
        ? request.preview.reason
        : "quota slot spend requires an eligible preview",
    );
  }
  const slots = positiveSlots(request.preview);
  if (request.after.spent_slots !== request.before.spent_slots + slots) {
    throw new EffectRuntimeRequestError(
      "after.spent_slots must equal before.spent_slots + slots",
    );
  }
  const action = request.before.effective_action;
  const deliveryCompletionSpend = request.preview.delivery_completion_spend === true;
  const selfRepairSpend = request.before.should_run &&
    action !== null && SELF_REPAIR_SPEND_ACTIONS.has(action) &&
    request.before.self_repair_allowed;
  const capabilityRepairSpend = request.before.should_run &&
    action === "capability_bridge_repair" &&
    request.before.capability_repair_allowed;
  const eligibleSpend = request.before.should_run &&
    request.before.state === "eligible" &&
    action !== "external_evidence_observe" &&
    !selfRepairSpend && !capabilityRepairSpend &&
    !request.before.workspace_repair_allowed && !deliveryCompletionSpend;
  const safeBypassSpend = request.preview.safe_bypass_spend === true &&
    (
      request.before.state === "operator_gate" ||
      request.before.recovery_delivery_allowed ||
      action === "outcome_floor_recovery"
    ) && request.before.safe_bypass_allowed;
  // A recovered settlement describes work that already happened. The current
  // frontier may now ask for capability or control-plane repair, but that later
  // projection cannot rewrite the attribution of the completed delivery.
  if (deliveryCompletionSpend) return "delivery_completion";
  if (eligibleSpend) return "eligible";
  if (safeBypassSpend && action === "outcome_floor_recovery") {
    return "outcome_floor_recovery";
  }
  if (selfRepairSpend) return "control_plane_self_repair";
  if (capabilityRepairSpend) return "capability_repair";
  if (safeBypassSpend) return "safe_bypass";
  throw new EffectRuntimeRequestError(
    "quota slot spend requires an eligible, safe-bypass, control-plane self-repair, " +
      "capability bridge repair, or latest validated delivery-completion quota should-run decision",
  );
}

function reasonSummary(
  request: QuotaSpendCommitRequest,
  disposition: SpendDisposition,
  slots: number,
): string {
  switch (disposition) {
    case "eligible":
      return `${slots} automatic agent slot(s) completed under an eligible quota guard`;
    case "outcome_floor_recovery":
      return `${slots} automatic agent slot(s) completed as outcome-floor recovery safe-bypass work`;
    case "control_plane_self_repair":
      return `${slots} automatic agent slot(s) completed as control-plane self-repair work`;
    case "capability_repair":
      return `${slots} automatic agent slot(s) completed as capability bridge repair work`;
    case "delivery_completion":
      return `${slots} automatic agent slot(s) accounted after validated delivery ${optionalString(request.preview.delivery_run_classification, "preview.delivery_run_classification") ?? ""}`;
    case "safe_bypass":
      return `${slots} automatic agent slot(s) completed as safe-bypass work`;
  }
}

function healthCheck(
  disposition: SpendDisposition,
): string {
  switch (disposition) {
    case "eligible":
      return "quota should-run eligible; quota slot spend event public-safe";
    case "outcome_floor_recovery":
      return "quota outcome-floor recovery safe-bypass; quota slot spend event public-safe";
    case "control_plane_self_repair":
      return "quota control-plane self-repair; quota slot spend event public-safe";
    case "capability_repair":
      return "quota capability bridge repair; quota slot spend event public-safe";
    case "delivery_completion":
      return "quota validated delivery completion; quota slot spend event public-safe";
    case "safe_bypass":
      return "quota safe-bypass delivery; quota slot spend event public-safe";
  }
}

function buildSpendRecord(
  request: QuotaSpendCommitRequest,
  fingerprint: string,
): JsonObject {
  const disposition = spendDisposition(request);
  const slots = positiveSlots(request.preview);
  const deliveryAction = typeof request.preview.delivery_run_recommended_action === "string"
    ? request.preview.delivery_run_recommended_action.trim()
    : "";
  const recommendedAction = disposition === "delivery_completion" && deliveryAction
    ? deliveryAction
    : typeof request.preview.after_recommended_action === "string"
    ? request.preview.after_recommended_action
    : "inspect next quota should-run decision";
  const quotaEvent: JsonObject = {
    event_type: QUOTA_SLOT_SPENT_CLASSIFICATION,
    source: request.source,
    todo_id: request.preview.todo_id ?? null,
    replan_obligation_id: request.preview.replan_obligation_id ?? null,
    turn_instance_id: request.preview.turn_instance_id ?? null,
    settlement_identity: request.preview.settlement_identity ?? null,
    effect_ref: request.preview.effect_ref ?? null,
    slots,
    reason_summary: reasonSummary(request, disposition, slots),
    delivery_run_generated_at: request.preview.delivery_run_generated_at ?? null,
    delivery_run_classification: request.preview.delivery_run_classification ?? null,
    delivery_run_agent_id: request.preview.delivery_run_agent_id ?? null,
    delivery_run_recommended_action: deliveryAction || null,
    delivery_workspace: request.preview.delivery_workspace ?? null,
    delivery_workspace_causality: request.preview.delivery_workspace_causality ?? null,
    delivery_workspace_validated: request.preview.delivery_workspace_validated === true,
    before: request.before,
    after: request.after,
  };
  const commit = {
    schema_version: QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA,
    effect_id: request.effect_id,
    request_digest: fingerprint,
  } satisfies JsonObject;
  const record: JsonObject = {
    generated_at: request.generated_at,
    goal_id: request.goal_id,
    classification: QUOTA_SLOT_SPENT_CLASSIFICATION,
    recommended_action: recommendedAction,
    health_check: healthCheck(disposition),
    quota_event: quotaEvent,
    quota_spend_commit: commit,
  };
  if (request.resolved_agent_id) {
    record.agent_id = request.resolved_agent_id;
    quotaEvent.agent_id = request.resolved_agent_id;
  }
  const effectRef = optionalString(request.preview.effect_ref, "preview.effect_ref");
  if (effectRef) record.effect_ref = effectRef;
  const turnInstanceId = optionalString(
    request.preview.turn_instance_id,
    "preview.turn_instance_id",
  );
  if (turnInstanceId) {
    record.turn_instance_id = turnInstanceId;
    const todoId = optionalString(request.preview.todo_id, "preview.todo_id");
    const replanId = optionalString(
      request.preview.replan_obligation_id,
      "preview.replan_obligation_id",
    );
    if (todoId) record.todo_id = todoId;
    if (replanId) record.replan_obligation_id = replanId;
    const identity = jsonObject(request.preview.settlement_identity);
    if (identity) record.settlement_identity = identity;
  }
  return record;
}

function runStem(generatedAt: string): string {
  const stem = generatedAt.replace(/[^0-9A-Za-z-]+/g, "-").replace(/^-+|-+$/g, "");
  if (!stem) throw new EffectRuntimeRequestError("generated_at cannot form a run artifact name");
  return stem;
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path);
    return true;
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) return false;
    throw error;
  }
}

function isNodeErrorCode(error: unknown, code: string): boolean {
  return error instanceof Error && "code" in error && error.code === code;
}

async function nextArtifactPaths(
  runsDir: string,
  generatedAt: string,
  effectId: string,
): Promise<{ jsonPath: string; markdownPath: string }> {
  const effectDigest = sha256(effectId).slice(
    "sha256:".length,
    "sha256:".length + 24,
  );
  const base = `${runStem(generatedAt)}-quota-slot-spent-${effectDigest}`;
  for (let index = 1; ; index += 1) {
    const stem = index === 1 ? base : `${base}-${index}`;
    const jsonPath = join(runsDir, `${stem}.json`);
    const markdownPath = join(runsDir, `${stem}.md`);
    if (!await pathExists(jsonPath) && !await pathExists(markdownPath)) {
      return { jsonPath, markdownPath };
    }
  }
}

function transactionPath(runsDir: string, effectId: string): string {
  const digest = sha256(effectId).slice("sha256:".length, "sha256:".length + 24);
  return join(runsDir, ".transactions", "quota-spend", `${digest}.json`);
}

async function readOptionalText(path: string): Promise<string | null> {
  try {
    return await readFile(path, "utf8");
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) return null;
    throw error;
  }
}

async function readOptionalBytes(path: string): Promise<Buffer | null> {
  try {
    return await readFile(path);
  } catch (error) {
    if (isNodeErrorCode(error, "ENOENT")) return null;
    throw error;
  }
}

export async function quotaSpendIndexDigest(indexPath: string): Promise<string | null> {
  const content = await readOptionalBytes(indexPath);
  return content === null ? null : sha256Bytes(content);
}

function indexRecords(content: string | null): JsonObject[] {
  if (content === null) return [];
  const records: JsonObject[] = [];
  for (const [index, line] of content.split(/\r?\n/).entries()) {
    if (!line.trim()) continue;
    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch {
      throw new EffectRuntimeRequestError(
        `quota run index line ${index + 1} is malformed`,
        "malformed_run_index",
      );
    }
    records.push(requiredObject(value, `quota run index line ${index + 1}`));
  }
  return records;
}

function repairedTruncatedTail(
  content: Buffer,
  expectedRecord: JsonObject,
  expectedIndexDigest: string | null,
  expectedIndexBytes: number,
): string | null {
  if (content.length <= expectedIndexBytes) return null;
  const validPrefix = content.subarray(0, expectedIndexBytes);
  const truncatedTail = content.subarray(expectedIndexBytes);
  const expectedLine = Buffer.from(`${JSON.stringify(expectedRecord)}\n`, "utf8");
  if (
    truncatedTail.length >= expectedLine.length ||
    !expectedLine.subarray(0, truncatedTail.length).equals(truncatedTail)
  ) {
    return null;
  }
  if (
    expectedIndexDigest === null
      ? validPrefix.length !== 0
      : sha256Bytes(validPrefix) !== expectedIndexDigest
  ) {
    return null;
  }
  const validPrefixText = validPrefix.toString("utf8");
  indexRecords(validPrefixText);
  return `${validPrefixText}${expectedLine.toString("utf8")}`;
}

type EffectIdentityResolution =
  | { kind: "absent" }
  | { kind: "matched"; record: JsonObject }
  | { kind: "conflict"; reason: string };

function effectIdentityValue(
  value: unknown,
): { value: string | null; malformed: boolean } {
  if (value === null || value === undefined || value === "") {
    return { value: null, malformed: false };
  }
  if (typeof value !== "string" || !value.trim()) {
    return { value: null, malformed: true };
  }
  return { value: value.trim(), malformed: false };
}

function resolveEffectIdentity(
  record: JsonObject,
  expectedEffectId: string,
): EffectIdentityResolution {
  const rawMetadata = record.quota_spend_commit;
  const recordEffect = effectIdentityValue(record.effect_ref);
  const recordReferencesExpected = recordEffect.value === expectedEffectId;
  const metadataPresent = rawMetadata !== undefined;
  const metadata = metadataPresent ? jsonObject(rawMetadata) : null;
  if (metadataPresent && metadata === null) {
    if (!recordReferencesExpected) return { kind: "absent" };
    return {
      kind: "conflict",
      reason: "quota spend index row has malformed effect metadata",
    };
  }
  const metadataEffect = effectIdentityValue(metadata?.effect_id);
  const referencesExpected = metadataEffect.value === expectedEffectId ||
    recordReferencesExpected;
  if (!referencesExpected) return { kind: "absent" };
  if (
    metadataEffect.malformed ||
    recordEffect.malformed ||
    (metadataPresent && metadataEffect.value === null)
  ) {
    return {
      kind: "conflict",
      reason: "quota spend index row has malformed effect identity",
    };
  }
  if (
    metadataEffect.value !== null &&
    recordEffect.value !== null &&
    metadataEffect.value !== recordEffect.value
  ) {
    return {
      kind: "conflict",
      reason: "quota spend index row has conflicting effect identities",
    };
  }
  return { kind: "matched", record };
}

function matchingIndexRecord(
  records: readonly JsonObject[],
  effectId: string,
): EffectIdentityResolution {
  for (const record of [...records].reverse()) {
    if (record.classification !== QUOTA_SLOT_SPENT_CLASSIFICATION) continue;
    const resolution = resolveEffectIdentity(record, effectId);
    if (resolution.kind !== "absent") return resolution;
  }
  return { kind: "absent" };
}

async function evaluateQuotaSpendReplay(
  value: unknown,
): Promise<QuotaSpendCommitResult> {
  const request = replayRequestObject(value);
  const indexPath = join(
    request.runtime_root,
    "goals",
    request.goal_id,
    "runs",
    "index.jsonl",
  );
  const evaluate = async (): Promise<QuotaSpendCommitResult> => {
    const content = await readOptionalText(indexPath);
    const candidateResolution = matchingIndexRecord(
      indexRecords(content),
      request.effect_id,
    );
    if (candidateResolution.kind === "conflict") {
      return {
        schema_version: QUOTA_SPEND_COMMIT_RESULT_SCHEMA,
        effect_id: request.effect_id,
        status: "conflict",
        written: false,
        replayed: false,
        repaired: false,
        conflict: true,
        request_digest: sha256(canonicalJson(value)),
        index_digest: await quotaSpendIndexDigest(indexPath),
        reason: candidateResolution.reason,
        record: null,
        payload: {
          ok: false,
          appended: false,
          replay_found: true,
          goal_id: request.goal_id,
          effect_ref: request.effect_id,
          reason: candidateResolution.reason,
        },
        reason_code: "effect_id_conflict",
      };
    }
    const candidate = candidateResolution.kind === "matched"
      ? candidateResolution.record
      : null;
    const basePayload: JsonObject = {
      ok: false,
      appended: false,
      replay_found: candidate !== null,
      goal_id: request.goal_id,
      effect_ref: request.effect_id,
    };
    if (candidate === null) {
      return {
        schema_version: QUOTA_SPEND_COMMIT_RESULT_SCHEMA,
        effect_id: request.effect_id,
        status: "preview",
        written: false,
        replayed: false,
        repaired: false,
        conflict: false,
        request_digest: sha256(canonicalJson(value)),
        index_digest: await quotaSpendIndexDigest(indexPath),
        reason: "quota spend replay was not found",
        record: null,
        payload: basePayload,
      };
    }
    const candidateGoalId = typeof candidate.goal_id === "string"
      ? candidate.goal_id.trim()
      : "";
    const candidateAgentId = typeof candidate.agent_id === "string"
      ? candidate.agent_id.trim()
      : "";
    if (
      candidateGoalId !== request.goal_id ||
      !request.resolved_agent_id ||
      candidateAgentId !== request.resolved_agent_id
    ) {
      return {
        schema_version: QUOTA_SPEND_COMMIT_RESULT_SCHEMA,
        effect_id: request.effect_id,
        status: "preview",
        written: false,
        replayed: false,
        repaired: false,
        conflict: false,
        request_digest: sha256(canonicalJson(value)),
        index_digest: await quotaSpendIndexDigest(indexPath),
        reason: "quota spend replay requires the same valid agent identity",
        record: null,
        payload: { ...basePayload, reason: "agent identity mismatch" },
      };
    }
    return {
      schema_version: QUOTA_SPEND_COMMIT_RESULT_SCHEMA,
      effect_id: request.effect_id,
      status: "replayed",
      written: false,
      replayed: true,
      repaired: false,
      conflict: false,
      request_digest: sha256(canonicalJson(value)),
      index_digest: await quotaSpendIndexDigest(indexPath),
      reason: "quota spend replayed for the same provider effect",
      record: candidate,
      payload: {
        ...candidate,
        ...basePayload,
        ok: true,
        idempotent_replay: true,
        agent_id: candidateAgentId,
        reason: "quota spend replayed for the same provider effect",
      },
    };
  };
  return request.read_only
    ? await evaluate()
    : await withFileMutationLock(indexPath, evaluate);
}

function indexRecordFor(
  request: QuotaSpendCommitRequest,
  record: JsonObject,
  jsonPath: string,
  markdownPath: string,
  fingerprint: string,
): JsonObject {
  const indexRecord: JsonObject = {
    generated_at: request.generated_at,
    goal_id: request.goal_id,
    classification: QUOTA_SLOT_SPENT_CLASSIFICATION,
    recommended_action: record.recommended_action,
    health_check: record.health_check,
    json_path: jsonPath,
    markdown_path: markdownPath,
    quota_spend_commit: {
      schema_version: QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA,
      effect_id: request.effect_id,
      request_digest: fingerprint,
    },
  };
  for (const field of [
    "agent_id",
    "effect_ref",
    "turn_instance_id",
    "todo_id",
    "replan_obligation_id",
    "settlement_identity",
  ]) {
    if (record[field] !== undefined && record[field] !== null && record[field] !== "") {
      indexRecord[field] = record[field];
    }
  }
  return indexRecord;
}

function pyValue(value: unknown): string {
  if (value === true) return "True";
  if (value === false) return "False";
  if (value === null || value === undefined) return "None";
  return String(value);
}

function markdownScalar(value: unknown): string {
  return pyValue(value).replace(/\r/g, " ").replace(/\n/g, " ").replace(/\|/g, "\\|").trim();
}

function quotaSpendMarkdown(payload: JsonObject): string {
  const before = jsonObject(payload.before) ?? {};
  const after = jsonObject(payload.after) ?? {};
  const beforeQuota = jsonObject(before.quota) ?? before;
  const afterQuota = jsonObject(after.quota) ?? after;
  const lines = [
    "# LoopX Quota Slot Preview",
    "",
    `- ok: \`${pyValue(payload.ok)}\``,
    `- dry_run: \`${pyValue(payload.dry_run)}\``,
    `- goal_id: \`${pyValue(payload.goal_id)}\``,
    `- classification: \`${pyValue(payload.classification ?? QUOTA_SLOT_SPENT_CLASSIFICATION)}\``,
    `- agent_id: \`${pyValue(payload.agent_id ?? "")}\``,
    `- slots: \`${pyValue(payload.slots)}\``,
    `- appended: \`${pyValue(payload.appended)}\``,
    `- registry_mutated: \`${pyValue(payload.registry_mutated)}\``,
    `- would_throttle: \`${pyValue(payload.would_throttle)}\``,
  ];
  if (payload.json_path) lines.push(`- json_path: \`${pyValue(payload.json_path)}\``);
  if (payload.index_path) lines.push(`- index_path: \`${pyValue(payload.index_path)}\``);
  if (payload.reason) lines.push(`- reason: ${pyValue(payload.reason)}`);
  if (Object.keys(before).length) {
    lines.push(
      `- before: state=${pyValue(before.state)} should_run=${pyValue(before.should_run)} ` +
        `slots=${pyValue(beforeQuota.spent_slots)}/${pyValue(beforeQuota.allowed_slots)}`,
    );
  }
  if (Object.keys(after).length) {
    lines.push(
      `- after: state=${pyValue(after.state)} should_run=${pyValue(after.should_run)} ` +
        `slots=${pyValue(afterQuota.spent_slots)}/${pyValue(afterQuota.allowed_slots)}`,
    );
    const summary = jsonObject(after.plan_summary);
    if (summary) {
      lines.push(
        `- after_plan_next_automatic_turn: ${pyValue(summary.next_automatic_turn ?? "none")}`,
      );
    }
  }
  if (payload.rolling_window_note) {
    lines.push(`- rolling_window_note: ${pyValue(payload.rolling_window_note)}`);
  }
  const operatorAction = jsonObject(payload.operator_action);
  if (operatorAction) {
    if (payload.error_code) lines.push(`- error_code: \`${pyValue(payload.error_code)}\``);
    if (payload.incident_channel) {
      lines.push(`- incident_channel: \`${pyValue(payload.incident_channel)}\``);
    }
    lines.push(
      "- operator_action: " +
        `action=${markdownScalar(operatorAction.action ?? "")} ` +
        `holder_pid=${markdownScalar(operatorAction.holder_pid ?? "") || "unknown"} ` +
        `retry_mode=${markdownScalar(operatorAction.retry_mode ?? "")}`,
    );
    if (Array.isArray(operatorAction.steps)) {
      for (const step of operatorAction.steps) lines.push(`  - ${markdownScalar(step)}`);
    }
  }
  return `${lines.join("\n")}\n`;
}

function payloadFor(
  request: QuotaSpendCommitRequest,
  record: JsonObject,
  jsonPath: string,
  markdownPath: string,
  indexPath: string,
  options: { appended: boolean; replayed: boolean; repaired: boolean },
): JsonObject {
  const event = requiredObject(record.quota_event, "record.quota_event");
  const payload: JsonObject = {
    ...request.preview,
    dry_run: !request.execute,
    appended: options.appended,
    registry_mutated: false,
    source: event.source,
    classification: QUOTA_SLOT_SPENT_CLASSIFICATION,
    generated_at: record.generated_at,
    agent_id: record.agent_id ?? null,
    quota_event: event,
    json_path: jsonPath,
    markdown_path: markdownPath,
    index_path: indexPath,
    effect_id: request.effect_id,
    idempotent_replay: options.replayed,
    transaction_repaired: options.repaired,
    reason: options.replayed
      ? "quota spend commit replayed for the same effect identity"
      : options.repaired
      ? "quota spend commit repaired its prepared durable transaction"
      : `${request.execute ? "appended" : "dry-run preview"} quota slot spend event: ` +
        `${request.goal_id} ${request.before.spent_slots}->${request.after.spent_slots} slots`,
  };
  if (request.execute) {
    payload.before = request.before;
    payload.after = request.after;
  }
  return payload;
}

function result(
  request: QuotaSpendCommitRequest,
  fingerprint: string,
  status: QuotaSpendCommitStatus,
  indexDigest: string | null,
  reason: string,
  record: JsonObject | null,
  payload: JsonObject,
  extra: Partial<QuotaSpendCommitResult> = {},
): QuotaSpendCommitResult {
  return {
    schema_version: QUOTA_SPEND_COMMIT_RESULT_SCHEMA,
    effect_id: request.effect_id,
    status,
    written: status === "written",
    replayed: status === "replayed",
    repaired: status === "repaired",
    conflict: status === "conflict",
    request_digest: fingerprint,
    index_digest: indexDigest,
    reason,
    record,
    payload,
    ...extra,
  };
}

function receiptObject(value: unknown): QuotaSpendCommitReceipt {
  const receipt = requiredObject(value, "quota spend transaction receipt");
  if (receipt.schema_version !== QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA) {
    throw new EffectRuntimeRequestError("Quota spend transaction receipt schema mismatch");
  }
  const status = requireStringLiteral(
    receipt.status,
    ["prepared", "committed"] as const,
    "receipt.status",
  );
  const expectedIndexBytes = requiredInteger(
    receipt.expected_index_bytes,
    "receipt.expected_index_bytes",
  );
  if (expectedIndexBytes < 0) {
    throw new EffectRuntimeRequestError("receipt.expected_index_bytes cannot be negative");
  }
  return {
    schema_version: QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA,
    effect_id: requiredString(receipt.effect_id, "receipt.effect_id"),
    request_digest: requiredString(receipt.request_digest, "receipt.request_digest"),
    status,
    json_path: requiredString(receipt.json_path, "receipt.json_path"),
    markdown_path: requiredString(receipt.markdown_path, "receipt.markdown_path"),
    index_path: requiredString(receipt.index_path, "receipt.index_path"),
    expected_index_digest: optionalString(
      receipt.expected_index_digest,
      "receipt.expected_index_digest",
    ),
    expected_index_bytes: expectedIndexBytes,
    record: requiredObject(receipt.record, "receipt.record"),
    index_record: requiredObject(receipt.index_record, "receipt.index_record"),
    markdown: requiredString(receipt.markdown, "receipt.markdown"),
    payload: requiredObject(receipt.payload, "receipt.payload"),
  };
}

async function readReceipt(path: string): Promise<QuotaSpendCommitReceipt | null> {
  const content = await readOptionalText(path);
  if (content === null) return null;
  let value: unknown;
  try {
    value = JSON.parse(content);
  } catch {
    throw new EffectRuntimeRequestError(
      "quota spend transaction receipt is malformed",
      "malformed_transaction_receipt",
    );
  }
  return receiptObject(value);
}

async function ensureJsonArtifact(
  path: string,
  expected: JsonObject,
): Promise<boolean> {
  const existing = await readOptionalText(path);
  if (existing === null) {
    await atomicWriteJson(path, expected);
    return true;
  }
  let actual: unknown;
  try {
    actual = JSON.parse(existing);
  } catch {
    throw new EffectRuntimeRequestError(
      "quota spend JSON artifact is malformed",
      "artifact_conflict",
    );
  }
  if (canonicalJson(actual) !== canonicalJson(expected)) {
    throw new EffectRuntimeRequestError(
      "quota spend JSON artifact conflicts with its transaction receipt",
      "artifact_conflict",
    );
  }
  return false;
}

async function ensureMarkdownArtifact(
  path: string,
  expected: string,
): Promise<boolean> {
  const existing = await readOptionalText(path);
  if (existing === null) {
    await atomicWriteText(path, expected);
    return true;
  }
  if (existing !== expected) {
    throw new EffectRuntimeRequestError(
      "quota spend Markdown artifact conflicts with its transaction receipt",
      "artifact_conflict",
    );
  }
  return false;
}

async function readReceiptIndex(
  receipt: QuotaSpendCommitReceipt,
): Promise<{ content: string | null; records: JsonObject[]; repaired: boolean }> {
  const indexBytes = await readOptionalBytes(receipt.index_path);
  let content = indexBytes === null ? null : indexBytes.toString("utf8");
  try {
    return { content, records: indexRecords(content), repaired: false };
  } catch (error) {
    const recovered = indexBytes === null
      ? null
      : repairedTruncatedTail(
        indexBytes,
        receipt.index_record,
        receipt.expected_index_digest,
        receipt.expected_index_bytes,
      );
    if (recovered === null) throw error;
    await atomicWriteText(receipt.index_path, recovered);
    content = recovered;
    return { content, records: indexRecords(content), repaired: true };
  }
}

async function ensureReceiptArtifacts(
  receipt: QuotaSpendCommitReceipt,
): Promise<boolean> {
  let repaired = false;
  repaired = await ensureJsonArtifact(receipt.json_path, receipt.record) || repaired;
  repaired = await ensureMarkdownArtifact(receipt.markdown_path, receipt.markdown) || repaired;
  const index = await readReceiptIndex(receipt);
  repaired = index.repaired || repaired;
  const matchResolution = matchingIndexRecord(index.records, receipt.effect_id);
  if (matchResolution.kind === "conflict") {
    throw new EffectRuntimeRequestError(
      matchResolution.reason,
      "effect_id_conflict",
    );
  }
  const match = matchResolution.kind === "matched"
    ? matchResolution.record
    : null;
  if (match) {
    const metadata = jsonObject(match.quota_spend_commit);
    if (metadata?.request_digest !== receipt.request_digest) {
      throw new EffectRuntimeRequestError(
        "quota spend effect identity is already bound to a different request",
        "effect_id_conflict",
      );
    }
  } else {
    const prefix = index.content ?? "";
    if (prefix && !prefix.endsWith("\n")) {
      await atomicWriteText(
        receipt.index_path,
        `${prefix}\n${JSON.stringify(receipt.index_record)}\n`,
      );
    } else {
      await appendJsonLine(receipt.index_path, receipt.index_record);
    }
    repaired = true;
  }
  return repaired;
}

export async function evaluateQuotaSpendCommit(
  value: unknown,
): Promise<QuotaSpendCommitResult> {
  const rawRequest = requiredObject(value, "quota.spend.commit params");
  if (rawRequest.operation === "replay") {
    return await evaluateQuotaSpendReplay(rawRequest);
  }
  const request = requestObject(value);
  const fingerprint = requestDigest(request);
  const record = buildSpendRecord(request, fingerprint);
  if (!request.runtime_root) {
    const payload = payloadFor(request, record, "", "", "", {
      appended: false,
      replayed: false,
      repaired: false,
    });
    return result(
      request,
      fingerprint,
      "preview",
      null,
      "quota spend event preview evaluated by TypeScript",
      record,
      payload,
    );
  }

  const runsDir = join(request.runtime_root, "goals", request.goal_id, "runs");
  const indexPath = join(runsDir, "index.jsonl");
  if (!request.execute) {
    const { jsonPath, markdownPath } = await nextArtifactPaths(
      runsDir,
      request.generated_at,
      request.effect_id,
    );
    const payload = payloadFor(
      request,
      record,
      jsonPath,
      markdownPath,
      indexPath,
      { appended: false, replayed: false, repaired: false },
    );
    return result(
      request,
      fingerprint,
      "preview",
      await quotaSpendIndexDigest(indexPath),
      "quota spend transaction preview evaluated by TypeScript",
      record,
      payload,
    );
  }

  return await withFileMutationLock(indexPath, async () => {
    const receiptPath = transactionPath(runsDir, request.effect_id);
    const existingReceipt = await readReceipt(receiptPath);
    if (existingReceipt) {
      if (
        existingReceipt.effect_id !== request.effect_id ||
        existingReceipt.request_digest !== fingerprint
      ) {
        const payload = { ...request.preview, ok: false, appended: false };
        return result(
          request,
          fingerprint,
          "conflict",
          await quotaSpendIndexDigest(indexPath),
          "quota spend effect identity is already bound to a different request",
          null,
          payload,
          { reason_code: "effect_id_conflict" },
        );
      }
      const repaired = await ensureReceiptArtifacts(existingReceipt);
      const committedReceipt = {
        ...existingReceipt,
        status: "committed",
      } satisfies QuotaSpendCommitReceipt;
      if (existingReceipt.status !== "committed" || repaired) {
        await atomicWriteJson(receiptPath, committedReceipt);
      }
      const replayPayload = {
        ...existingReceipt.payload,
        appended: repaired,
        idempotent_replay: !repaired,
        transaction_repaired: repaired,
        reason: repaired
          ? "quota spend commit repaired its prepared durable transaction"
          : "quota spend commit replayed for the same effect identity",
      };
      return result(
        request,
        fingerprint,
        repaired ? "repaired" : "replayed",
        await quotaSpendIndexDigest(indexPath),
        optionalString(replayPayload.reason, "replay payload reason") ?? "",
        existingReceipt.record,
        replayPayload,
      );
    }

    const currentIndexBytes = await readOptionalBytes(indexPath);
    const currentIndexContent = currentIndexBytes === null
      ? null
      : currentIndexBytes.toString("utf8");
    const currentDigest = currentIndexBytes === null
      ? null
      : sha256Bytes(currentIndexBytes);
    if (request.expected_index_digest !== currentDigest) {
      return result(
        request,
        fingerprint,
        "conflict",
        currentDigest,
        "quota run index compare-and-swap precondition failed",
        null,
        { ...request.preview, ok: false, appended: false },
        { reason_code: "index_digest_conflict" },
      );
    }
    const currentRecords = indexRecords(currentIndexContent);
    const duplicateResolution = matchingIndexRecord(currentRecords, request.effect_id);
    if (duplicateResolution.kind === "conflict") {
      return result(
        request,
        fingerprint,
        "conflict",
        currentDigest,
        duplicateResolution.reason,
        null,
        { ...request.preview, ok: false, appended: false },
        { reason_code: "effect_id_conflict" },
      );
    }
    if (duplicateResolution.kind === "matched") {
      return result(
        request,
        fingerprint,
        "conflict",
        currentDigest,
        "quota spend effect identity already exists without a matching transaction receipt",
        null,
        { ...request.preview, ok: false, appended: false },
        { reason_code: "effect_id_conflict" },
      );
    }

    const { jsonPath, markdownPath } = await nextArtifactPaths(
      runsDir,
      request.generated_at,
      request.effect_id,
    );
    const payload = payloadFor(
      request,
      record,
      jsonPath,
      markdownPath,
      indexPath,
      { appended: true, replayed: false, repaired: false },
    );
    const indexRecord = indexRecordFor(
      request,
      record,
      jsonPath,
      markdownPath,
      fingerprint,
    );
    const markdown = quotaSpendMarkdown(payload);
    const prepared = {
      schema_version: QUOTA_SPEND_COMMIT_RECEIPT_SCHEMA,
      effect_id: request.effect_id,
      request_digest: fingerprint,
      status: "prepared",
      json_path: jsonPath,
      markdown_path: markdownPath,
      index_path: indexPath,
      expected_index_digest: currentDigest,
      expected_index_bytes: currentIndexBytes?.length ?? 0,
      record,
      index_record: indexRecord,
      markdown,
      payload,
    } satisfies QuotaSpendCommitReceipt;
    await atomicWriteJson(receiptPath, prepared);
    await ensureReceiptArtifacts(prepared);
    await atomicWriteJson(receiptPath, { ...prepared, status: "committed" });
    return result(
      request,
      fingerprint,
      "written",
      await quotaSpendIndexDigest(indexPath),
      "quota spend transaction committed by TypeScript",
      record,
      payload,
    );
  });
}

import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  optionalNonEmptyString,
  requireInteger,
  requireJsonObject,
  requireNonEmptyString,
  requireStringArray,
} from "../runtime_decode.ts";

import type { JsonObject } from "../effect_program.ts";

export const PLANNING_HORIZON_SCHEMA_VERSION = "quota_planning_horizon_v0";
export const PLANNING_HORIZON_REQUEST_SCHEMA_VERSION =
  "quota_planning_horizon_request_v0";

const MAX_SOURCE_ITEMS = 32;
const MAX_PROJECTED_ITEMS = 5;
const MAX_PROJECTED_RELATIONS = 8;
const MAX_PROJECTED_ACCEPTANCE_GAPS = 2;
const ITEM_TEXT_LIMIT = 180;
const CONTEXT_TEXT_LIMIT = 140;
const ACCEPTANCE_TEXT_LIMIT = 220;
const TODO_ID = /^todo_[A-Za-z0-9_-]{3,80}$/;

type PlanningState =
  | "selected"
  | "runnable"
  | "waiting"
  | "blocked"
  | "scheduled"
  | "context";

interface HorizonCandidate extends JsonObject {
  todo_id: string;
  text: string;
  priority?: string;
  status?: string;
  task_class?: string;
  action_kind?: string;
  continuation_hint?: string;
  resume_when?: string;
  resume_ready?: boolean;
  next_due_at?: string;
  unblocks_todo_id?: string;
  successor_todo_ids: string[];
  superseded_by?: string;
  route_id?: string;
  route_key?: string;
  index?: number;
}

interface HorizonRelation extends JsonObject {
  from_todo_id: string;
  to_ref: string;
  relation: "successor" | "unblocks" | "resumes_when" | "superseded_by" | "routes_via";
  enforcement: "lineage_only" | "typed_lifecycle" | "typed_condition" | "read_only_context";
}

function todoId(value: unknown, label: string): string {
  const normalized = requireNonEmptyString(value, label);
  if (!TODO_ID.test(normalized)) {
    throw new EffectRuntimeRequestError(`${label} must be a public Todo id`);
  }
  return normalized;
}

function compactText(value: unknown, limit: number): { text: string; truncated: boolean } {
  const normalized = requireNonEmptyString(value, "planning horizon text")
    .trim()
    .replace(/\s+/g, " ");
  return {
    text: normalized.slice(0, limit),
    truncated: normalized.length > limit,
  };
}

function optionalTodoId(value: unknown, label: string): string | undefined {
  const normalized = optionalNonEmptyString(value, label);
  return normalized === null ? undefined : todoId(normalized, label);
}

function candidate(value: unknown, label: string): HorizonCandidate {
  const raw = requireJsonObject(value, label);
  const result: HorizonCandidate = {
    todo_id: todoId(raw.todo_id, `${label}.todo_id`),
    text: requireNonEmptyString(raw.text, `${label}.text`),
    successor_todo_ids: [],
  };
  for (const field of [
    "priority",
    "status",
    "task_class",
    "action_kind",
    "continuation_hint",
    "resume_when",
    "next_due_at",
    "route_id",
    "route_key",
  ] as const) {
    const normalized = optionalNonEmptyString(raw[field], `${label}.${field}`);
    if (normalized !== null) result[field] = normalized;
  }
  for (const field of ["unblocks_todo_id", "superseded_by"] as const) {
    const normalized = optionalTodoId(raw[field], `${label}.${field}`);
    if (normalized !== undefined) result[field] = normalized;
  }
  if (raw.successor_todo_ids !== null && raw.successor_todo_ids !== undefined) {
    result.successor_todo_ids = requireStringArray(
      raw.successor_todo_ids,
      `${label}.successor_todo_ids`,
    ).map((item, index) => todoId(item, `${label}.successor_todo_ids[${index}]`));
  }
  if (raw.resume_ready !== null && raw.resume_ready !== undefined) {
    if (typeof raw.resume_ready !== "boolean") {
      throw new EffectRuntimeRequestError(`${label}.resume_ready must be a boolean`);
    }
    result.resume_ready = raw.resume_ready;
  }
  if (raw.index !== null && raw.index !== undefined) {
    result.index = requireInteger(raw.index, `${label}.index`);
  }
  return result;
}

function priorityRank(value: unknown): number {
  const match = /^P(\d+)/i.exec(String(value ?? ""));
  return match ? Number(match[1]) : 1_000;
}

function planningState(
  item: HorizonCandidate,
  selectedTodoId: string,
  runnableTodoIds: ReadonlySet<string>,
): PlanningState {
  if (item.todo_id === selectedTodoId) return "selected";
  if (runnableTodoIds.has(item.todo_id)) return "runnable";
  if (item.status === "blocked") return "blocked";
  if (item.resume_when && item.resume_ready !== true) return "waiting";
  if (item.status === "deferred") return "waiting";
  if (item.task_class === "continuous_monitor" && item.next_due_at) {
    return "scheduled";
  }
  return "context";
}

function relationKey(value: HorizonRelation): string {
  return `${value.from_todo_id}\u0000${value.relation}\u0000${value.to_ref}`;
}

function relations(candidates: readonly HorizonCandidate[]): HorizonRelation[] {
  const projected: HorizonRelation[] = [];
  const seen = new Set<string>();
  const add = (value: HorizonRelation) => {
    const key = relationKey(value);
    if (!seen.has(key)) {
      seen.add(key);
      projected.push(value);
    }
  };
  for (const item of candidates) {
    for (const successor of new Set(item.successor_todo_ids)) {
      if (successor !== item.todo_id) {
        add({
          from_todo_id: item.todo_id,
          to_ref: successor,
          relation: "successor",
          enforcement: "lineage_only",
        });
      }
    }
    if (item.unblocks_todo_id && item.unblocks_todo_id !== item.todo_id) {
      add({
        from_todo_id: item.todo_id,
        to_ref: item.unblocks_todo_id,
        relation: "unblocks",
        enforcement: "typed_lifecycle",
      });
    }
    if (item.resume_when) {
      add({
        from_todo_id: item.todo_id,
        to_ref: item.resume_when,
        relation: "resumes_when",
        enforcement: "typed_condition",
      });
    }
    if (item.superseded_by && item.superseded_by !== item.todo_id) {
      add({
        from_todo_id: item.todo_id,
        to_ref: item.superseded_by,
        relation: "superseded_by",
        enforcement: "lineage_only",
      });
    }
    const routeRef = item.route_id || item.route_key;
    if (routeRef) {
      add({
        from_todo_id: item.todo_id,
        to_ref: `route:${routeRef}`,
        relation: "routes_via",
        enforcement: "read_only_context",
      });
    }
  }
  return projected;
}

function todoRef(value: string): string | null {
  if (TODO_ID.test(value)) return value;
  const separator = value.indexOf(":");
  if (separator < 0) return null;
  const suffix = value.slice(separator + 1);
  return TODO_ID.test(suffix) ? suffix : null;
}

function connectedDistances(
  selectedTodoId: string,
  values: readonly HorizonRelation[],
): Map<string, number> {
  const adjacency = new Map<string, Set<string>>();
  const connect = (left: string, right: string) => {
    const neighbors = adjacency.get(left) ?? new Set<string>();
    neighbors.add(right);
    adjacency.set(left, neighbors);
  };
  for (const relation of values) {
    const target = todoRef(relation.to_ref);
    if (!target) continue;
    connect(relation.from_todo_id, target);
    connect(target, relation.from_todo_id);
  }
  const distances = new Map<string, number>([[selectedTodoId, 0]]);
  const queue = [selectedTodoId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    const nextDistance = (distances.get(current) ?? 0) + 1;
    for (const neighbor of adjacency.get(current) ?? []) {
      if (distances.has(neighbor)) continue;
      distances.set(neighbor, nextDistance);
      queue.push(neighbor);
    }
  }
  return distances;
}

function contextReasons(
  item: HorizonCandidate,
  state: PlanningState,
  selectedPriority: number,
  distance: number | undefined,
): string[] {
  const reasons: string[] = [];
  if (distance !== undefined && distance > 0) reasons.push("related_to_selected");
  if (priorityRank(item.priority) < selectedPriority) {
    reasons.push("higher_priority_than_selected");
  }
  if (state === "runnable") reasons.push("runnable_alternative");
  if (state === "waiting") reasons.push("pending_resume_condition");
  if (state === "blocked") reasons.push("explicit_blocker");
  if (state === "scheduled") reasons.push("scheduled_observation");
  return reasons;
}

function compactAcceptanceGap(value: unknown, index: number): JsonObject & { truncated: boolean } {
  const raw = requireJsonObject(value, `acceptance_gaps[${index}]`);
  const compact: JsonObject & { truncated: boolean } = {
    kind: requireNonEmptyString(raw.kind, `acceptance_gaps[${index}].kind`),
    truncated: false,
  };
  for (const field of [
    "source",
    "acceptance_summary",
    "replan_trigger_summary",
    "advancement_policy",
  ] as const) {
    const normalized = optionalNonEmptyString(raw[field], `acceptance_gaps[${index}].${field}`);
    if (normalized === null) continue;
    const bounded = compactText(
      normalized,
      field === "source" || field === "advancement_policy"
        ? CONTEXT_TEXT_LIMIT
        : ACCEPTANCE_TEXT_LIMIT,
    );
    compact[field] = bounded.text;
    compact.truncated ||= bounded.truncated;
  }
  return compact;
}

/**
 * Project the bounded context an agent needs to reason beyond one local action.
 *
 * The reducer is deliberately read-only. It orders and bounds existing typed
 * facts, but selected_todo/action_portfolio remain the only dispatch authority.
 */
export function projectQuotaPlanningHorizon(value: unknown): JsonObject | null {
  const request = requireJsonObject(value, "planning_horizon_request");
  if (request.schema_version !== PLANNING_HORIZON_REQUEST_SCHEMA_VERSION) {
    throw new EffectRuntimeRequestError(
      `planning_horizon_request.schema_version must be ${PLANNING_HORIZON_REQUEST_SCHEMA_VERSION}`,
    );
  }
  const goalId = requireNonEmptyString(request.goal_id, "planning_horizon_request.goal_id");
  const agentId = requireNonEmptyString(request.agent_id, "planning_horizon_request.agent_id");
  const selected = candidate(request.selected_todo, "planning_horizon_request.selected_todo");
  const sourceContextCount = requireInteger(
    request.source_context_todo_count,
    "planning_horizon_request.source_context_todo_count",
  );
  if (sourceContextCount < 0) {
    throw new EffectRuntimeRequestError(
      "planning_horizon_request.source_context_todo_count must be non-negative",
    );
  }
  const rawCandidates = Array.isArray(request.candidates) ? request.candidates : [];
  if (rawCandidates.length > MAX_SOURCE_ITEMS) {
    throw new EffectRuntimeRequestError(
      `planning_horizon_request.candidates must contain at most ${MAX_SOURCE_ITEMS} items`,
    );
  }
  const byId = new Map<string, HorizonCandidate>([[selected.todo_id, selected]]);
  for (const [index, raw] of rawCandidates.entries()) {
    const item = candidate(raw, `planning_horizon_request.candidates[${index}]`);
    if (!byId.has(item.todo_id)) byId.set(item.todo_id, item);
  }
  const runnableTodoIds = new Set(
    requireStringArray(
      request.runnable_todo_ids ?? [],
      "planning_horizon_request.runnable_todo_ids",
    ).map((item, index) => todoId(item, `planning_horizon_request.runnable_todo_ids[${index}]`)),
  );
  const sourceRelations = relations([...byId.values()]);
  const distances = connectedDistances(selected.todo_id, sourceRelations);
  const selectedPriority = priorityRank(selected.priority);
  const strategicContextStates = new Set<PlanningState>([
    "waiting",
    "blocked",
    "scheduled",
  ]);
  const ordered = [...byId.values()].sort((left, right) => {
    const leftDistance = distances.get(left.todo_id);
    const rightDistance = distances.get(right.todo_id);
    const bucket = (item: HorizonCandidate, distance: number | undefined) => {
      if (item.todo_id === selected.todo_id) return 0;
      if (distance !== undefined) return 1;
      if (strategicContextStates.has(planningState(item, selected.todo_id, runnableTodoIds))) {
        return 2;
      }
      if (priorityRank(item.priority) < selectedPriority) return 3;
      if (runnableTodoIds.has(item.todo_id)) return 4;
      return 5;
    };
    return (
      bucket(left, leftDistance) - bucket(right, rightDistance) ||
      (leftDistance ?? 1_000) - (rightDistance ?? 1_000) ||
      priorityRank(left.priority) - priorityRank(right.priority) ||
      (left.index ?? 1_000_000) - (right.index ?? 1_000_000) ||
      left.todo_id.localeCompare(right.todo_id)
    );
  });
  const projectedItems = ordered.slice(0, MAX_PROJECTED_ITEMS).map((item) => {
    const state = planningState(item, selected.todo_id, runnableTodoIds);
    const text = compactText(item.text, ITEM_TEXT_LIMIT);
    const projected: JsonObject = {
      todo_id: item.todo_id,
      text: text.text,
      planning_state: state,
      context_reasons: contextReasons(
        item,
        state,
        selectedPriority,
        distances.get(item.todo_id),
      ),
    };
    for (const field of ["priority", "action_kind"] as const) {
      if (item[field] !== undefined) projected[field] = item[field];
    }
    if (item.task_class && item.task_class !== "advancement_task") {
      projected.task_class = item.task_class;
    }
    if (item.continuation_hint) {
      const hint = compactText(item.continuation_hint, CONTEXT_TEXT_LIMIT);
      projected.continuation_hint = hint.text;
      if (hint.truncated) projected.context_truncated = true;
    }
    if (text.truncated) projected.context_truncated = true;
    return projected;
  });
  const projectedIds = new Set(projectedItems.map((item) => String(item.todo_id)));
  const relevantRelations = sourceRelations.filter((relation) => {
    const target = todoRef(relation.to_ref);
    return projectedIds.has(relation.from_todo_id) || (target !== null && projectedIds.has(target));
  }).sort((left, right) => {
    const relationRank = (relation: HorizonRelation) => ({
      successor: 0,
      unblocks: 1,
      superseded_by: 2,
      resumes_when: 3,
      routes_via: 4,
    })[relation.relation];
    const distance = (relation: HorizonRelation) => {
      const target = todoRef(relation.to_ref);
      return Math.min(
        distances.get(relation.from_todo_id) ?? 1_000,
        target ? distances.get(target) ?? 1_000 : 1_000,
      );
    };
    return relationRank(left) - relationRank(right) ||
      distance(left) - distance(right) || relationKey(left).localeCompare(relationKey(right));
  });
  const projectedRelations = relevantRelations.slice(0, MAX_PROJECTED_RELATIONS);
  const rawGaps = Array.isArray(request.acceptance_gaps) ? request.acceptance_gaps : [];
  const compactGaps = rawGaps.map(compactAcceptanceGap);
  const projectedGaps = compactGaps
    .slice(0, MAX_PROJECTED_ACCEPTANCE_GAPS)
    .map(({ truncated: _truncated, ...gap }) => gap);
  const sourceUnrepresented = Math.max(0, sourceContextCount - byId.size);
  const omittedItems = Math.max(0, byId.size - projectedItems.length);
  const omittedRelations = Math.max(0, sourceRelations.length - projectedRelations.length);
  const omittedGaps = Math.max(0, compactGaps.length - projectedGaps.length);
  const compactFieldTruncationCount =
    projectedItems.filter((item) => item.context_truncated === true).length +
    compactGaps.slice(0, MAX_PROJECTED_ACCEPTANCE_GAPS).filter((gap) => gap.truncated).length;
  const addsStrategicContext = sourceRelations.length > 0 ||
    compactGaps.length > 0 ||
    ordered.some((item) =>
      item.todo_id !== selected.todo_id &&
      strategicContextStates.has(planningState(item, selected.todo_id, runnableTodoIds))
    );
  if (!addsStrategicContext) {
    return null;
  }
  return {
    schema_version: PLANNING_HORIZON_SCHEMA_VERSION,
    mode: "read_only",
    goal_id: goalId,
    agent_id: agentId,
    selected_todo_id: selected.todo_id,
    selection_contract: {
      selected_todo_authority: "$.selected_todo",
      action_choice_authority: "$.action_portfolio",
      horizon_changes_selection: false,
      explicit_selection_required_for_other_work: true,
    },
    work_items: projectedItems,
    relations: projectedRelations,
    acceptance_gaps: projectedGaps,
    attention_todo_ids: projectedItems
      .filter((item) =>
        item.todo_id !== selected.todo_id &&
        Array.isArray(item.context_reasons) &&
        item.context_reasons.length > 0
      )
      .slice(0, 3)
      .map((item) => item.todo_id),
    completeness: {
      schema_version: "quota_planning_horizon_completeness_v0",
      source_context_todo_count: sourceContextCount,
      candidate_input_count: byId.size,
      source_unrepresented_todo_count: sourceUnrepresented,
      omitted_candidate_todo_count: omittedItems,
      omitted_relation_count: omittedRelations,
      omitted_acceptance_gap_count: omittedGaps,
      compact_field_truncation_count: compactFieldTruncationCount,
      complete: sourceUnrepresented === 0 && omittedItems === 0 &&
        omittedRelations === 0 && omittedGaps === 0 && compactFieldTruncationCount === 0,
    },
    detail_refs: {
      selected_todo: {
        schema_version: "todo_detail_ref_v0",
        goal_id: goalId,
        role: "agent",
        todo_id: selected.todo_id,
        projection: "todo_detail_cold_path_v0",
      },
      agent_todos: "quota should-run --include-detail agent-todos",
      task_graph: "status --include-task-graph",
    },
  };
}

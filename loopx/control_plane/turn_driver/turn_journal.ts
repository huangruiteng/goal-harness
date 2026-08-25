import transactionContract from "../turn_transaction_contract.json" with {
  type: "json",
};

import type { EffectTurn } from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";

export const TURN_JOURNAL_INSPECTION_SCHEMA_VERSION =
  "loopx_turn_journal_inspection_v0";

type JsonObject = Record<string, unknown>;

export interface TurnJournalInspectionRequest {
  schema_version: "loopx_turn_journal_interpretation_request_v0";
  journal: JsonObject;
  goal_id: string;
  agent_id: string;
  turn_key: string;
}

export interface TurnJournalInspection {
  ok: true;
  schema_version: typeof TURN_JOURNAL_INSPECTION_SCHEMA_VERSION;
  decision: "replay_legal" | "replay_blocked";
  journal_status: string;
  replay_legal: boolean;
  goal_matches: boolean;
  owner_matches: boolean;
  turn_key_matches: boolean;
  phases_form_ordered_prefix: boolean;
  completed_phases: string[];
  tombstone_retained: boolean;
  violations: string[];
  effects: [];
}

export interface TurnJournalEffectContext {
  replay_legal: boolean;
  goal_matches: boolean;
  owner_matches: boolean;
  turn_key_matches: boolean;
  phases_form_ordered_prefix: boolean;
  journal_status: string;
  tombstone_retained: boolean;
  completed_phases: string[];
  violations: string[];
}

export type TurnJournalEffect = EffectTurn<
  TurnJournalEffectContext,
  "replay_legal" | "replay_blocked"
>;

const transactionPhases = Object.freeze([...transactionContract.phases]);

function asObject(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function isValidIdentity(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function identityState(
  requiredValues: unknown[],
  optionalValues: Array<[boolean, unknown]>,
  expected: unknown,
): [complete: boolean, matches: boolean] {
  const complete =
    requiredValues.every(isValidIdentity) &&
    optionalValues.every(([present, value]) => !present || isValidIdentity(value)) &&
    isValidIdentity(expected);
  const observed = requiredValues.filter(isValidIdentity);
  for (const [present, value] of optionalValues) {
    if (present && isValidIdentity(value)) observed.push(value);
  }
  if (isValidIdentity(expected)) observed.push(expected);
  return [complete, complete && new Set(observed).size === 1];
}

function stringifyPhase(value: unknown): string {
  if (value === null) return "None";
  if (value === true) return "True";
  if (value === false) return "False";
  return String(value);
}

export function interpretTurnJournalEffect(
  request: TurnJournalInspectionRequest,
): TurnJournalEffect {
  if (request.schema_version !== "loopx_turn_journal_interpretation_request_v0") {
    throw new EffectRuntimeRequestError("Turn-journal interpretation request schema mismatch");
  }
  const journal = asObject(request.journal);
  const plan = asObject(journal.plan);
  const envelope = asObject(plan.turn_envelope);
  const transaction = asObject(plan.transaction);
  const settlement = asObject(transaction.settlement_plan);
  const identity = asObject(settlement.identity);
  const hostResult = asObject(journal.host_result);
  const receipt = asObject(journal.receipt);

  const [goalComplete, goalMatches] = identityState(
    [journal.goal_id, envelope.goal_id, identity.goal_id],
    [],
    request.goal_id,
  );
  const [ownerComplete, ownerMatches] = identityState(
    [envelope.agent_id, identity.agent_id],
    [],
    request.agent_id,
  );
  const [turnKeyComplete, turnKeyMatches] = identityState(
    [journal.turn_key, transaction.turn_key],
    [
      [Object.hasOwn(hostResult, "turn_key"), hostResult.turn_key],
      [Object.hasOwn(receipt, "turn_key"), receipt.turn_key],
    ],
    request.turn_key,
  );

  const violations: string[] = [];
  if (!goalComplete) violations.push("goal_identity_missing");
  else if (!goalMatches) violations.push("goal_mismatch");
  if (!ownerComplete) violations.push("owner_identity_missing");
  else if (!ownerMatches) violations.push("owner_mismatch");
  if (!turnKeyComplete) violations.push("turn_key_identity_missing");
  else if (!turnKeyMatches) violations.push("turn_key_mismatch");

  let completedPhases: string[] = [];
  let phasesFormOrderedPrefix = false;
  if (Array.isArray(journal.completed_phases)) {
    completedPhases = journal.completed_phases.map(stringifyPhase);
    phasesFormOrderedPrefix = completedPhases.every(
      (phase, index) => transactionPhases[index] === phase,
    );
    if (!phasesFormOrderedPrefix) {
      violations.push("completed_phases_not_ordered_prefix");
    }
  } else {
    violations.push("completed_phases_invalid");
  }

  const journalStatus = journal.status ? String(journal.status) : "";
  const tombstoneRetained = ["committed", "stopped", "failed"].includes(
    journalStatus,
  );
  if (["in_progress", "scheduler_action_required"].includes(journalStatus)) {
    violations.push("journal_not_terminal");
  } else if (!tombstoneRetained) {
    violations.push("journal_status_unsupported");
  }

  const replayLegal = violations.length === 0;
  const decision = replayLegal ? "replay_legal" : "replay_blocked";
  return {
    request: {
      kind: "turn_journal",
      source: "turn_journal",
      goal_id: request.goal_id,
      agent_id: request.agent_id,
      capabilities: [],
      context: {
        replay_legal: replayLegal,
        goal_matches: goalMatches,
        owner_matches: ownerMatches,
        turn_key_matches: turnKeyMatches,
        phases_form_ordered_prefix: phasesFormOrderedPrefix,
        journal_status: journalStatus,
        tombstone_retained: tombstoneRetained,
        completed_phases: completedPhases,
        violations,
      },
    },
    interpretation: {
      route: "turn_journal_replay",
      obligation: "observe_fenced_replay",
      interaction_mode: "read_only",
      capability_action: null,
      cadence_class: null,
    },
    observation: {
      decision,
      should_run: false,
      effective_action: replayLegal ? "observe_replay" : "block_replay",
      recommended_action: replayLegal
        ? "Retain the terminal Turn journal tombstone."
        : "Inspect the structured Turn journal violations before replay.",
      action_portfolio: null,
      planning_horizon: null,
      protocol_summary: replayLegal
        ? "Turn journal replay is legal and effect-free."
        : `Turn journal replay is blocked by ${violations.length} structured violation(s).`,
    },
    next_effect: {
      cli_actions: [],
      execution_mode: null,
      scheduler_action: null,
      cadence_class: null,
      ack_cli_args: [],
      failure_cli_args: [],
    },
  };
}

export function projectTurnJournalInspection(
  turn: TurnJournalEffect,
): TurnJournalInspection {
  const context = turn.request.context;
  return {
    ok: true,
    schema_version: TURN_JOURNAL_INSPECTION_SCHEMA_VERSION,
    decision: turn.observation.decision,
    journal_status: context.journal_status,
    replay_legal: context.replay_legal,
    goal_matches: context.goal_matches,
    owner_matches: context.owner_matches,
    turn_key_matches: context.turn_key_matches,
    phases_form_ordered_prefix: context.phases_form_ordered_prefix,
    completed_phases: context.completed_phases,
    tombstone_retained: context.tombstone_retained,
    violations: context.violations,
    effects: [],
  };
}

export function interpretTurnJournal(
  request: TurnJournalInspectionRequest,
): TurnJournalInspection {
  return projectTurnJournalInspection(interpretTurnJournalEffect(request));
}

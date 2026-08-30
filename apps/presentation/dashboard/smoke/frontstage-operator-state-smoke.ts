// Semantic smoke for the operator-state classification in
// src/data/goal-channel-frontstage.ts.
//
// Proves exact typed mapping semantics, not element presence: positive and
// negative outcome tokens, failed/blocked delivery dispositions, ordinary
// workspace/capability wording that must NOT classify as repair/wait, and
// unknown tokens staying neutral.

import {
  actionKindTone,
  deriveOperatorStateSignals,
  deliveryOutcomeTone,
  eventClassificationTone,
  leaseStatusTone,
  sampleGoalChannelProjection,
  type GoalChannelProjection,
} from "../src/data/goal-channel-frontstage.js";

type Tone = "neutral" | "success" | "warning" | "info" | "danger";

function expectTone(actual: Tone, expected: Tone, label: string): void {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
}

const outcomeOutcomeCases: Array<[string | null | undefined, Tone]> = [
  ["outcome_progress", "success"],
  ["primary_goal_outcome", "success"],
  ["PRIMARY_GOAL_OUTCOME", "success"],
  ["outcome_gap", "danger"],
  ["delivery_failed", "danger"],
  ["delivery_blocked", "danger"],
  ["surface_only", "neutral"],
  ["unknown", "neutral"],
  ["not_configured", "neutral"],
  ["some_future_token", "neutral"],
  [null, "neutral"],
  [undefined, "neutral"],
];

const actionKindCases: Array<[string | null | undefined, Tone]> = [
  ["workspace_repair", "warning"],
  ["capability_wait", "warning"],
  ["capability_repair", "warning"],
  ["delivery", "neutral"],
  ["delivery_failed", "neutral"],
  ["review_refine_merge", "neutral"],
  ["approve_route", "neutral"],
  ["frontstage_render", "neutral"],
  [undefined, "neutral"],
];

const classificationCases: Array<[string | null | undefined, Tone]> = [
  ["validated_progress", "success"],
  ["delivery_outcome", "info"],
  ["operator_gate_recorded", "info"],
  ["capability_wait", "warning"],
  ["workspace_repair", "warning"],
  ["outcome_gap", "danger"],
  ["delivery_blocked", "danger"],
  ["surface_only", "neutral"],
  ["capability lookups ongoing", "neutral"],
  [undefined, "neutral"],
];

const leaseStatusCases: Array<[string | null | undefined, Tone]> = [
  ["hard_lease", "success"],
  ["active", "success"],
  ["soft_claim", "info"],
  ["claimed", "info"],
  ["expired", "neutral"],
  ["released", "neutral"],
  ["renewing_soon", "neutral"],
  [undefined, "neutral"],
];

function runTables(): void {
  for (const [token, expected] of outcomeOutcomeCases) {
    expectTone(deliveryOutcomeTone(token), expected, `deliveryOutcomeTone(${token})`);
  }
  for (const [token, expected] of actionKindCases) {
    expectTone(actionKindTone(token), expected, `actionKindTone(${token})`);
  }
  for (const [token, expected] of classificationCases) {
    expectTone(
      eventClassificationTone(token),
      expected,
      `eventClassificationTone(${token})`,
    );
  }
  for (const [token, expected] of leaseStatusCases) {
    expectTone(leaseStatusTone(token), expected, `leaseStatusTone(${token})`);
  }
}

function projectionWith(overrides: Partial<GoalChannelProjection>): GoalChannelProjection {
  return { ...sampleGoalChannelProjection, ...overrides };
}

function signal(
  projection: GoalChannelProjection,
  label: string,
): { value: string; tone: Tone } {
  const derived = deriveOperatorStateSignals(projection).find(
    (entry) => entry.label === label,
  );
  if (!derived) {
    throw new Error(`missing operator signal: ${label}`);
  }
  return { value: derived.value, tone: derived.tone };
}

function runDerivedSignals(): void {
  // Sample fixture: outcome_progress is a positive outcome, not a gap.
  expectTone(
    signal(sampleGoalChannelProjection, "outcome").tone,
    "success",
    "sample outcome signal",
  );

  const gap = projectionWith({
    source_refs: {
      ...sampleGoalChannelProjection.source_refs,
      latest_delivery_outcome: "outcome_gap",
    },
  });
  const gapSignal = signal(gap, "outcome");
  expectTone(gapSignal.tone, "danger", "outcome_gap signal");
  if (gapSignal.value !== "outcome_gap") {
    throw new Error(`outcome_gap value: ${gapSignal.value}`);
  }

  const failed = projectionWith({
    source_refs: {
      ...sampleGoalChannelProjection.source_refs,
      latest_delivery_outcome: "delivery_failed",
    },
  });
  expectTone(signal(failed, "outcome").tone, "danger", "delivery_failed signal");

  const surfacedOnly = projectionWith({
    source_refs: {
      ...sampleGoalChannelProjection.source_refs,
      latest_delivery_outcome: "surface_only",
    },
  });
  expectTone(signal(surfacedOnly, "outcome").tone, "neutral", "surface_only signal");

  // A failed delivery observed only in the event ledger still reads as danger.
  const ledgerGap = projectionWith({
    source_refs: { ...sampleGoalChannelProjection.source_refs, latest_delivery_outcome: null },
    recent_events: [
      {
        generated_at: "2026-06-20T08:03:00Z",
        classification: "outcome_gap",
        summary: "run produced no material advancement",
      },
    ],
  });
  expectTone(signal(ledgerGap, "outcome").tone, "danger", "ledger outcome_gap signal");

  // Ordinary workspace/capability prose in a todo title must not classify as
  // repair or wait; only typed domain discriminators do.
  const proseOnly = projectionWith({
    waiting_on: "nothing",
    agent_todos: [
      {
        todo_id: "todo_prose",
        priority: "P2",
        status: "open",
        task_class: "advancement_task",
        action_kind: "review_notes",
        title: "Document workspace behavior and review capability catalog wording.",
      },
    ],
    open_gates: [],
    recent_events: [],
  });
  expectTone(signal(proseOnly, "workspace-repair").tone, "success", "workspace prose todo");
  expectTone(signal(proseOnly, "capability-wait").tone, "success", "capability prose todo");

  // Typed capability wait signals stay warnings.
  const waiting = projectionWith({
    agent_todos: [
      {
        todo_id: "todo_wait",
        priority: "P0",
        status: "waiting",
        task_class: "advancement_task",
        action_kind: "capability_wait",
        title: "Wait for worker_bridge.",
      },
    ],
  });
  expectTone(signal(waiting, "capability-wait").tone, "warning", "capability_wait todo");

  // A generic waiting lifecycle status does not establish a capability wait.
  const externalReviewWait = projectionWith({
    waiting_on: "external_evidence",
    agent_todos: [
      {
        todo_id: "todo_external_review_wait",
        priority: "P0",
        status: "waiting",
        task_class: "advancement_task",
        action_kind: "external_review_wait",
        title: "Wait for an independent reviewer.",
      },
    ],
    open_gates: [],
    recent_events: [],
  });
  const externalReviewSignal = signal(externalReviewWait, "capability-wait");
  expectTone(
    externalReviewSignal.tone,
    "success",
    "external review waiting todo",
  );
  if (externalReviewSignal.value !== "clear") {
    throw new Error(`external review waiting value: ${externalReviewSignal.value}`);
  }

  // Unknown outcome tokens stay neutral, never success.
  const unknownToken = projectionWith({
    source_refs: {
      ...sampleGoalChannelProjection.source_refs,
      latest_delivery_outcome: "mystery_outcome",
    },
  });
  expectTone(signal(unknownToken, "outcome").tone, "neutral", "unknown outcome token");
}

function main(): void {
  runTables();
  runDerivedSignals();
  console.log("frontstage-operator-state-smoke ok");
}

main();

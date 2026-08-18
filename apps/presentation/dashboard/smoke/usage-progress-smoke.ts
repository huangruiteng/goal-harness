// @ts-expect-error The smoke compiler intentionally runs without @types/node.
import { readFileSync } from "node:fs";

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

function includes(source: string, snippet: string, label: string) {
  assert(source.includes(snippet), `missing ${label}: ${snippet}`);
}

function excludes(source: string, snippet: string, label: string) {
  assert(!source.includes(snippet), `unexpected ${label}: ${snippet}`);
}

const statusSource = readFileSync("src/data/status.ts", "utf8");
const dashboardSource = readFileSync("src/views/dashboard-page.tsx", "utf8");
const packageSource = readFileSync("package.json", "utf8");
const exampleStatus = readFileSync("../../../examples/status.example.json", "utf8");
const promotionGateWarningFixture = readFileSync("../../../examples/dashboard-promotion-gate-warning-status.json", "utf8");
const decisionFreshnessFixture = readFileSync("../../../examples/dashboard-home-browser-smoke.mjs", "utf8");
const contractSource = readFileSync("../../../docs/status-data-contract.md", "utf8");
const promotionGateWarningStatus = JSON.parse(promotionGateWarningFixture);

for (const [field, label] of [
  ["progress_signal_run_count_24h", "24h progress signal field"],
  ["progress_signal_run_count_7d", "7d progress signal field"],
] as const) {
  includes(statusSource, `${field}: z.number().optional().default(0)`, `schema ${label}`);
  includes(statusSource, `${field}: 0`, `default totals ${label}`);
  includes(exampleStatus, `"${field}"`, `example ${label}`);
  includes(contractSource, field, `contract ${label}`);
}

for (const [field, label] of [
  ["status_contract", "status contract payload field"],
  ["schema_version", "status contract schema version"],
  ["reload_hint", "status contract daemon reload hint"],
  ["event_ledger_summary", "event ledger summary payload field"],
  ["by_class_24h", "24h event class counts"],
  ["by_class_7d", "7d event class counts"],
  ["latest_event_class", "latest event class"],
] as const) {
  includes(statusSource, field, `schema ${label}`);
  includes(exampleStatus, `"${field}"`, `example ${label}`);
  includes(contractSource, field, `contract ${label}`);
}

for (const [field, label] of [
  ["decision_freshness_summary", "decision freshness payload field"],
  ["requires_decision_point_rebase", "decision point rebase guard"],
  ["newer_event_count_7d", "newer event count"],
] as const) {
  includes(statusSource, field, `schema ${label}`);
  if (field === "decision_freshness_summary") {
    includes(exampleStatus, `"${field}"`, `example ${label}`);
  } else {
    includes(decisionFreshnessFixture, field, `decision freshness fixture ${label}`);
  }
  includes(contractSource, field, `contract ${label}`);
}

for (const [field, label] of [
  ["promotion_readiness_summary", "promotion readiness payload field"],
  ["promotion_gate", "promotion gate payload field"],
  ["can_promote", "promotion gate promote decision"],
  ["should_warn", "promotion gate warning decision"],
  ["requires_readiness_run", "promotion readiness rerun guard"],
  ["freshness_window_hours", "promotion readiness freshness window"],
] as const) {
  includes(statusSource, field, `schema ${label}`);
  includes(exampleStatus, `"${field}"`, `example ${label}`);
  includes(contractSource, field, `contract ${label}`);
}

assert(
  promotionGateWarningStatus.promotion_gate.gate_state === "warning",
  "promotion gate warning fixture gate_state",
);
assert(
  promotionGateWarningStatus.promotion_gate.can_promote === false,
  "promotion gate warning fixture can_promote",
);
assert(
  promotionGateWarningStatus.promotion_gate.should_warn === true,
  "promotion gate warning fixture should_warn",
);
assert(
  promotionGateWarningStatus.promotion_gate.readiness.freshness_status === "missing",
  "promotion gate warning fixture freshness",
);
includes(
  promotionGateWarningFixture,
  "python3 examples/canary/canary-promotion-readiness-smoke.py",
  "promotion gate warning fixture recommended action",
);

includes(
  packageSource,
  "dashboard-promotion-readiness-browser-smoke.mjs",
  "canonical promotion readiness browser smoke script",
);
excludes(
  packageSource,
  "dashboard-promotion-readiness-smoke.mjs",
  "stale promotion readiness browser smoke script",
);

for (const [snippet, label] of [
  ["buildPersonalHomeModel(payload, rows)", "personal workspace model assembly"],
  ["shareUsageById(payload.usage_summary)", "goal usage projection"],
  ["systemHealth", "system health projection"],
  ["payload.decision_freshness_summary", "decision freshness check"],
] as const) {
  includes(dashboardSource, snippet, label);
}

console.log("usage-progress smoke ok");

#!/usr/bin/env node
// Browser-level smoke for the dashboard planned operator-gate state.

import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanupBrowserSmoke, launchBrowser, loadPlaywright } from "./dashboard-browser-smoke-support.mjs";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dashboardDir = resolve(repoRoot, "apps/presentation/dashboard");
const fixtureName = "status.operator-gate.browser-smoke.json";
const approvedFixtureName = "status.operator-gate-approved.browser-smoke.json";
const staleHistoryApprovedFixtureName = "status.operator-gate-approved-stale-history.browser-smoke.json";
const fixturePath = resolve(dashboardDir, "public", fixtureName);
const approvedFixturePath = resolve(dashboardDir, "public", approvedFixtureName);
const staleHistoryApprovedFixturePath = resolve(dashboardDir, "public", staleHistoryApprovedFixtureName);
const port = Number(process.env.LOOPX_DASHBOARD_OPERATOR_GATE_SMOKE_PORT ?? "5192");

const goalId = "planned-main-control";
const operatorQuestion = "是否同意 `planned-main-control` 先执行 read-only map opt-in？";
const recommendedAction = "先在 LoopX 完成 operator 判断；同意后项目 Agent 只执行 read-only map dry-run";
const assetNextAction = "Project asset: handle owner todo before approving the gate";
const assetStopCondition = "Project asset stop: record or defer the owner todo before approval";
const userTodoText = "Read owner review worksheet first.";
const agentTodoText = "Run the read-only map dry-run after owner todo resolution.";
const previewCommand = "loopx read-only-map --goal-id planned-main-control --dry-run";
const approvedAction = "operator approved read-only map; project agent can execute the approved dry-run";
const approvedCommand = "loopx read-only-map --goal-id planned-main-control --dry-run --approved";

const operatorGateQuota = {
  compute: 0.5,
  window_hours: 24,
  slot_minutes: 1,
  allowed_slots: 720,
  spent_slots: 0,
  state: "operator_gate",
  reason: "planned goal needs operator opt-in before spending agent turns",
};

const statusFixture = {
  ok: true,
  registry: "./fixtures/registry.json",
  runtime_root: "./fixtures/runtime",
  goal_count: 1,
  run_count: 0,
  contract: {
    ok: true,
    summary: { errors: 0, warnings: 0, checks: 1 },
    errors: [],
    warnings: [],
    checks: ["public-safe operator-gate dashboard fixture"],
  },
  global_registry: {
    available: true,
    ok: true,
    registry: "./fixtures/registry.global.json",
    current_registry: "./fixtures/registry.json",
    current_registry_is_global: false,
    global_goal_count: 1,
    current_goal_count: 1,
    source_registry_count: 1,
    summary: { high: 0, action: 0, info: 0, checks: 1, findings: 0 },
    findings: [],
    checks: ["public-safe operator-gate dashboard fixture"],
  },
  attention_queue: {
    available: true,
    item_count: 1,
    needs_user_or_controller: 1,
    needs_controller: 0,
    needs_codex: 0,
    watching_external_evidence: 0,
    items: [
      {
        goal_id: goalId,
        status: "planned-high-complexity",
        lifecycle_phase: "planned",
        lifecycle_flags: ["planned"],
        waiting_on: "user_or_controller",
        severity: "action",
        recommended_action: recommendedAction,
        project_asset: {
          owner: "user_or_controller",
          gate: "operator_question",
          next_action: assetNextAction,
          stop_condition: assetStopCondition,
          user_todos: {
            open: 1,
            done: 0,
            total: 1,
            next: userTodoText,
          },
          agent_todos: {
            open: 1,
            done: 0,
            total: 1,
            next: agentTodoText,
          },
          quota: operatorGateQuota,
          latest_validation: {
            generated_at: "2026-01-01T00:00:00+00:00",
            classification: "planned-high-complexity",
            summary: "fixture planned controller opt-in",
          },
        },
        operator_question: operatorQuestion,
        agent_command: previewCommand,
        quota: operatorGateQuota,
        source: "registry",
      },
    ],
  },
  run_history: {
    available: true,
    goal_count: 1,
    run_count: 0,
    goals: [
      {
        id: goalId,
        domain: "operator-gate-fixture",
        status: "planned-high-complexity",
        lifecycle_phase: "planned",
        lifecycle_flags: ["planned"],
        registry_member: true,
        legacy_runtime_goal: false,
        adapter_kind: "complex_project_read_only_map_v0",
        adapter_status: "planned",
        authority_registry: {
          declared: false,
          required: false,
          default_entry_count: 0,
          default_entries_checked: 0,
          default_entries_present: 0,
          topic_authority_count: 0,
          deprecated_source_count: 0,
          conflict_risk: "none",
        },
        quota: operatorGateQuota,
        index_exists: false,
        raw_index_records: 0,
        unique_runs: 0,
        latest_runs: [],
      },
    ],
    recent_runs: [],
  },
};

const approvedStatusFixture = {
  ...statusFixture,
  run_count: 1,
  attention_queue: {
    ...statusFixture.attention_queue,
    needs_user_or_controller: 0,
    needs_codex: 1,
    items: [
      {
        goal_id: goalId,
        status: "operator_gate_approved",
        lifecycle_phase: "mapped",
        lifecycle_flags: ["mapped", "operator_approved"],
        waiting_on: "codex",
        severity: "action",
        recommended_action: approvedAction,
        project_asset: {
          owner: "codex",
          gate: "none",
          next_action: approvedAction,
          stop_condition: "Project asset stop: stop if the approved dry-run command fails",
          agent_todos: {
            open: 1,
            done: 0,
            total: 1,
            next: agentTodoText,
          },
          quota: {
            compute: 0.5,
            window_hours: 24,
            allowed_slots: 12,
            spent_slots: 0,
            state: "eligible",
            reason: "operator gate approved; eligible for the next agent turn",
          },
          latest_validation: {
            generated_at: "2026-01-01T00:01:00+00:00",
            classification: "operator_gate_approved",
            summary: "fixture operator gate approved; agent_command 1/1",
          },
        },
        agent_command: approvedCommand,
        quota: {
          compute: 0.5,
          window_hours: 24,
          allowed_slots: 12,
          spent_slots: 0,
          state: "eligible",
          reason: "operator gate approved; eligible for the next agent turn",
        },
        source: "latest_run",
      },
    ],
  },
  run_history: {
    ...statusFixture.run_history,
    run_count: 1,
    goals: [
      {
        ...statusFixture.run_history.goals[0],
        status: "operator_gate_approved",
        lifecycle_phase: "mapped",
        lifecycle_flags: ["mapped", "operator_approved"],
        index_exists: true,
        raw_index_records: 1,
        unique_runs: 1,
        latest_runs: [
          {
            generated_at: "2026-01-01T00:01:00+00:00",
            goal_id: goalId,
            classification: "operator_gate_approved",
            lifecycle_phase: "mapped",
            lifecycle_flags: ["mapped", "operator_approved"],
            recommended_action: approvedAction,
            health_check: "fixture operator gate approved; agent_command 1/1",
            json_exists: true,
            markdown_exists: true,
            operator_gate: {
              recorded_at: "2026-01-01T00:01:00+00:00",
              gate: "read_only_map_opt_in",
              decision: "approve",
              reason_summary: "approved read-only map dry-run only",
              agent_command: approvedCommand,
            },
          },
        ],
      },
    ],
    recent_runs: [
      {
        generated_at: "2026-01-01T00:01:00+00:00",
        goal_id: goalId,
        classification: "operator_gate_approved",
        lifecycle_phase: "mapped",
        lifecycle_flags: ["mapped", "operator_approved"],
        recommended_action: approvedAction,
        health_check: "fixture operator gate approved; agent_command 1/1",
        json_exists: true,
        markdown_exists: true,
        operator_gate: {
          recorded_at: "2026-01-01T00:01:00+00:00",
          gate: "read_only_map_opt_in",
          decision: "approve",
          reason_summary: "approved read-only map dry-run only",
          agent_command: approvedCommand,
        },
      },
    ],
  },
};

const staleHistoryApprovedStatusFixture = {
  ...approvedStatusFixture,
  run_history: {
    ...approvedStatusFixture.run_history,
    goals: [
      {
        ...statusFixture.run_history.goals[0],
        status: "operator_gate_deferred",
        lifecycle_phase: "planned",
        lifecycle_flags: ["planned"],
        index_exists: true,
        raw_index_records: 1,
        unique_runs: 1,
        latest_runs: [
          {
            generated_at: "2026-01-01T00:00:00+00:00",
            goal_id: goalId,
            classification: "operator_gate_deferred",
            lifecycle_phase: "planned",
            lifecycle_flags: ["planned"],
            recommended_action: "ask the stale operator gate again",
            health_check: "stale latest run should not drive dashboard action selection",
            json_exists: true,
            markdown_exists: true,
            operator_gate: {
              recorded_at: "2026-01-01T00:00:00+00:00",
              gate: "read_only_map_opt_in",
              decision: "defer",
              operator_question: operatorQuestion,
              reason_summary: "stale defer should not replace the current queue item",
              agent_command: "loopx stale-command --dry-run",
            },
          },
        ],
      },
    ],
    recent_runs: [
      {
        generated_at: "2026-01-01T00:00:00+00:00",
        goal_id: goalId,
        classification: "operator_gate_deferred",
        lifecycle_phase: "planned",
        lifecycle_flags: ["planned"],
        recommended_action: "ask the stale operator gate again",
        health_check: "stale latest run should not drive dashboard action selection",
        json_exists: true,
        markdown_exists: true,
        operator_gate: {
          recorded_at: "2026-01-01T00:00:00+00:00",
          gate: "read_only_map_opt_in",
          decision: "defer",
          operator_question: operatorQuestion,
          reason_summary: "stale defer should not replace the current queue item",
          agent_command: "loopx stale-command --dry-run",
        },
      },
    ],
  },
};

async function navigateTo(page, url) {
  await page.goto(url, { waitUntil: "networkidle" });
}

function countText(body, text) {
  return body.split(text).length - 1;
}

function requireTexts(body, texts, label) {
  const missing = texts.filter((text) => !body.includes(text));
  if (missing.length) {
    throw new Error(`Missing ${label} text: ${missing.join(", ")}`);
  }
}

function forbidTexts(body, texts, label) {
  const present = texts.filter((text) => body.includes(text));
  if (present.length) {
    throw new Error(`${label}: ${present.join(", ")}`);
  }
}

function requireExactTextCount(body, text, expected, label) {
  const actual = countText(body, text);
  if (actual !== expected) {
    throw new Error(`${label}: expected ${expected}, got ${actual}.`);
  }
}

function requireTextOrder(body, texts, label) {
  let cursor = -1;
  for (const text of texts) {
    const next = body.indexOf(text, cursor + 1);
    if (next < 0) {
      throw new Error(`Missing ${label} ordered text: ${text}`);
    }
    if (next < cursor) {
      throw new Error(`${label}: expected ${texts.join(" -> ")}`);
    }
    cursor = next;
  }
}

async function readBodyText(page, { requiredText = "用户操作", timeoutMs = 15_000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let body = "";
  let lastError;
  while (Date.now() < deadline) {
    try {
      body = await page.locator("main").innerText({ timeout: 5_000 });
      if (!requiredText || body.includes(requiredText)) {
        return body;
      }
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveTimeout) => setTimeout(resolveTimeout, 250));
  }
  throw new Error([
    `Timed out waiting for page text: ${requiredText}`,
    lastError?.message,
    body.slice(0, 500),
  ].filter(Boolean).join("\n"));
}

async function waitForDashboard(url) {
  const deadline = Date.now() + 20_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveTimeout) => setTimeout(resolveTimeout, 250));
  }
  throw lastError ?? new Error(`Timed out waiting for ${url}`);
}

async function main() {
  const { chromium } = loadPlaywright();
  await writeFile(fixturePath, JSON.stringify(statusFixture, null, 2) + "\n", "utf-8");
  await writeFile(approvedFixturePath, JSON.stringify(approvedStatusFixture, null, 2) + "\n", "utf-8");
  await writeFile(staleHistoryApprovedFixturePath, JSON.stringify(staleHistoryApprovedStatusFixture, null, 2) + "\n", "utf-8");

  const server = spawn("npm", ["run", "dev", "--", "--port", String(port), "--strictPort"], {
    cwd: dashboardDir,
    env: process.env,
    stdio: "ignore",
  });

  let browser;
  try {
    const baseUrl = `http://127.0.0.1:${port}`;
    await waitForDashboard(baseUrl);
    browser = await launchBrowser(chromium);
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await navigateTo(page, `${baseUrl}/?view=ops&statusUrl=/${fixtureName}&goalId=${goalId}&actionKind=all`);
    let body = await readBodyText(page, { requiredText: "复制操作信息" });
    requireTexts(body, [
      "Todo 重点",
      "用户 Todo",
      "Agent 优先 Todo",
      "1 个操作",
      "项目",
      goalId,
      "控制者",
      "审阅控制者接入",
      "需要批准",
      "用户 / 控制者",
      "需要操作者回答",
      "是否同意 `planned-main-control` 先执行 read-only map opt-in？",
      "先做用户待办",
      "Read owner review worksheet first.",
      "Project asset stop: record or defer the owner todo before approval",
      "批准后可执行 Agent 命令",
      "配额 0.5",
      "Agent Todo",
      "Run the read-only map dry-run after owner todo resolution.",
      "验证",
      "planned-high-complexity",
      "fixture planned controller opt-in",
      "复制操作信息",
    ], "pending dashboard");
    forbidTexts(body, [
      "当前没有需要用户处理的操作。",
      "让 Codex 继续",
      "Codex 可以继续",
      "Codex 可以执行",
      "continue_from_refreshed_state",
      "continue_codex_action",
      "Operator Review Packet",
      "Copy Review Packet",
      "复制交接信息",
      "Suggested decision",
      "同意先做只读映射预演；不授权写入或生产动作。",
    ], "Operator-gated goal leaked into confusing UI");
    requireExactTextCount(body, "审阅控制者接入", 2, "All-actions controller action plus selected-detail count");
    requireExactTextCount(body, "复制操作信息", 1, "All-actions review-packet copy count");
    requireTextOrder(body, ["Todo 重点", "用户操作"], "Todo focus should lead user action cards");
    requireTextOrder(body, ["项目", goalId, "审阅控制者接入"], "All-actions project-first card identity");
    if (body.indexOf("需要操作者回答") > body.indexOf("批准后可执行 Agent 命令")) {
      throw new Error("Operator question should appear before the after-approval agent command hint.");
    }

    await navigateTo(page, `${baseUrl}/?view=ops&statusUrl=/${fixtureName}&goalId=${goalId}&actionKind=controller`);
    body = await readBodyText(page, { requiredText: "复制操作信息" });
    requireTexts(body, [
      "Todo 重点",
      "用户 Todo",
      "Agent 优先 Todo",
      "1 个操作",
      "项目",
      goalId,
      "控制者",
      "审阅控制者接入",
      "需要批准",
      "需要操作者回答",
      "是否同意 `planned-main-control` 先执行 read-only map opt-in？",
      "Read owner review worksheet first.",
      "Agent Todo",
      "Run the read-only map dry-run after owner todo resolution.",
      "验证",
      "planned-high-complexity",
      "复制操作信息",
    ], "focused controller dashboard");
    forbidTexts(body, [
      "当前没有需要用户处理的操作。",
      "Operator Review Packet",
      "让 Codex 继续",
      "Codex 可以继续",
      "Copy Review Packet",
      "复制交接信息",
      "Suggested decision",
      "同意先做只读映射预演；不授权写入或生产动作。",
    ], "Focused controller view rendered confusing stale UI");
    requireExactTextCount(body, "审阅控制者接入", 2, "Focused controller action plus selected-detail count");
    requireExactTextCount(body, "复制操作信息", 1, "Focused controller review-packet copy count");
    requireTextOrder(body, ["Todo 重点", "用户操作"], "Focused todo focus should lead user action cards");
    requireTextOrder(body, ["项目", goalId, "审阅控制者接入"], "Focused controller project-first card identity");

    await navigateTo(page, `${baseUrl}/?view=ops&statusUrl=/${approvedFixtureName}&goalId=${goalId}&actionKind=all`);
    body = await readBodyText(page, { requiredText: "复制交接信息" });
    requireTexts(body, [
      "1 个操作",
      "项目",
      goalId,
      "Codex",
      "执行已批准的 Agent 命令",
      "已批准交接",
      "已批准 Agent 命令",
      "已批准命令",
      "批准",
      "复制交接信息",
    ], "approved dashboard");
    forbidTexts(body, [
      "审阅控制者接入",
      "需要批准",
      "需要操作者回答",
      "批准后可执行 Agent 命令",
      "操作者确认试运行草稿",
      "Operator Review Packet",
      "Copy Review Packet",
    ], "Approved operator gate still looks user-gated");
    requireExactTextCount(body, "执行已批准的 Agent 命令", 2, "Approved Codex-ready action plus selected-detail count");
    requireExactTextCount(body, "复制交接信息", 1, "Approved handoff copy count");
    requireTextOrder(body, ["项目", goalId, "执行已批准的 Agent 命令"], "Approved project-first card identity");

    await navigateTo(page, `${baseUrl}/?view=ops&statusUrl=/${staleHistoryApprovedFixtureName}&goalId=${goalId}&actionKind=all`);
    body = await readBodyText(page, { requiredText: "复制交接信息" });
    requireTexts(body, [
      "1 个操作",
      "项目",
      goalId,
      "Codex",
      "执行已批准的 Agent 命令",
      "已批准交接",
      "已批准 Agent 命令",
      "已批准命令",
      "复制交接信息",
    ], "current queue over stale history dashboard");
    forbidTexts(body, [
      "审阅控制者接入",
      "需要批准",
      "批准后可执行 Agent 命令",
      "操作者确认试运行草稿",
      "Operator Review Packet",
      "Copy Review Packet",
    ], "Current queue approved action was replaced by stale run-history gate");
    requireExactTextCount(body, "执行已批准的 Agent 命令", 2, "Current queue approved action plus selected-detail count over stale history");
    requireExactTextCount(body, "复制交接信息", 1, "Current queue approved handoff copy count over stale history");
    requireTextOrder(body, ["项目", goalId, "执行已批准的 Agent 命令"], "Current queue approved project-first card identity");
    if (pageErrors.length) {
      throw new Error(`Dashboard page errors: ${pageErrors.join(" | ")}`);
    }
    console.log("dashboard-operator-gate-browser-smoke ok");
  } finally {
    await cleanupBrowserSmoke({
      browser,
      fixturePaths: [fixturePath, approvedFixturePath, staleHistoryApprovedFixturePath],
      server,
    });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});

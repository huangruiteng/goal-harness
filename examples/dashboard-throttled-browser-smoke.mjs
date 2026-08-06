#!/usr/bin/env node
// Browser-level smoke for the dashboard throttled-quota quiet state.

import { spawn } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanupBrowserSmoke, launchBrowser, loadPlaywright } from "./dashboard-browser-smoke-support.mjs";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dashboardDir = resolve(repoRoot, "apps/presentation/dashboard");
const fixtureName = "status.throttled.browser-smoke.json";
const fixturePath = resolve(dashboardDir, "public", fixtureName);
const pausedFixtureName = "status.paused.browser-smoke.json";
const pausedFixturePath = resolve(dashboardDir, "public", pausedFixtureName);
const port = Number(process.env.LOOPX_DASHBOARD_SMOKE_PORT ?? "5191");

const statusFixture = {
  ok: true,
  registry: "./fixtures/registry.json",
  runtime_root: "./fixtures/runtime",
  goal_count: 1,
  run_count: 1,
  contract: {
    ok: true,
    summary: { errors: 0, warnings: 0, checks: 1 },
    errors: [],
    warnings: [],
    checks: ["public-safe throttled dashboard fixture"],
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
    checks: ["public-safe throttled dashboard fixture"],
  },
  attention_queue: {
    available: true,
    item_count: 1,
    needs_user_or_controller: 0,
    needs_controller: 0,
    needs_codex: 1,
    watching_external_evidence: 0,
    items: [
      {
        goal_id: "throttled-codex",
        status: "state_refreshed",
        waiting_on: "codex",
        severity: "action",
        recommended_action: "continue only after compute quota opens",
        source: "fixture",
        lifecycle_phase: "refreshed",
        lifecycle_flags: ["refreshed"],
        quota: {
          compute: 0.5,
          window_hours: 24,
          slot_minutes: 1,
          allowed_slots: 720,
          spent_slots: 720,
          state: "throttled",
          reason: "0.5 compute quota spent 720/720 minute-slots in this window",
        },
      },
    ],
  },
  run_history: {
    available: true,
    goal_count: 1,
    run_count: 1,
    goals: [
      {
        id: "throttled-codex",
        domain: "quota-fixture",
        status: "active",
        lifecycle_phase: "refreshed",
        lifecycle_flags: ["refreshed"],
        registry_member: true,
        legacy_runtime_goal: false,
        adapter_kind: "read_only_project_map_v0",
        adapter_status: "connected-read-only",
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
        quota: {
          compute: 0.5,
          window_hours: 24,
          slot_minutes: 1,
          allowed_slots: 720,
          spent_slots: 720,
          state: "throttled",
          reason: "0.5 compute quota spent 720/720 minute-slots in this window",
        },
        index_exists: true,
        raw_index_records: 1,
        unique_runs: 1,
        latest_runs: [
          {
            generated_at: "2026-01-01T00:00:00+00:00",
            goal_id: "throttled-codex",
            classification: "state_refreshed",
            lifecycle_phase: "refreshed",
            lifecycle_flags: ["refreshed"],
            recommended_action: "continue only after compute quota opens",
            health_check: "fixture 1/1",
          },
        ],
      },
    ],
    recent_runs: [
      {
        generated_at: "2026-01-01T00:00:00+00:00",
        goal_id: "throttled-codex",
        classification: "state_refreshed",
        lifecycle_phase: "refreshed",
        lifecycle_flags: ["refreshed"],
        recommended_action: "continue only after compute quota opens",
        health_check: "fixture 1/1",
      },
    ],
  },
};

const pausedGoalId = "paused-codex";
const pausedStatusFixture = structuredClone(statusFixture);
pausedStatusFixture.attention_queue.items[0] = {
  ...pausedStatusFixture.attention_queue.items[0],
  goal_id: pausedGoalId,
  recommended_action: "wait until automatic compute resumes",
  quota: {
    ...pausedStatusFixture.attention_queue.items[0].quota,
    spent_slots: 12,
    state: "paused",
    reason: "automatic compute paused by fixture",
  },
};
pausedStatusFixture.run_history.goals[0] = {
  ...pausedStatusFixture.run_history.goals[0],
  id: pausedGoalId,
  quota: pausedStatusFixture.attention_queue.items[0].quota,
  latest_runs: pausedStatusFixture.run_history.goals[0].latest_runs.map((run) => ({
    ...run,
    goal_id: pausedGoalId,
    recommended_action: "wait until automatic compute resumes",
  })),
};
pausedStatusFixture.run_history.recent_runs = pausedStatusFixture.run_history.recent_runs.map((run) => ({
  ...run,
  goal_id: pausedGoalId,
  recommended_action: "wait until automatic compute resumes",
}));

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
  await writeFile(pausedFixturePath, JSON.stringify(pausedStatusFixture, null, 2) + "\n", "utf-8");

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
    await page.goto(`${baseUrl}/?view=ops&statusUrl=/${fixtureName}&goalId=throttled-codex&actionKind=all`, { waitUntil: "networkidle" });
    await page.getByText("用户操作").waitFor();
    const body = await page.locator("body").innerText();
    const required = [
      "0 个操作",
      "当前没有需要用户处理的操作。",
      "配额 0.5",
      "本窗口配额已用完",
      "720/720 个执行槽位",
    ];
    const missing = required.filter((text) => !body.includes(text));
    if (missing.length) {
      throw new Error(`Missing dashboard text: ${missing.join(", ")}\n${body.slice(0, 4_000)}`);
    }
    const forbidden = [
      "1 个操作",
      "让 Codex 继续",
      "Codex 可以继续",
      "continue_from_refreshed_state",
    ];
    const present = forbidden.filter((text) => body.includes(text));
    if (present.length) {
      throw new Error("Throttled goal leaked into user actions: " + present.join(", "));
    }

    await page.goto(`${baseUrl}/?view=ops&statusUrl=/${pausedFixtureName}&goalId=${pausedGoalId}&actionKind=all`, { waitUntil: "networkidle" });
    await page.getByText("用户操作").waitFor();
    const pausedBody = await page.locator("body").innerText();
    const pausedRequired = [
      "0 个操作",
      "自动推进已暂停",
      "自动计算已暂停",
      "wait_for_control_plane",
    ];
    const pausedMissing = pausedRequired.filter((text) => !pausedBody.includes(text));
    if (pausedMissing.length) {
      throw new Error(`Missing paused dashboard text: ${pausedMissing.join(", ")}\n${pausedBody.slice(0, 4_000)}`);
    }
    const pausedForbidden = [
      "让 Codex 继续",
      "Codex 可以继续",
      "Codex 可以执行",
      "continue_from_refreshed_state",
      "continue_codex_action",
    ];
    const pausedPresent = pausedForbidden.filter((text) => pausedBody.includes(text));
    if (pausedPresent.length) {
      throw new Error(`Paused goal leaked into executable actions: ${pausedPresent.join(", ")}`);
    }
    if (pageErrors.length) {
      throw new Error(`Dashboard page errors: ${pageErrors.join(" | ")}`);
    }
    console.log("dashboard-throttled-browser-smoke ok");
  } finally {
    await cleanupBrowserSmoke({ browser, fixturePaths: [fixturePath, pausedFixturePath], server });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});

#!/usr/bin/env node
// Browser-level smoke for the canonical Chinese-first dashboard home.

import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanupBrowserSmoke, launchBrowser } from "./dashboard-browser-smoke-support.mjs";

const require = createRequire(import.meta.url);
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dashboardDir = resolve(repoRoot, "apps/presentation/dashboard");
const fixtureName = "status.home.browser-smoke.json";
const fixturePath = resolve(dashboardDir, "public", fixtureName);
const visualOutputDir = resolve(repoRoot, "output/playwright/dashboard-home-visual-acceptance");
const port = Number(process.env.LOOPX_DASHBOARD_HOME_SMOKE_PORT ?? "5194");

const quotaEligible = {
  compute: 1,
  window_hours: 24,
  slot_minutes: 1,
  allowed_slots: 1440,
  spent_slots: 3,
  state: "eligible",
  reason: "fixture eligible quota",
};

const quotaFocusWait = {
  ...quotaEligible,
  spent_slots: 8,
  state: "focus_wait",
  reason: "fixture outcome floor blocks further spend",
  handoff_outcome_floor_block: true,
  safe_bypass_allowed: true,
  safe_bypass_kind: "outcome_floor_recovery",
  safe_bypass_policy: "Outcome-floor recovery only: attempt one bounded ranker_or_cross_domain_evidence evidence segment or write back a concrete blocker.",
  must_advance: ["ranker_or_cross_domain_evidence"],
  avoid: ["clean_downstream_surface_propagation", "synthetic_only_test_chain"],
  post_handoff_outcome_gap_streak: 3,
};

const goalSpecs = [
  {
    id: "showcase-user-gate-safe-side-path",
    domain: "showcase-user-gate-fixture",
    status: "state_refreshed",
    waiting_on: "user_or_controller",
    quota: { ...quotaEligible, state: "operator_gate" },
    userTodos: { open: 1, done: 3, total: 4, next: "请确认 owner 选项 A/B 的取舍。" },
    userTodoItems: [
      { done: false, text: "请确认 owner 选项 A/B 的取舍；未确认前不推进 gated route。" },
      { done: true, text: "已读完核心迁移文档第 8 节，并确认当前结论。" },
      { done: true, text: "已确认 item embedding 不阻塞当前 P0 i2i 路径。" },
      { done: true, text: "已确认 P0 degrade 走统一标准品策略。" },
    ],
    agentTodos: { open: 4, done: 0, total: 4, next: "推进与 owner 决策独立的 safe side path。" },
    agentTodoItems: [
      { done: false, text: "推进与 owner 决策独立的 safe side path，输出公开可复现证据。" },
      { done: false, text: "复查公开边界，确认 showcase 数据不包含内部项目名或生产细节。" },
      { done: false, text: "按安全再生成计划只写私有 tmp_data，不触碰生产配置。" },
      { done: false, text: "把关闭的 P0 阻塞和剩余 gate 写回迁移目标状态。" },
    ],
    latest: {
      generated_at: "2026-01-01T00:00:00+00:00",
      classification: "state_refreshed",
      delivery_batch_scale: "multi_surface",
      health_check: "fixture platform migration state",
      json_exists: true,
      markdown_exists: true,
    },
  },
  {
    id: "showcase-creator-operator",
    domain: "creator-operator-fixture",
    status: "state_refreshed",
    waiting_on: "codex",
    quota: quotaEligible,
    userTodos: { open: 0, done: 1, total: 1, next: null },
    userTodoItems: [
      { done: true, text: "用户已授权 creator operator 使用合成素材主动推进。" },
    ],
    agentTodos: { open: 4, done: 0, total: 4, next: "整理热点、洞察、语料和创作 backlog。" },
    agentTodoItems: [
      { done: false, text: "整理各平台热点，形成按偏好排序的创作候选。" },
      { done: false, text: "提炼热点洞察，补充素材库和语料库。" },
      { done: false, text: "把可用素材转成文章或视频脚本草稿。" },
      { done: false, text: "每次产出都写回 showcase backlog 和证据 ledger。" },
    ],
    latest: {
      generated_at: "2026-01-01T00:01:00+00:00",
      classification: "state_refreshed",
      delivery_batch_scale: "implementation",
      health_check: "fixture creator-operator active-delivery authorization",
      json_exists: true,
      markdown_exists: true,
    },
  },
  {
    id: "showcase-side-agent-self-iteration",
    domain: "side-bypass-fixture",
    status: "state_refreshed",
    waiting_on: "codex",
    quota: quotaFocusWait,
    userTodos: { open: 1, done: 0, total: 1, next: "提供或批准 hard_category held-out / paired eval 范围。" },
    userTodoItems: [
      { done: false, text: "提供或批准 candidate-specific hard_category held-out / paired eval 范围。" },
    ],
    agentTodos: { open: 3, done: 1, total: 4, next: "产出排序器 / 跨域证据，否则不花配额写 blocker。" },
    agentTodoItems: [
      { done: false, text: "产出排序器 / 跨域证据，证明不是单面小步。" },
      { done: false, text: "若证据范围仍不可用，写回具体 blocker 并停止花配额。" },
      { done: false, text: "禁止继续 summary / queue / field 的表层传播。" },
      { done: true, text: "已识别 outcome_floor_recovery 分支并拦住普通 delivery。" },
    ],
    handoffReadiness: {
      ready: true,
      codex_ready: true,
      source: "project_asset",
      quota_state: "focus_wait",
      handoff_status: "post_handoff_run_seen",
      post_handoff_run_seen: true,
      post_handoff_outcome_gap_streak: 3,
      post_handoff_latest_run: {
        generated_at: "2026-01-01T00:02:00+00:00",
        classification: "state_refreshed",
        delivery_batch_scale: "single_surface",
        delivery_outcome: "outcome_gap",
        health_check: "fixture side-bypass outcome gap",
        json_exists: true,
        markdown_exists: true,
      },
    },
    latest: {
      generated_at: "2026-01-01T00:02:00+00:00",
      classification: "state_refreshed",
      delivery_batch_scale: "single_surface",
      delivery_outcome: "outcome_gap",
      health_check: "fixture side-bypass outcome gap",
      json_exists: true,
      markdown_exists: true,
    },
  },
  {
    id: "loopx-meta",
    domain: "loopx-fixture",
    status: "dashboard_home_chinese_operator_copy_contract",
    waiting_on: "codex",
    quota: { ...quotaEligible, spent_slots: 9 },
    userTodos: { open: 0, done: 1, total: 1, next: null },
    userTodoItems: [
      { done: true, text: "用户确认分享页应以中文控制面为主屏。" },
    ],
    agentTodos: { open: 3, done: 1, total: 4, next: "拆分 dependency blocker 和 current-goal blocker。" },
    agentTodoItems: [
      { done: false, text: "拆分依赖阻塞和当前目标阻塞，避免 meta 可执行回合空转。" },
      {
        done: false,
        text: "增加自动 backlog 候选面，让 P1/P2 可持续推进。",
        todo_id: "todo_dashboard_search_meta_backlog",
        priority: "P1",
        status: "open",
        task_class: "advancement_task",
        action_kind: "dashboard_todo_search_fixture",
        claimed_by: "codex-side-bypass",
        evidence: "A deliberately long public-safe evidence reference proves that Agent cards keep metadata inside their responsive column without widening the card or the page.",
      },
      {
        done: false,
        text: "重复来源不应生成第二张 Todo 卡片。",
        todo_id: "todo_dashboard_search_meta_backlog",
        priority: "P1",
        status: "open",
        task_class: "advancement_task",
        action_kind: "dashboard_todo_search_fixture",
        claimed_by: "codex-side-bypass",
      },
      { done: false, text: "统一多项目看板的 serve-status --global-registry 命令说明。" },
      { done: true, text: "已硬化 heartbeat prompt，依赖项目 todo 不再吃掉当前 goal turn。" },
    ],
    controlPlane: {
      self_repair: {
        enabled: true,
        allow_health_blocker_repair: true,
        allow_waiting_projection_repair: true,
      },
    },
    orchestration: {
      mode: "multi_subagent",
      spawn_allowed: true,
      max_children: 2,
      allowed_domains: ["docs", "validation"],
    },
    latest: {
      generated_at: "2026-01-01T00:03:00+00:00",
      classification: "dashboard_home_chinese_operator_copy_contract",
      delivery_batch_scale: "multi_surface",
      delivery_outcome: "primary_goal_outcome",
      health_check: "fixture home copy contract",
      json_exists: true,
      markdown_exists: true,
    },
  },
];

function projectAssetFor(spec) {
  return {
    owner: spec.waiting_on,
    gate: spec.userTodos.open > 0 ? "user_todo" : "none",
    next_action: spec.agentTodos.next ?? "continue from current fixture state",
    stop_condition: "fixture stop condition",
    user_todos: spec.userTodos,
    agent_todos: spec.agentTodos,
    quota: spec.quota,
    control_plane: spec.controlPlane,
    orchestration: spec.orchestration,
    latest_validation: {
      generated_at: spec.latest.generated_at,
      classification: spec.latest.classification,
      summary: spec.latest.health_check,
    },
  };
}

function todoGroupFor(spec, role) {
  const summary = role === "user" ? spec.userTodos : spec.agentTodos;
  const rawItems = role === "user" ? spec.userTodoItems : spec.agentTodoItems;
  return {
    source_section: role === "user" ? "User Todo / Owner Review Reading Queue" : "Agent Todo",
    total_count: summary.total,
    open_count: summary.open,
    done_count: summary.done,
    items: (rawItems ?? []).map((item, index) => ({
      index: index + 1,
      done: item.done,
      text: item.text,
      todo_id: item.todo_id,
      priority: item.priority,
      status: item.status,
      task_class: item.task_class,
      action_kind: item.action_kind,
      claimed_by: item.claimed_by,
      evidence: item.evidence,
      review_materials: [],
    })),
  };
}

const statusFixture = {
  ok: true,
  registry: "./fixtures/registry.global.json",
  runtime_root: "./fixtures/runtime",
  goal_count: goalSpecs.length,
  run_count: goalSpecs.length,
  status_contract: {
    schema_version: 2,
    minimum_dashboard_schema_version: 2,
    producer: "loopx status",
    reload_hint: "scripts/macos-dashboard-launchagent.sh restart",
  },
  contract: {
    ok: true,
    summary: { errors: 0, warnings: 0, checks: 1 },
    errors: [],
    warnings: [],
    checks: ["public-safe dashboard home fixture"],
  },
  global_registry: {
    available: true,
    ok: true,
    registry: "./fixtures/registry.global.json",
    current_registry: "./fixtures/registry.global.json",
    current_registry_is_global: true,
    global_goal_count: goalSpecs.length,
    current_goal_count: goalSpecs.length,
    source_registry_count: 4,
    summary: { high: 0, action: 0, info: 0, checks: 1, findings: 0 },
    findings: [],
    checks: ["public-safe dashboard home fixture"],
  },
  attention_queue: {
    available: true,
    item_count: goalSpecs.length,
    needs_user_or_controller: 1,
    needs_controller: 0,
    needs_codex: 3,
    watching_external_evidence: 0,
    autonomous_backlog_candidates: {
      source: "attention_queue.agent_todos",
      open_count: 2,
      items: [
        {
          goal_id: "loopx-meta",
          status: "dashboard_home_chinese_operator_copy_contract",
          waiting_on: "codex",
          quota_state: "eligible",
          priority: "P1",
          todo_index: 2,
          text: "增加自动 backlog 候选面，让 P1/P2 可持续推进。",
          source: "agent_todos",
        },
        {
          goal_id: "showcase-creator-operator",
          status: "state_refreshed",
          waiting_on: "codex",
          quota_state: "eligible",
          priority: "P2",
          todo_index: 1,
          text: "整理热点、洞察、语料和创作 backlog。",
          source: "agent_todos",
        },
      ],
    },
    items: goalSpecs.map((spec) => {
      const sideBypass = goalSpecs.find((goal) => goal.id === "showcase-side-agent-self-iteration");
      const sideBypassUserTodo = sideBypass?.userTodoItems?.find((todo) => !todo.done);
      return {
        goal_id: spec.id,
        status: spec.status,
        waiting_on: spec.waiting_on,
        severity: "action",
        recommended_action: spec.agentTodos.next ?? "continue from current fixture state",
        project_asset: projectAssetFor(spec),
        handoff_readiness: spec.handoffReadiness,
        quota: spec.quota,
        control_plane: spec.controlPlane,
        user_todos: todoGroupFor(spec, "user"),
        agent_todos: todoGroupFor(spec, "agent"),
        dependency_blockers: spec.id === "loopx-meta" && sideBypassUserTodo
          ? {
              source: "attention_queue.user_todos",
              open_count: 1,
              items: [{
                goal_id: "showcase-side-agent-self-iteration",
                status: "state_refreshed",
                waiting_on: "codex",
                severity: "action",
                index: 1,
                text: sideBypassUserTodo.text,
                source: "user_todos",
              }],
            }
          : null,
        source: "fixture",
      };
    }),
  },
  run_history: {
    available: true,
    goal_count: goalSpecs.length,
    run_count: goalSpecs.length,
    goals: goalSpecs.map((spec) => ({
      id: spec.id,
      domain: spec.domain,
      status: spec.status,
      lifecycle_phase: "fixture",
      lifecycle_flags: ["fixture"],
      registry_member: true,
      legacy_runtime_goal: false,
      adapter_kind: "dashboard_home_fixture",
      adapter_status: "connected",
      quota: spec.quota,
      control_plane: spec.controlPlane,
      spawn_policy: spec.orchestration,
      index_exists: true,
      raw_index_records: 1,
      unique_runs: 1,
      latest_runs: [{ ...spec.latest, goal_id: spec.id }],
    })),
    recent_runs: goalSpecs.map((spec) => ({ ...spec.latest, goal_id: spec.id })),
  },
  usage_summary: {
    available: true,
    source: "run_history",
    sample_run_count: 4,
    proxy_note: "public-safe dashboard home fixture",
    totals: {
      runs_24h: 8,
      runs_7d: 8,
      quota_spend_slots_24h: 6,
      quota_spend_slots_7d: 6,
      automation_run_count_24h: 5,
      automation_run_count_7d: 5,
      progress_signal_run_count_24h: 4,
      progress_signal_run_count_7d: 4,
    },
    goals: goalSpecs.map((spec, index) => ({
      goal_id: spec.id,
      runs_24h: 2,
      runs_7d: 2,
      quota_spend_slots_24h: index,
      quota_spend_slots_7d: index,
      automation_run_count_24h: 1,
      automation_run_count_7d: 1,
      progress_signal_run_count_24h: 1,
      progress_signal_run_count_7d: 1,
      project_share_24h: 0.25,
    })),
  },
  todo_index: {
    schema_version: "todo_index_v0",
    source: "attention_queue_and_rollout_event_log",
    total_count: 2,
    current_projected_count: 1,
    rollout_event_count: 3,
    item_limit: 240,
    items: [
      {
        schema_version: "todo_index_item_v0",
        goal_id: "loopx-meta",
        index: 1,
        done: false,
        text: "todo update recorded for todo_dashboard_search_meta_backlog",
        title: "todo update recorded for todo_dashboard_search_meta_backlog",
        todo_id: "todo_dashboard_search_meta_backlog",
        role: "agent",
        status: "open",
        source: "rollout_event_log",
        event_count: 1,
        event_kinds: ["todo_update"],
        latest_event_kind: "todo_update",
        latest_event_at: "2026-06-22T12:29:47Z",
        latest_event_status: "open",
        agent_id: "codex-side-bypass",
      },
      {
        schema_version: "todo_index_item_v0",
        goal_id: "loopx-meta",
        index: 0,
        done: false,
        text: "todo update recorded for todo_f2760d7e328f",
        title: "todo update recorded for todo_f2760d7e328f",
        todo_id: "todo_f2760d7e328f",
        role: "agent",
        status: "open",
        source: "rollout_event_log",
        event_count: 2,
        event_kinds: ["todo_add", "todo_update"],
        latest_event_kind: "todo_update",
        latest_event_at: "2026-06-22T12:28:47Z",
        latest_event_status: "open",
        agent_id: "codex-main-control",
      },
    ],
  },
  decision_freshness_summary: {
    available: true,
    source: "run_history",
    sample_run_count: 4,
    window_days: 7,
    proxy_note: "public-safe dashboard home fixture",
    summary: {
      decision_count: 1,
      stale_count: 1,
      rebase_required_count: 1,
      fresh_count: 0,
    },
    items: [
      {
        goal_id: "loopx-meta",
        decision_kind: "operator_gate",
        decision_at: "2025-12-24T00:00:00+00:00",
        classification: "operator_gate_approved",
        age_days: 8.4,
        stale_by_age: true,
        newer_event_count_7d: 2,
        newer_event_classes_7d: {
          accounting: 0,
          decision: 0,
          evidence: 1,
          state: 1,
          work: 0,
        },
        freshness_state: "stale_rebase_required",
        requires_decision_point_rebase: true,
        reason: "fixture stale operator gate",
      },
    ],
  },
};

function loadPlaywright() {
  const candidates = [
    process.env.LOOPX_PLAYWRIGHT_PACKAGE,
    resolve(homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"),
  ].filter(Boolean);

  try {
    return require("playwright");
  } catch {
    // Try explicit or bundled local packages below.
  }

  for (const candidate of candidates) {
    if (!candidate || !existsSync(candidate)) {
      continue;
    }
    try {
      return require(candidate);
    } catch {
      // Keep looking.
    }
  }

  throw new Error("Playwright package not found; install playwright or set LOOPX_PLAYWRIGHT_PACKAGE");
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

function startDashboardServer() {
  const viteBin = resolve(dashboardDir, "node_modules/vite/bin/vite.js");
  if (!existsSync(viteBin)) {
    throw new Error(`Vite package not installed: ${viteBin}`);
  }
  const nodeBin = [
    process.env.LOOPX_NODE_BIN,
    "/opt/homebrew/bin/node",
    "/usr/local/bin/node",
    process.execPath,
  ].find((candidate) => candidate && existsSync(candidate));
  return spawn(nodeBin, [viteBin, "--host", "127.0.0.1", "--port", String(port), "--strictPort"], {
    cwd: dashboardDir,
    env: {
      ...process.env,
      PATH: ["/opt/homebrew/bin", "/usr/local/bin", process.env.PATH].filter(Boolean).join(":"),
    },
    stdio: "ignore",
  });
}

function formatOverflowOffender(offender) {
  const id = offender.testid ? `[data-testid="${offender.testid}"]` : offender.tag;
  return `${id} left=${offender.left} right=${offender.right} width=${offender.width} "${offender.text}"`;
}

async function assertNoHorizontalOverflow(page, label) {
  const report = await page.evaluate(() => {
    const viewportWidth = window.innerWidth;
    const root = document.documentElement;
    const body = document.body;
    const scrollWidth = Math.max(root.scrollWidth, body?.scrollWidth ?? 0);
    const offenders = [];
    for (const element of Array.from(document.body.querySelectorAll("*"))) {
      const style = window.getComputedStyle(element);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) {
        continue;
      }
      const rect = element.getBoundingClientRect();
      if (rect.width < 1 || rect.height < 1) {
        continue;
      }
      if (rect.left < -2 || rect.right > viewportWidth + 2) {
        offenders.push({
          tag: element.tagName.toLowerCase(),
          testid: element.getAttribute("data-testid"),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          text: (element.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 90),
        });
      }
      if (offenders.length >= 8) {
        break;
      }
    }
    return {
      viewportWidth,
      scrollWidth,
      overflowPx: Math.max(0, scrollWidth - viewportWidth),
      offenders,
    };
  });
  if (report.overflowPx > 2) {
    const offenders = report.offenders.map(formatOverflowOffender).join(" | ");
    throw new Error(`${label} horizontal overflow: viewport=${report.viewportWidth} scroll=${report.scrollWidth} offenders=${offenders || "none"}`);
  }
}

async function assertNoPanelContentOverflow(page, label) {
  const offenders = await page.evaluate(() => Array.from(document.querySelectorAll([
    '[data-testid="agent-management-row"]',
    '[data-testid="usage-goal-table"]',
    '[data-testid="event-ledger-goal-table"]',
    '[data-testid="decision-freshness-table"]',
  ].join(","))).filter((element) => element.scrollWidth > element.clientWidth + 2).map((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    testid: element.getAttribute("data-testid"),
  })));
  if (offenders.length) {
    throw new Error(`${label} panel content overflow: ${JSON.stringify(offenders)}`);
  }
}

async function assertDecisionFrameVisible(page, label) {
  const decisionFrame = page.locator('[data-testid^="share-decision-frame-"]').first();
  await decisionFrame.scrollIntoViewIfNeeded();
  const metrics = await decisionFrame.evaluate((element) => {
    const rect = element.getBoundingClientRect();
    return {
      left: Math.round(rect.left),
      right: Math.round(rect.right),
      top: Math.round(rect.top),
      bottom: Math.round(rect.bottom),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      text: (element.textContent ?? "").replace(/\s+/g, " ").trim(),
    };
  });
  if (metrics.left < 0 || metrics.right > metrics.viewportWidth || metrics.top < 0 || metrics.bottom > metrics.viewportHeight) {
    throw new Error(`${label} decision frame is not fully visible: ${JSON.stringify(metrics)}`);
  }
  const requiredFrameText = ["等待方", "推荐动作", "安全边界", "首个用户 Todo", "最高优 Agent Todo"];
  const missing = requiredFrameText.filter((text) => !metrics.text.includes(text));
  if (missing.length) {
    throw new Error(`${label} decision frame missing labels: ${missing.join(", ")}`);
  }
}

async function captureHomeVisualAcceptance(page, url, label) {
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForSelector('[data-testid="share-overview"]', { timeout: 10_000 });
  await assertNoHorizontalOverflow(page, `${label} top`);
  await page.screenshot({
    path: resolve(visualOutputDir, `${label}-home-top.png`),
    fullPage: false,
    animations: "disabled",
  });
  await assertDecisionFrameVisible(page, label);
  await assertNoHorizontalOverflow(page, `${label} decision frame`);
  await page.screenshot({
    path: resolve(visualOutputDir, `${label}-decision-frame.png`),
    fullPage: false,
    animations: "disabled",
  });
}

async function main() {
  const { chromium } = loadPlaywright();
  await writeFile(fixturePath, JSON.stringify(statusFixture, null, 2) + "\n", "utf-8");
  await mkdir(visualOutputDir, { recursive: true });

  const server = startDashboardServer();
  let browser;
  try {
    const baseUrl = `http://127.0.0.1:${port}`;
    await waitForDashboard(baseUrl);
    browser = await launchBrowser(chromium);
    const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.goto(`${baseUrl}/?statusUrl=/${fixtureName}`, { waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="share-overview"]', { timeout: 10_000 });

    const body = await page.locator("body").innerText();
    const required = [
      "把多项目 Agent 工作变成可管理的 Todo、证据和配额",
      "0617 用户确认",
      "请确认 owner 选项 A/B 的取舍",
      "创作者运营",
      "热点",
      "合成案例",
      "平级 Agent 自迭代",
      "需要 Codex 恢复",
      "排序器 / 跨域证据",
      "具体 blocker",
      "LoopX 自举",
      "配额守卫",
      "状态写回",
      "第一屏决策帧",
      "等待方",
      "推荐动作",
      "安全边界",
      "首个用户 Todo",
      "最高优 Agent Todo",
      "fixture stop condition",
      "前 4 个 Todo",
      "可自动推进候选",
      "待用户",
      "待 Agent",
      "已完成",
      "依赖阻塞",
      "决策需重新确认",
      "审批或转交前先重读",
      "这不是仓库回滚",
      "推进与 owner 决策独立的 safe side path",
      "拆分依赖阻塞和当前目标阻塞",
    ];
    const missing = required.filter((text) => !body.includes(text));
    if (missing.length) {
      throw new Error(`Missing dashboard home text: ${missing.join(", ")}`);
    }

    const forbidden = [
      "[plugin:vite:oxc]",
      "Transform failed",
      "active internal-slot <= 2",
      "single_surface",
      "quota_slot_spent",
      "focus_wait",
      "状态服务契约过旧",
    ];
    const present = forbidden.filter((text) => body.includes(text));
    if (present.length) {
      throw new Error(`Dashboard home leaked raw machine/debug text: ${present.join(", ")}`);
    }

    const url = new URL(page.url());
    if (url.searchParams.get("view")) {
      throw new Error(`Canonical home should not keep a view search param: ${page.url()}`);
    }

    await captureHomeVisualAcceptance(page, `${baseUrl}/?statusUrl=/${fixtureName}`, "desktop");
    const mobilePage = await browser.newPage({
      isMobile: true,
      viewport: { width: 390, height: 900 },
    });
    mobilePage.on("pageerror", (error) => pageErrors.push(`mobile: ${error.message}`));
    try {
      await captureHomeVisualAcceptance(mobilePage, `${baseUrl}/?statusUrl=/${fixtureName}`, "mobile");
    } finally {
      await mobilePage.close();
    }

    await page.goto(`${baseUrl}/?view=ops&goalId=loopx-meta&statusUrl=/${fixtureName}`, { waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="operator-mental-model-panel"]', { timeout: 10_000 });
    await page.setViewportSize({ width: 1440, height: 900 });
    await assertNoHorizontalOverflow(page, "ops 1440x900");
    await assertNoPanelContentOverflow(page, "ops 1440x900");
    await page.screenshot({
      path: resolve(visualOutputDir, "ops-1440x900.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 1920, height: 1080 });
    await assertNoHorizontalOverflow(page, "ops 1920x1080");
    await assertNoPanelContentOverflow(page, "ops 1920x1080");
    await page.screenshot({
      path: resolve(visualOutputDir, "ops-1920x1080.png"),
      fullPage: true,
    });
    const operatorModelText = await page.locator('[data-testid="operator-mental-model-panel"]').innerText();
    const requiredOperatorModelText = [
      "操作者概览",
      "目标",
      "下一步",
      "需要你判断",
      "证据",
      "是否可继续",
    ];
    const missingOperatorModelText = requiredOperatorModelText.filter((text) => !operatorModelText.includes(text));
    if (missingOperatorModelText.length) {
      throw new Error(`Missing operator mental model text: ${missingOperatorModelText.join(", ")}`);
    }
    await page.waitForSelector('[data-testid="project-todo-explorer"]', { timeout: 10_000 });
    const todoExplorer = page.locator('[data-testid="project-todo-explorer"]');
    const initialTodoExplorerText = await todoExplorer.innerText();
    const requiredTodoExplorerText = [
      "项目 Todo 浏览器",
      "全部项目",
      "todo_dashboard_search_meta_backlog",
      "dashboard_todo_search_fixture",
      "claimed_by=codex-side-bypass",
    ];
    const missingTodoExplorerText = requiredTodoExplorerText.filter((text) => !initialTodoExplorerText.includes(text));
    if (missingTodoExplorerText.length) {
      throw new Error(`Missing project todo explorer text: ${missingTodoExplorerText.join(", ")}`);
    }
    await page.locator('[data-testid="project-todo-search-input"]').fill("todo_dashboard_search_meta_backlog");
    const deduplicatedTodoCount = await page.locator('[data-testid="project-todo-result"]').count();
    if (deduplicatedTodoCount !== 1) {
      throw new Error(`Project todo explorer rendered ${deduplicatedTodoCount} copies of one stable todo id.`);
    }
    const filteredTodoExplorerText = await todoExplorer.innerText();
    if (!filteredTodoExplorerText.includes("1/")) {
      throw new Error(`Project todo explorer did not narrow search results: ${filteredTodoExplorerText}`);
    }
    if (!filteredTodoExplorerText.includes("增加自动 backlog 候选面")) {
      throw new Error("Project todo explorer search lost the matching todo body.");
    }
    if (filteredTodoExplorerText.includes("todo update recorded for todo_dashboard_search_meta_backlog")) {
      throw new Error("Project todo explorer preferred a historical event over the current todo projection.");
    }
    await page.getByLabel("Todo 所属项目").selectOption("showcase-creator-operator");
    const projectFilteredTodoExplorerText = await todoExplorer.innerText();
    if (!projectFilteredTodoExplorerText.includes("没有 Todo 匹配“todo_dashboard_search_meta_backlog”")) {
      throw new Error("Project todo explorer did not apply the selected project filter.");
    }
    await page.getByLabel("Todo 所属项目").selectOption("all");
    await page.locator('[data-testid="project-todo-search-input"]').fill("todo_f2760d7e328f");
    const historicalTodoExplorerText = await todoExplorer.innerText();
    const requiredHistoricalTodoText = [
      "todo_f2760d7e328f",
      "source=rollout_event_log",
      "event=todo_update",
      "todo update recorded for todo_f2760d7e328f",
    ];
    const missingHistoricalTodoText = requiredHistoricalTodoText.filter((text) => !historicalTodoExplorerText.includes(text));
    if (missingHistoricalTodoText.length) {
      throw new Error(`Project todo explorer did not expose historical todo index text: ${missingHistoricalTodoText.join(", ")}`);
    }
    await page.waitForSelector('[data-testid="control-plane-settings-panel"]', { timeout: 10_000 });
    const settingsText = await page.locator('[data-testid="control-plane-settings-panel"]').innerText();
    const requiredSettings = [
      "控制面设置",
      "配额 1",
      "自动修复已开启",
      "健康问题修复=开启",
      "等待状态修复=开启",
      "心跳安装",
      "已观测到",
      "多 Agent",
      "最多子 Agent=2",
      "允许的领域=docs,validation",
    ];
    const missingSettings = requiredSettings.filter((text) => !settingsText.includes(text));
    if (missingSettings.length) {
      throw new Error(`Missing control-plane settings text: ${missingSettings.join(", ")}`);
    }
    await page.locator('[data-testid="control-plane-quota-compute"]').fill("1.5");
    const updatedSettingsText = await page.locator('[data-testid="control-plane-settings-panel"]').innerText();
    if (!updatedSettingsText.includes("有未保存修改")) {
      throw new Error("Control-plane settings draft did not enter dirty state after editing quota.");
    }
    const settingsCommand = await page.locator('[data-testid="control-plane-settings-command-preview"]').innerText();
    const requiredCommandParts = [
      "configure-goal",
      "--goal-id loopx-meta",
      "--quota-compute 1.5",
      "--quota-window-hours 24",
      "--self-repair-enabled",
      "--self-repair-health",
      "--self-repair-waiting-projection",
      "--multi-subagent-feature enabled",
      "--max-children 2",
      "--allowed-domain docs",
      "--allowed-domain validation",
    ];
    const missingCommandParts = requiredCommandParts.filter((text) => !settingsCommand.includes(text));
    if (missingCommandParts.length) {
      throw new Error(`Missing control-plane settings command text: ${missingCommandParts.join(", ")}`);
    }
    if (settingsCommand.includes("--execute")) {
      throw new Error("Control-plane command preview must stay dry-run by default.");
    }

    await page.goto(`${baseUrl}/?view=ops&goalId=showcase-side-agent-self-iteration&statusUrl=/${fixtureName}`, { waitUntil: "networkidle" });
    await page.waitForSelector('[data-testid="operator-mental-model-panel"]', { timeout: 10_000 });
    const recoveryBody = await page.locator('[data-testid="selected-goal-detail"]').innerText();
    const requiredRecoveryText = [
      "执行恢复证据任务",
      "恢复任务路径",
      "限定恢复",
      "恢复任务边界",
      "检查最近证据",
      "结果恢复",
      "run_outcome_floor_recovery",
      "排序器 / 跨域证据",
    ];
    const missingRecoveryText = requiredRecoveryText.filter((text) => !recoveryBody.includes(text));
    if (missingRecoveryText.length) {
      throw new Error(`Missing outcome-floor recovery text: ${missingRecoveryText.join(", ")}`);
    }
    const forbiddenRecoveryText = [
      "执行已批准的 Agent 命令",
      "已批准 Agent 命令",
      "run_approved_agent_command",
      "continue_from_refreshed_state",
      "continue_codex_action",
    ];
    const leakedRecoveryText = forbiddenRecoveryText.filter((text) => recoveryBody.includes(text));
    if (leakedRecoveryText.length) {
      const leakContext = leakedRecoveryText.map((text) => {
        const index = recoveryBody.indexOf(text);
        return recoveryBody.slice(Math.max(0, index - 220), index + text.length + 320);
      }).join("\n---\n");
      throw new Error(`Outcome-floor recovery leaked into ordinary delivery: ${leakedRecoveryText.join(", ")}\n${leakContext}`);
    }

    const missingStatusRoutes = [
      `?statusUrl=/status.missing.browser-smoke.json`,
      `?view=ops&statusUrl=/status.missing.browser-smoke.json`,
    ];
    for (const route of missingStatusRoutes) {
      await page.goto(`${baseUrl}/${route}`, { waitUntil: "networkidle" });
      const initialStatusState = page.locator('[data-testid="initial-status-state"]');
      await initialStatusState.waitFor({ state: "visible", timeout: 10_000 });
      const initialStatusText = await initialStatusState.innerText();
      const missingInitialStatusText = ["无法加载实时状态", "重试", "使用示例"]
        .filter((text) => !initialStatusText.includes(text));
      if (missingInitialStatusText.length) {
        throw new Error(`Missing explicit initial status error state for ${route}: ${initialStatusText}`);
      }
      const syntheticDashboardCount = await page
        .locator('[data-testid="operator-mental-model-panel"], [data-testid="share-overview"]')
        .count();
      if (syntheticDashboardCount !== 0) {
        throw new Error(`Requested live status fell back to synthetic content for ${route}.`);
      }
      if (!route.includes("view=ops")) {
        await initialStatusState.getByRole("button", { name: "使用示例" }).click();
        const shareOverview = page.locator('[data-testid="share-overview"]');
        await shareOverview.waitFor({ state: "visible", timeout: 10_000 });
        await page.waitForTimeout(300);
        const sourceLabel = await page.locator('[data-testid="share-source-label"]').innerText();
        if (sourceLabel !== "内置示例") {
          throw new Error(`Explicit example selection did not remain stable: ${sourceLabel}`);
        }
        if (new URL(page.url()).searchParams.get("statusUrl")) {
          throw new Error("Explicit example selection did not clear the requested status URL.");
        }
        await page.goBack({ waitUntil: "networkidle" });
        const restoredStatusState = page.locator('[data-testid="initial-status-state"]');
        await restoredStatusState.waitFor({ state: "visible", timeout: 10_000 });
        await restoredStatusState.getByText("无法加载实时状态", { exact: true }).waitFor({
          state: "visible",
          timeout: 10_000,
        });
      }
    }

    await page.goto(`${baseUrl}/?view=ops`, { waitUntil: "networkidle" });
    await page.locator('[data-testid="operator-mental-model-panel"]').waitFor({
      state: "visible",
      timeout: 10_000,
    });
    await page.getByLabel("状态地址").fill("/status.missing.browser-smoke.json");
    await page.getByRole("button", { name: "加载地址" }).click();
    const requestedStatusState = page.locator('[data-testid="initial-status-state"]');
    await requestedStatusState.waitFor({ state: "visible", timeout: 10_000 });
    await requestedStatusState.getByText("无法加载实时状态", { exact: true }).waitFor({
      state: "visible",
      timeout: 10_000,
    });
    const syntheticOperatorCount = await page
      .locator('[data-testid="operator-mental-model-panel"], [data-testid="share-overview"]')
      .count();
    if (syntheticOperatorCount !== 0) {
      throw new Error("In-page live status failure left synthetic dashboard content visible.");
    }
    await Promise.all([
      page.waitForResponse((response) => (
        new URL(response.url()).pathname.endsWith("/status.missing.browser-smoke.json")
      )),
      requestedStatusState.getByRole("button", { name: "重试" }).click(),
    ]);
    await requestedStatusState.getByText("无法加载实时状态", { exact: true }).waitFor({
      state: "visible",
      timeout: 10_000,
    });
    await requestedStatusState.getByRole("button", { name: "使用示例" }).click();
    await page.locator('[data-testid="operator-mental-model-panel"]').waitFor({
      state: "visible",
      timeout: 10_000,
    });
    await page.getByText("内置示例", { exact: true }).waitFor({ state: "visible", timeout: 10_000 });

    if (pageErrors.length) {
      throw new Error(`Dashboard page errors: ${pageErrors.join(" | ")}`);
    }

    console.log("dashboard-home-browser-smoke ok");
  } finally {
    await cleanupBrowserSmoke({ browser, fixturePaths: [fixturePath], server });
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});

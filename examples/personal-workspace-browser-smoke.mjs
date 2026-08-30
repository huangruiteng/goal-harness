#!/usr/bin/env node
// Focused browser smoke for the personal Agent workspace first screen and interactions.

import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  launchBrowser,
  loadPlaywright,
  startViteDashboardServer,
  waitForHttp,
} from "./dashboard-browser-smoke-support.mjs";

const require = createRequire(import.meta.url);
const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dashboardDir = resolve(repoRoot, "apps/presentation/dashboard");
const outputDir = resolve(repoRoot, "output/playwright/personal-workspace");
const port = Number(process.env.LOOPX_PERSONAL_WORKSPACE_PORT ?? "5196");

async function visibleElementCount(locator) {
  return locator.evaluateAll((elements) => elements.filter((element) => {
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  }).length);
}

async function installApi(page) {
  let turnCounter = 0;
  const runtime = page.__loopxRuntime ??= { actionProposals: new Map(), larkConnections: [], messages: new Map(), sessions: new Map(), turnMessages: new Map() };
  const actionProposals = runtime.actionProposals;
  const sessions = runtime.sessions;
  const messages = runtime.messages;
  const turnMessages = runtime.turnMessages;
  const actionKinds = new Map(Array.from(actionProposals.values(), (proposal) => [proposal.proposal_id, proposal.action_kind]));
  const state = {
    actionApplies: [],
    actionCancels: [],
    actionPreviews: [],
    durableResources: new Set(),
    durableWriteCount: 0,
    failNextLifecycleApply: false,
    failNextStatusRequest: false,
    goalActivationStates: new Map([
      ["product-release", "active"],
      ["research-monitor", "active"],
      ["legacy-benchmark", "stopped"],
      ["archived-notes", "stopped"],
    ]),
    interrupts: [],
    larkWrites: [],
    actionTransitions: [],
    allowNextHeartbeatApply: false,
    nextLifecycleApplyDelayMs: 0,
    nextStatusDelayMs: 0,
    statusRequestCount: 0,
    turnRequests: [],
    get larkConnections() { return runtime.larkConnections; },
  };
  await page.route(`http://127.0.0.1:${port}/status.json`, async (route) => {
    state.statusRequestCount += 1;
    const fixture = structuredClone(require(resolve(repoRoot, "examples/status.example.json")));
    const directoryFixtures = [
      { id: "product-release", display_name: "Product Release" },
      { id: "research-monitor", display_name: "Research Monitor" },
      { id: "legacy-benchmark", display_name: "Legacy Benchmark" },
      { id: "archived-notes", display_name: "Archived Notes" },
    ];
    for (const directoryGoal of directoryFixtures) {
      const activation_state = state.goalActivationStates.get(directoryGoal.id) ?? "active";
      const existingGoal = fixture.run_history.goals.find((goal) => goal.id === directoryGoal.id);
      if (existingGoal) {
        existingGoal.activation_state = activation_state;
        continue;
      }
      fixture.run_history.goals.push({
        ...directoryGoal, activation_state,
        status: "active-read-only", registry_member: true,
        legacy_runtime_goal: false, adapter_kind: "generic_project_goal_v0", adapter_status: "connected",
        lifecycle_phase: "registered", lifecycle_flags: ["registered"],
        quota: { compute: 1, window_hours: 24, slot_minutes: 1, allowed_slots: 1440, spent_slots: 0, state: activation_state === "stopped" ? "paused" : "waiting" },
        index_exists: false, raw_index_records: 0, unique_runs: 0, latest_runs: [],
      });
    }
    if (!fixture.run_history.goals.some((goal) => goal.id === "stale-browser-goal")) {
      fixture.run_history.goals.push({
        id: "stale-browser-goal", status: "monitoring", registry_member: false,
        legacy_runtime_goal: false, adapter_kind: null, adapter_status: null,
        index_exists: false, raw_index_records: 0, unique_runs: 0, latest_runs: [],
      });
    }
    const first = fixture.attention_queue?.items?.[0];
    if (first) {
      first.waiting_on = "user_or_controller";
      first.user_todos = {
        items: [{ done: false, goal_id: first.goal_id, index: 0, role: "user", text: "确认本轮独立审查范围", todo_id: "todo-browser-user-gate" }],
        open_count: 1,
        source_section: "User Todo",
        total_count: 1,
      };
    }
    const delayMs = state.nextStatusDelayMs;
    state.nextStatusDelayMs = 0;
    if (delayMs > 0) await new Promise((resolveWait) => setTimeout(resolveWait, delayMs));
    if (state.failNextStatusRequest) {
      state.failNextStatusRequest = false;
      await route.fulfill({ contentType: "application/json", json: { error: "temporary status failure" }, status: 503 });
      return;
    }
    await route.fulfill({ contentType: "application/json", json: fixture, status: 200 });
  });
  await page.route(`http://127.0.0.1:${port}/api/ssh-source/ensure`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { ok: true, status_url: "http://127.0.0.1:8876/status.json", tunnel_required: true, remote_started: true },
      status: 200,
    });
  });
  await page.route(`http://127.0.0.1:${port}/ssh-hosts`, async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        ok: true,
        schema_version: "ssh_host_catalog_v0",
        hosts: [{ alias: "remote-lab" }, { alias: "remote-build" }],
      },
      status: 200,
    });
  });
  await page.route("http://127.0.0.1:8876/status.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: require(resolve(repoRoot, "examples/status.example.json")),
      status: 200,
    });
  });
  await page.route("http://127.0.0.1:8976/status.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: require(resolve(repoRoot, "examples/status.example.json")),
      status: 200,
    });
  });
  await page.route("http://127.0.0.1:8877/status.json", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: require(resolve(repoRoot, "examples/status.example.json")),
      status: 200,
    });
  });
  await page.route("**/api/chat/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const resumedEvents = url.pathname.match(/^\/api\/chat\/sessions\/([^/]+)\/turns\/([^/]+)\/events$/);
    if (resumedEvents && request.method() === "GET") {
      const sessionId = resumedEvents[1];
      const turnId = resumedEvents[2];
      const answer = "已沿用当前 Goal 与 Agent Session。接下来会先核对状态，再继续推进。";
      await new Promise((resolveWait) => setTimeout(resolveWait, /(中断控制|刷新恢复)/u.test(turnMessages.get(turnId) ?? "") ? 5000 : 1200));
      const activeSession = sessions.get(sessionId);
      if (!activeSession || activeSession.active_turn_id !== turnId) {
        await route.fulfill({ contentType: "text/event-stream", body: "", status: 200 });
        return;
      }
      const visible = messages.get(sessionId) ?? [];
      if (!visible.some((message) => message.message_id === `${turnId}-assistant`)) {
        visible.push({ message_id: `${turnId}-assistant`, turn_id: turnId, role: "assistant", text: answer, created_at: "2026-08-13T01:00:02Z" });
      }
      messages.set(sessionId, visible);
      const event = (id, kind, payload) => `id: ${id}\nevent: ${kind}\ndata: ${JSON.stringify({ event_id: id, sequence: Number(id), kind, created_at: "2026-08-13T01:00:02Z", payload })}\n\n`;
      await route.fulfill({ contentType: "text/event-stream", body: event("1", "assistant.delta", { text: answer }) + event("2", "turn.completed", { response: { schema_version: "loopx_chat_agent_response_v0", message: answer, proposals: [], gate: null } }), status: 200 });
      sessions.set(sessionId, { ...activeSession, active_turn_id: null, status: "ready", updated_at: "2026-08-13T01:00:02Z" });
      return;
    }
    if (url.pathname === "/api/chat/goals/contexts") {
      const fixture = require(resolve(repoRoot, "examples/status.example.json"));
      await route.fulfill({ contentType: "application/json", json: {
        ok: true,
        schema_version: "loopx_chat_goal_contexts_v0",
        goals: (fixture.run_history?.goals ?? []).map((goal) => ({
          goal_id: goal.id,
          repository: { branch: "codex/lark-goal-topic-binding", identity: "git:github.com/loopx-ai/loopx", label: "loopx-ai/loopx", read_only: true },
        })),
      }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/lark/apps") {
      await route.fulfill({ contentType: "application/json", json: {
        ok: true,
        schema_version: "loopx_lark_apps_v0",
        apps: [{ active: true, app_ref: "mew", brand: "feishu", label: "LoopX Mew", ready: true, reply_ready: true }],
      }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/lark/chats") {
      await route.fulfill({ contentType: "application/json", json: {
        ok: true,
        schema_version: "loopx_lark_group_chats_v0",
        chats: [{ chat_id: "oc_browser_fixture", chat_name: "Product group" }],
      }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/lark/connections" && request.method() === "GET") {
      await route.fulfill({ contentType: "application/json", json: {
        ok: true,
        schema_version: "loopx_lark_goal_topic_connections_v0",
        connections: runtime.larkConnections,
      }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/lark/connections" && request.method() === "POST") {
      const body = request.postDataJSON();
      if (body.execute) {
        const fixture = require(resolve(repoRoot, "examples/status.example.json"));
        const goal = (fixture.run_history?.goals ?? []).find((item) => item.id === body.goal_id);
        runtime.larkConnections = runtime.larkConnections.filter((item) => item.goal_id !== body.goal_id);
        runtime.larkConnections.push({
          agent_id: body.agent_id ?? null,
          app_label: "LoopX Mew", app_ref: body.app_ref, chat_name: body.chat_name, enabled: true,
          capture_scope: body.capture_scope,
          event_count: 0, health_error_code: "lark_event_delivery_unverified",
          goal_id: body.goal_id, goal_title: goal?.id ?? body.goal_id, incoming_mode: body.incoming_mode,
          ingress_mode: body.ingress_mode,
          last_event_reason: null, last_event_status: null, listener_error_code: null, listener_status: "listening", replied_count: 0,
          reply_mode: "topic_reply", target_ref: "product-group", topic_name: goal?.id ?? body.goal_id,
          topic_setup_required: false, reply_ready: false,
        });
        state.larkWrites.push({ ...body });
      }
      await route.fulfill({ contentType: "application/json", json: {
        ok: true,
        status: body.execute ? "connected" : "preview_ready",
        public_summary: body.execute ? "connected" : "previewed",
      }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/lark/connections" && request.method() === "DELETE") {
      const goalId = url.searchParams.get("goal_id");
      runtime.larkConnections = runtime.larkConnections.filter((item) => item.goal_id !== goalId);
      await route.fulfill({ contentType: "application/json", json: { ok: true, status: "disconnected" }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/capabilities") {
      await route.fulfill({ contentType: "application/json", json: {
        ok: true, schema_version: "loopx_chat_capabilities_v1", agent_backend: "multi_adapter",
        sandbox: "read-only", approval_policy: "never", todo_write: "preview_locked",
        goal_id: null, streaming: true, resume: true, interrupt: true, typed_actions: true,
        action_kinds: ["goal.create", "goal.lifecycle", "agent.bind", "heartbeat.bind", "monitor.create", "run.correct"],
        adapters: [
          { agent_id: "codex", display_name: "Codex", adapter_kind: "codex_app_server", available: true, streaming: true, resume: true, interrupt: true },
          { agent_id: "claude-code", display_name: "Claude Code", adapter_kind: "claude_code_cli", available: true, streaming: true, resume: true, interrupt: true },
          { agent_id: "offline-agent", display_name: "Offline Agent", adapter_kind: "acp", available: false, streaming: false, resume: false, interrupt: false },
        ],
      }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/sessions" && request.method() === "GET") {
      const requestedGoal = url.searchParams.get("goal_id");
      const requestedAgent = url.searchParams.get("agent_id");
      const requestedChannel = url.searchParams.get("channel_id");
      const matched = [...sessions.values()].filter((session) =>
        (!requestedGoal || session.goal_id === requestedGoal)
        && (!requestedAgent || session.agent_id === requestedAgent)
        && (!requestedChannel || session.channel_id === requestedChannel)
      );
      await route.fulfill({ contentType: "application/json", json: { ok: true, schema_version: "loopx_chat_session_list_v1", sessions: matched }, status: 200 });
      return;
    }
    if (url.pathname === "/api/chat/sessions" && request.method() === "POST") {
      const body = request.postDataJSON();
      const session_id = `session-${body.context_kind}-${body.goal_id}-${body.agent_id}`;
      const existing = body.mode === "resume_latest" ? sessions.get(session_id) : null;
      const session = existing ?? { session_id, goal_id: body.goal_id, agent_id: body.agent_id, adapter_kind: body.agent_id, channel_id: body.context_kind === "manager" ? "manager" : `goal.${body.goal_id}`, status: "ready", active_turn_id: null, last_error_code: null, created_at: "2026-08-13T01:00:00Z", updated_at: "2026-08-13T01:00:00Z", last_activity_at: "2026-08-13T01:00:00Z", resumable: true };
      sessions.set(session_id, session);
      messages.set(session_id, messages.get(session_id) ?? []);
      await route.fulfill({ contentType: "application/json", json: { ok: true, agent_id: body.agent_id, goal_id: body.goal_id, resumed: body.mode === "resume_latest", session_id }, status: 201 });
      return;
    }
    const snapshot = url.pathname.match(/^\/api\/chat\/sessions\/([^/]+)$/);
    if (snapshot && request.method() === "GET") {
      const session = sessions.get(snapshot[1]);
      await route.fulfill({ contentType: "application/json", json: { ok: true, schema_version: "loopx_chat_store_v1", session, messages: messages.get(snapshot[1]) ?? [], active_turn: null }, status: session ? 200 : 404 });
      return;
    }
    const turns = url.pathname.match(/^\/api\/chat\/sessions\/([^/]+)\/turns$/);
    if (turns && request.method() === "POST") {
      const body = request.postDataJSON();
      const turn_id = `turn-${Date.now()}`;
      turnMessages.set(turn_id, body.message);
      const current = sessions.get(turns[1]);
      if (current) sessions.set(turns[1], { ...current, active_turn_id: turn_id, status: "busy", updated_at: "2026-08-13T01:00:01Z" });
      messages.get(turns[1])?.push({ message_id: `${turn_id}-user`, turn_id, role: "user", text: body.message, created_at: "2026-08-13T01:00:01Z" });
      state.turnRequests.push({ message: body.message, sessionId: turns[1], turnId: turn_id });
      await route.fulfill({ contentType: "application/json", json: { ok: true, session_id: turns[1], turn_id, created: true, status: "running", events_url: `/events/${turns[1]}/${turn_id}` }, status: 202 });
      return;
    }
    const interrupt = url.pathname.match(/^\/api\/chat\/sessions\/([^/]+)\/turns\/([^/]+)\/interrupt$/);
    if (interrupt && request.method() === "POST") {
      const current = sessions.get(interrupt[1]);
      if (current) sessions.set(interrupt[1], { ...current, active_turn_id: null, status: "ready", updated_at: "2026-08-13T01:00:02Z" });
      state.interrupts.push({ sessionId: interrupt[1], turnId: interrupt[2] });
      await route.fulfill({ contentType: "application/json", json: { ok: true, session_id: interrupt[1], turn_id: interrupt[2], status: "interrupted" }, status: 200 });
      return;
    }
    await route.fulfill({ contentType: "application/json", json: { ok: true }, status: 200 });
  });
  await page.route("**/events/**", async (route) => {
    const parts = new URL(route.request().url()).pathname.split("/").filter(Boolean);
    const sessionId = parts[1];
    const turnId = parts[2];
    const operatorMessage = turnMessages.get(turnId) ?? "";
    const protectedAction = operatorMessage === "请合并 PR #123"
      ? { operation: "merge", target: "PR #123", summary: "准备 PR #123 的受保护合并预览。" }
      : operatorMessage === "请合并我刚才说的那个"
        ? { operation: "merge", target: "PR #999", summary: "模型错误补出了用户没有提供的目标。" }
      : null;
    const answer = operatorMessage === "请只回复：合并后真实回复已收到"
      ? "合并后真实回复已收到"
      : operatorMessage === "请分析：合并 PR #123 后会有什么风险"
        ? "主要风险是检查未完成或目标分支发生变化；这里只做分析，不会创建合并预览。"
          : operatorMessage === "请合并"
            ? "请告诉我要合并的具体 PR 或 MR；在目标明确前不会创建执行预览。"
          : operatorMessage === "请合并我刚才说的那个"
            ? "这个指代不够明确，请提供具体 PR 或 MR。"
          : protectedAction
            ? "我识别到一个明确的合并请求。LoopX 会先展示受保护操作预览，不会直接执行。"
            : "已沿用当前 Goal 与 Agent Session。接下来会先核对状态，再继续推进。";
    await new Promise((resolveWait) => setTimeout(resolveWait, /(中断控制|刷新恢复)/u.test(operatorMessage) ? 5000 : 1200));
    const activeSession = sessions.get(sessionId);
    if (!activeSession || activeSession.active_turn_id !== turnId) {
      await route.fulfill({ contentType: "text/event-stream", body: "", status: 200 });
      return;
    }
    if (sessionId && messages.has(sessionId)) {
      const visible = messages.get(sessionId);
      if (!visible.some((message) => message.message_id === `${turnId}-assistant`)) {
        visible.push({ message_id: `${turnId}-assistant`, turn_id: turnId, role: "assistant", text: answer, created_at: "2026-08-13T01:00:02Z" });
      }
    }
    const event = (id, kind, payload) => `id: ${id}\nevent: ${kind}\ndata: ${JSON.stringify({ event_id: id, sequence: Number(id), kind, created_at: "2026-08-13T01:00:02Z", payload })}\n\n`;
    await route.fulfill({ contentType: "text/event-stream", body: event("1", "assistant.delta", { text: answer }) + event("2", "turn.completed", { response: { schema_version: "loopx_chat_agent_response_v0", message: answer, proposals: [], protected_action: protectedAction, gate: null } }), status: 200 });
    const current = sessions.get(sessionId);
    if (current?.active_turn_id === turnId) sessions.set(sessionId, { ...current, active_turn_id: null, status: "ready", updated_at: "2026-08-13T01:00:02Z" });
  });
  await page.route("**/api/actions?**", async (route) => {
    const url = new URL(route.request().url());
    const goalId = url.searchParams.get("goal_id");
    const contextKind = url.searchParams.get("context_kind");
    const proposals = Array.from(actionProposals.values()).filter((proposal) => {
      if (proposal.status === "cancelled") return false;
      if (goalId && (proposal.context?.goal_id ?? proposal.normalized_parameters?.goal_id) !== goalId) return false;
      return !contextKind || proposal.context?.kind === contextKind;
    });
    await route.fulfill({ contentType: "application/json", json: { ok: true, schema_version: "loopx_chat_action_list_v1", proposals }, status: 200 });
  });
  await page.route("**/api/actions/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/actions/preview") {
      const body = request.postDataJSON();
      const proposal_id = `proposal-${body.idempotency_key}`;
      actionKinds.set(proposal_id, body.action_kind);
      state.actionPreviews.push({ ...body, proposalId: proposal_id });
      const proposal = {
        schema_version: "loopx_chat_action_proposal_v1", proposal_id, action_kind: body.action_kind,
        summary: body.summary, normalized_parameters: body.normalized_parameters, context: body.context,
        expected_state_fingerprint: "fixture-r1", permission_classification: "durable_write",
        validation_evidence: ["fixture validation"], available_transitions: ["apply", "cancel"],
        status: "preview_ready", receipt: null, stale: null, created_at: "2026-08-13T01:00:00Z", updated_at: "2026-08-13T01:00:00Z",
      };
      actionProposals.set(proposal_id, proposal);
      await route.fulfill({ contentType: "application/json", json: { ok: true, proposal }, status: 201 });
      return;
    }
    const apply = url.pathname.match(/^\/api\/actions\/(.+)\/apply$/);
    if (apply) {
      state.actionApplies.push(apply[1]);
      if (actionKinds.get(apply[1]) === "heartbeat.bind" && !state.allowNextHeartbeatApply) {
        await route.fulfill({ contentType: "application/json", json: { ok: false, schema_version: "loopx_chat_action_gate_v1", error: "Host activation required", error_code: "protected_action", gate: { kind: "host_activation_required", summary: "需要 Codex App 宿主创建 Heartbeat 自动化。", next_action: "确认宿主自动化后重新验证。" }, write_attempted: false }, status: 409 });
        return;
      }
      if (actionKinds.get(apply[1]) === "heartbeat.bind") state.allowNextHeartbeatApply = false;
      const actionKind = actionKinds.get(apply[1]) ?? "goal.create";
      const preview = state.actionPreviews.find((item) => item.proposalId === apply[1]);
      const lifecycleDelayMs = actionKind === "goal.lifecycle" ? state.nextLifecycleApplyDelayMs : 0;
      state.nextLifecycleApplyDelayMs = 0;
      if (lifecycleDelayMs > 0) await new Promise((resolveWait) => setTimeout(resolveWait, lifecycleDelayMs));
      if (actionKind === "goal.lifecycle" && state.failNextLifecycleApply) {
        state.failNextLifecycleApply = false;
        await route.fulfill({
          contentType: "application/json",
          json: {
            error: "Lifecycle gate changed before apply",
            error_code: "protected_action",
            gate: { kind: "goal_lifecycle_gate", summary: "Goal 状态已变化，请重新确认。" },
            ok: false,
            write_attempted: false,
          },
          status: 409,
        });
        return;
      }
      let acceptedTurn = null;
      if (actionKind === "run.correct" && preview) {
        const sessionId = preview.normalized_parameters.session_id;
        const turnId = `turn-${++turnCounter}`;
        acceptedTurn = { session_id: sessionId, turn_id: turnId, status: "queued", created: true };
        turnMessages.set(turnId, preview.normalized_parameters.message);
        state.turnRequests.push({ message: preview.normalized_parameters.message, sessionId, turnId });
        const active = sessions.get(sessionId) ?? {
          session_id: sessionId,
          goal_id: preview.normalized_parameters.goal_id,
          agent_id: "codex",
          adapter_kind: "codex",
          channel_id: `goal.${preview.normalized_parameters.goal_id}`,
          active_turn_id: null,
          status: "ready",
          resumable: true,
        };
        sessions.set(sessionId, { ...active, active_turn_id: turnId, status: "busy" });
        const sessionMessages = messages.get(sessionId) ?? [];
        sessionMessages.push({ message_id: `${turnId}-user`, turn_id: turnId, role: "user", text: preview.normalized_parameters.message, created_at: "2026-08-13T01:00:01Z" });
        messages.set(sessionId, sessionMessages);
      }
      if (actionKind === "goal.lifecycle" && preview) {
        state.goalActivationStates.set(
          preview.normalized_parameters.goal_id,
          preview.normalized_parameters.operation === "stop" ? "stopped" : "active",
        );
      }
      const resourceKey = `${actionKind}:${apply[1]}`;
      if (!state.durableResources.has(resourceKey)) {
        state.durableResources.add(resourceKey);
        state.durableWriteCount += 1;
      }
      const proposal = {
        schema_version: "loopx_chat_action_proposal_v1", proposal_id: apply[1], action_kind: actionKind,
        summary: "已应用", normalized_parameters: preview?.normalized_parameters ?? {}, context: preview?.context ?? {}, expected_state_fingerprint: "fixture-r1",
        permission_classification: "durable_write", validation_evidence: [], available_transitions: ["apply", "cancel"],
        status: "applied", receipt: { projection_verified: true, receipt_id: "fixture-receipt" }, stale: null, created_at: "2026-08-13T01:00:00Z", updated_at: "2026-08-13T01:00:01Z",
      };
      actionProposals.set(apply[1], proposal);
      await route.fulfill({ contentType: "application/json", json: { ok: true, proposal, turn: acceptedTurn }, status: acceptedTurn ? 202 : 200 });
      return;
    }
    const cancel = url.pathname.match(/^\/api\/actions\/(.+)\/cancel$/);
    if (cancel) {
      state.actionCancels.push(cancel[1]);
      const proposal = {
        schema_version: "loopx_chat_action_proposal_v1", proposal_id: cancel[1], action_kind: actionKinds.get(cancel[1]) ?? "goal.create",
        summary: "已取消", normalized_parameters: {}, context: {}, expected_state_fingerprint: "fixture-r1",
        permission_classification: "durable_write", validation_evidence: [], available_transitions: ["apply", "cancel"],
        status: "cancelled", receipt: null, stale: null, created_at: "2026-08-13T01:00:00Z", updated_at: "2026-08-13T01:00:01Z",
      };
      actionProposals.set(cancel[1], proposal);
      await route.fulfill({ contentType: "application/json", json: { ok: true, proposal }, status: 200 });
      return;
    }
    const transition = url.pathname.match(/^\/api\/actions\/(.+)\/(defer|reject|regenerate)$/);
    if (transition) {
      const existing = actionProposals.get(transition[1]);
      const nextId = transition[2] === "regenerate" ? `${transition[1]}-regenerated` : transition[1];
      const proposal = {
        ...(existing ?? {}),
        schema_version: "loopx_chat_action_proposal_v1",
        proposal_id: nextId,
        action_kind: existing?.action_kind ?? actionKinds.get(transition[1]) ?? "goal.create",
        summary: existing?.summary ?? "已更新决定",
        normalized_parameters: existing?.normalized_parameters ?? {},
        context: existing?.context ?? {},
        expected_state_fingerprint: "fixture-r1",
        permission_classification: "durable_write",
        validation_evidence: [],
        available_transitions: ["apply", "cancel"],
        status: transition[2] === "defer" ? "deferred" : transition[2] === "reject" ? "rejected" : "preview_ready",
        receipt: null,
        stale: null,
        created_at: existing?.created_at ?? "2026-08-13T01:00:00Z",
        updated_at: "2026-08-13T01:00:01Z",
      };
      actionProposals.set(nextId, proposal);
      state.actionTransitions.push({ proposalId: transition[1], transition: transition[2] });
      await route.fulfill({ contentType: "application/json", json: { ok: true, proposal }, status: 200 });
      return;
    }
    await route.fulfill({ contentType: "application/json", json: { ok: true }, status: 200 });
  });
  return state;
}

async function main() {
  const { chromium } = loadPlaywright();
  await mkdir(outputDir, { recursive: true });
  const results = new Map(Array.from({ length: 20 }, (_, index) => [index + 1, { status: "UNTESTED", note: "" }]));
  const observations = [];
  const pass = (criterion, note) => results.set(criterion, { status: "PASS", note });
  const fail = (criterion, note) => results.set(criterion, { status: "FAIL", note });
  const server = startViteDashboardServer({ dashboardDir, port });
  let browser;
  try {
    const url = `http://127.0.0.1:${port}/?statusUrl=/status.json`;
    await waitForHttp(url);
    browser = await launchBrowser(chromium);
    const page = await browser.newPage({ viewport: { width: 1512, height: 982 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") pageErrors.push(message.text());
    });
    const api = await installApi(page);
    await page.goto(url, { waitUntil: "networkidle" });
    try {
      await page.getByTestId("personal-goal-home").waitFor({ state: "visible", timeout: 15_000 });
    } catch (error) {
      throw new Error(`${error.message}; url=${page.url()}; errors=${pageErrors.join(" | ")}; body=${(await page.locator("body").innerText()).slice(0, 1000)}`);
    }
    const body = await page.locator("body").innerText();
    for (const text of ["LoopX 管家", "需要你", "执行中", "观察中", "已安排", "历史", "GOALS", "Codex"]) {
      if (!body.includes(text)) {
        await page.screenshot({ path: resolve(outputDir, "desktop-first-screen-failed.png"), fullPage: false, animations: "disabled" });
        throw new Error(`First screen missing ${text}; body=${body.slice(0, 2000)}`);
      }
    }
    if (await page.locator(".personal-home-lane").count() !== 4) throw new Error("Manager home did not render four active lanes");
    if (body.includes("接下来")) throw new Error("Manager home still exposes the ambiguous 接下来 label");
    if (body.includes("stale-browser-goal")) throw new Error("An unregistered historical Goal remained interactive");
    if (!(await page.locator(".personal-home-history").first().isVisible())) throw new Error("Completed Goals are not available through the collapsed history section");
    const needsYouCount = await page.getByTestId("personal-home-lane-needs_you").locator(".personal-home-goal-card").count();
    const greeting = await page.locator(".personal-manager-greeting").innerText();
    if (!greeting.includes(`你有 ${needsYouCount} 项需要处理`)) {
      throw new Error(`Manager greeting count disagrees with the needs-you lane: count=${needsYouCount}; greeting=${greeting}`);
    }
    if (await page.locator(".personal-manager-channels").count()) throw new Error("Sidebar still exposes state lanes as duplicate navigation channels");
    if (await page.locator(".personal-digest-stats button").count()) throw new Error("Away digest still behaves like hidden channel navigation");
    if (body.includes("Agent 设置")) throw new Error("Sidebar still exposes the read-only Agent settings dead end");
    if (await page.locator(".personal-global-rail").count()) throw new Error("Old icon rail is visible");
    if ((await page.locator(".personal-goal-list:not(.is-stopped) .personal-goal-row").count()) !== 3) throw new Error("Active Goal directory did not exclude stopped Goals");
    const stoppedDirectory = page.locator(".personal-stopped-goals");
    if (!(await stoppedDirectory.isVisible()) || await stoppedDirectory.getAttribute("open") !== null) throw new Error("Stopped Goals are not available in a collapsed directory section");
    const writesBeforeLifecyclePreview = api.durableWriteCount;
    await page.getByRole("button", { name: "停止 Product Release", exact: true }).click();
    await page.getByText("确认执行", { exact: true }).waitFor({ state: "visible" });
    const stopPreview = api.actionPreviews.findLast((preview) => preview.action_kind === "goal.lifecycle" && preview.normalized_parameters.operation === "stop");
    if (!stopPreview || stopPreview.normalized_parameters.goal_id !== "product-release") throw new Error("Goal stop did not create the expected typed preview");
    if (api.durableWriteCount !== writesBeforeLifecyclePreview) throw new Error("Goal stop preview wrote state before owner confirmation");
    const statusRequestsBeforeStop = api.statusRequestCount;
    api.nextLifecycleApplyDelayMs = 900;
    api.nextStatusDelayMs = 900;
    await page.getByRole("button", { name: "停止 Goal", exact: true }).click();
    await page.waitForFunction(
      () => document.querySelectorAll(".personal-goal-list:not(.is-stopped) .personal-goal-row").length === 2,
      null,
      { timeout: 600 },
    );
    if ((await page.locator(".personal-goal-list:not(.is-stopped) .personal-goal-row").count()) !== 2) throw new Error("Optimistic Goal stop did not update the active sidebar immediately");
    await page.waitForTimeout(2_000);
    if (api.statusRequestCount <= statusRequestsBeforeStop) throw new Error("Successful Goal stop did not start background full-status reconciliation");
    if ((await page.locator(".personal-goal-list:not(.is-stopped) .personal-goal-row").count()) !== 2) throw new Error("Full-status reconciliation reverted a successful Goal stop");
    await stoppedDirectory.locator("summary").click();
    await page.getByRole("button", { name: "恢复 Product Release", exact: true }).click();
    await page.getByText("确认执行", { exact: true }).waitFor({ state: "visible" });
    const resumePreview = api.actionPreviews.findLast((preview) => preview.action_kind === "goal.lifecycle" && preview.normalized_parameters.operation === "resume");
    if (!resumePreview || resumePreview.normalized_parameters.goal_id !== "product-release") throw new Error("Goal resume did not create the expected typed preview");
    if (api.durableWriteCount !== writesBeforeLifecyclePreview + 1) throw new Error("Goal resume preview wrote state before owner confirmation");
    api.nextLifecycleApplyDelayMs = 900;
    await page.getByRole("button", { name: "恢复 Goal", exact: true }).click();
    await page.getByRole("button", { name: "停止 Product Release", exact: true }).waitFor({ state: "attached", timeout: 600 });
    await page.waitForTimeout(1_100);
    if ((await page.locator(".personal-goal-list:not(.is-stopped) .personal-goal-row").count()) !== 3) throw new Error("Full-status reconciliation reverted a successful Goal resume");

    await page.getByRole("button", { name: "停止 Product Release", exact: true }).click();
    await page.getByText("确认执行", { exact: true }).waitFor({ state: "visible" });
    api.nextStatusDelayMs = 1_600;
    await page.getByRole("button", { name: "停止 Goal", exact: true }).click();
    await page.getByRole("button", { name: "恢复 Product Release", exact: true }).waitFor({ state: "attached" });
    await page.getByRole("button", { name: "恢复 Product Release", exact: true }).click();
    await page.getByText("确认执行", { exact: true }).waitFor({ state: "visible" });
    await page.getByRole("button", { name: "恢复 Goal", exact: true }).click();
    await page.getByRole("button", { name: "停止 Product Release", exact: true }).waitFor({ state: "attached" });
    await page.waitForTimeout(1_800);
    if ((await page.locator(".personal-goal-list:not(.is-stopped) .personal-goal-row").count()) !== 3) throw new Error("A stale background response overwrote a newer optimistic Goal transition");

    await page.getByRole("button", { name: "停止 Product Release", exact: true }).click();
    await page.getByText("确认执行", { exact: true }).waitFor({ state: "visible" });
    api.failNextLifecycleApply = true;
    api.nextLifecycleApplyDelayMs = 900;
    await page.getByRole("button", { name: "停止 Goal", exact: true }).click();
    await page.getByRole("button", { name: "恢复 Product Release", exact: true }).waitFor({ state: "attached", timeout: 600 });
    await page.getByRole("button", { name: "停止 Product Release", exact: true }).waitFor({ state: "attached", timeout: 2_000 });
    if (api.goalActivationStates.get("product-release") !== "active") throw new Error("Rejected Goal stop mutated the durable fixture state");
    await page.getByRole("button", { name: "停止 Product Release", exact: true }).click();
    await page.getByText("确认执行", { exact: true }).waitFor({ state: "visible" });
    api.failNextStatusRequest = true;
    api.nextStatusDelayMs = 400;
    await page.getByRole("button", { name: "停止 Goal", exact: true }).click();
    await page.waitForTimeout(900);
    if (await page.getByText("无法读取状态", { exact: false }).count()) throw new Error("Background lifecycle reconciliation replaced the workspace with a fatal status error");
    if ((await page.locator(".personal-goal-list:not(.is-stopped) .personal-goal-row").count()) !== 2) throw new Error("Background reconciliation failure reverted the successful optimistic Goal state");
    const closeLifecycleDrawer = page.getByRole("button", { name: "关闭", exact: true });
    if (await closeLifecycleDrawer.count()) await closeLifecycleDrawer.click();
    await page.emulateMedia({ reducedMotion: "reduce" });
    const stoppedChevronTransition = await stoppedDirectory.locator("summary svg").evaluate((element) => getComputedStyle(element).transitionDuration);
    if (stoppedChevronTransition !== "0s") throw new Error(`Stopped Goals disclosure ignores reduced motion: ${stoppedChevronTransition}`);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.screenshot({ path: resolve(outputDir, "goal-lifecycle-directory.png"), fullPage: false, animations: "disabled" });
    pass(1, "Goal stop/resume updates the sidebar optimistically, rolls back a rejected apply, and still reconciles the full status payload in the background.");
    if (await page.locator(".personal-timeline-row").filter({ hasText: /纠偏/u }).count()) throw new Error("Browse rows expose repeated correction actions");
    pass(2, "Browse rows are full-row click targets and Session rows state that they open execution progress and results.");
    await page.screenshot({ path: resolve(outputDir, "desktop-first-screen.png"), fullPage: false, animations: "disabled" });
    pass(4, "First viewport exposes needs-you, running, observing, and scheduled Goal lanes with collapsed history.");
    pass(15, "Desktop viewport matches the approved single-sidebar/channel/drawer composition.");

    if (await page.locator("html").getAttribute("lang") !== "zh-CN") throw new Error("Desktop did not start in Simplified Chinese");
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("region", { name: "设置", exact: true }).waitFor({ state: "visible" });
    await page.getByRole("button", { name: /语言/ }).click();
    const englishLocale = page.getByRole("radio", { name: /English/ });
    await englishLocale.click();
    await page.getByRole("heading", { level: 1, name: "Language", exact: true }).waitFor({ state: "visible" });
    if (await page.locator("html").getAttribute("lang") !== "en") throw new Error("Language switch did not update the document locale");
    if (await page.evaluate(() => localStorage.getItem("loopx-pw-locale")) !== "en") throw new Error("English locale was not persisted");
    await page.screenshot({ path: resolve(outputDir, "desktop-settings-english.png"), fullPage: false, animations: "disabled" });
    await page.reload({ waitUntil: "networkidle" });
    await page.getByTestId("personal-goal-home").waitFor({ state: "visible" });
    await page.getByText("LoopX Manager", { exact: true }).first().waitFor({ state: "visible" });
    if (await page.locator("html").getAttribute("lang") !== "en") throw new Error("English locale did not survive reload");
    await page.locator(".personal-goal-link").first().click();
    await page.getByRole("button", { name: "Goal details" }).click();
    await page.getByText("Repository", { exact: true }).waitFor({ state: "visible" });
    await page.getByText("Execution Session", { exact: true }).waitFor({ state: "visible" });
    await page.getByText("Read only", { exact: true }).waitFor({ state: "visible" });
    await page.getByRole("button", { name: /Close details/ }).click();

    const writesBeforeEnglishPreviews = api.durableWriteCount;
    await page.locator(".personal-manager-link").first().click();
    await page.getByRole("button", { name: "Create Goal", description: "Insert a Goal template to review before creation" }).click();
    const englishGoalDraft = await page.getByLabel("Send a message to LoopX").inputValue();
    for (const field of ["Objective:", "Completion criteria:", "Execution boundary (optional):", "Related repository (optional):", "Notification method (optional):"]) {
      if (!englishGoalDraft.includes(field)) throw new Error(`English Create Goal draft missing ${field}: ${englishGoalDraft}`);
    }
    await page.getByLabel("Send a message to LoopX").fill([
      "Create a long-term Goal:",
      "Objective: Prepare my weekly work review",
      "Completion criteria: List completed work, blockers, and next-week plans",
      "Execution boundary (optional): Read only; do not call external tools or modify repositories",
      "Related repository (optional):",
      "Notification method (optional):",
    ].join("\n"));
    await page.locator(".personal-channel-composer > button").last().click();
    await page.getByText("Confirm execution", { exact: true }).waitFor({ state: "visible" });
    await page.getByRole("button", { name: "Create Goal and start first run", exact: true }).waitFor({ state: "visible" });
    const englishGoalPreview = api.actionPreviews.at(-1);
    if (englishGoalPreview?.action_kind !== "goal.create") throw new Error(`English Goal input did not create a Goal preview: ${JSON.stringify(englishGoalPreview)}`);
    if (englishGoalPreview.normalized_parameters.title !== "Prepare my weekly work review") throw new Error(`English Goal title drifted: ${JSON.stringify(englishGoalPreview.normalized_parameters)}`);
    if (englishGoalPreview.normalized_parameters.completion_criteria !== "List completed work, blockers, and next-week plans") throw new Error(`English completion criteria were not preserved: ${JSON.stringify(englishGoalPreview.normalized_parameters)}`);
    if (englishGoalPreview.normalized_parameters.execution_boundary !== "Read only; do not call external tools or modify repositories") throw new Error(`English execution boundary was not preserved: ${JSON.stringify(englishGoalPreview.normalized_parameters)}`);
    if (englishGoalPreview.normalized_parameters.permission !== "read_only") throw new Error(`English execution boundary did not remain read-only: ${JSON.stringify(englishGoalPreview.normalized_parameters)}`);
    await page.getByRole("button", { name: "Close", exact: true }).click();

    await page.locator(".personal-goal-link").first().click();
    await page.getByRole("button", { name: "Configure scheduled check", description: "Fill in what to check, frequency, and stop condition before creation" }).click();
    const englishMonitorDraft = await page.getByLabel("Send a message to LoopX").inputValue();
    for (const field of ["Check target:", "Frequency", "Stop condition:"]) {
      if (!englishMonitorDraft.includes(field)) throw new Error(`English monitor draft missing ${field}: ${englishMonitorDraft}`);
    }
    const previewsBeforeEnglishCalendarSchedule = api.actionPreviews.length;
    await page.getByLabel("Send a message to LoopX").fill([
      "Add a scheduled check for the current Goal:",
      "Check target: Verify the weekly review",
      "Frequency: Every Friday at 17:00",
      "Stop condition: Goal completes",
    ].join("\n"));
    await page.locator(".personal-channel-composer > button").last().click();
    await page.getByText("Scheduled checks do not currently support an exact weekday or time.", { exact: false }).waitFor({ state: "visible" });
    if (api.actionPreviews.length !== previewsBeforeEnglishCalendarSchedule) throw new Error("Unsupported English calendar schedule created a misleading preview");
    await page.getByLabel("Send a message to LoopX").fill([
      "Add a scheduled check for the current Goal:",
      "Check target: Verify the review includes completed work, blockers, and next-week plans",
      "Frequency: Every 2 hours",
      "Stop condition: Goal completes",
    ].join("\n"));
    await page.locator(".personal-channel-composer > button").last().click();
    await page.getByText("Confirm execution", { exact: true }).waitFor({ state: "visible" });
    await page.getByRole("button", { name: "Confirm and apply", exact: true }).waitFor({ state: "visible" });
    const englishMonitorPreview = api.actionPreviews.at(-1);
    if (englishMonitorPreview?.action_kind !== "monitor.create") throw new Error(`English monitor input did not create a monitor preview: ${JSON.stringify(englishMonitorPreview)}`);
    if (englishMonitorPreview.normalized_parameters.cadence !== "2h") throw new Error(`English monitor cadence drifted: ${JSON.stringify(englishMonitorPreview.normalized_parameters)}`);
    if (englishMonitorPreview.normalized_parameters.target !== "Verify the review includes completed work, blockers, and next-week plans") throw new Error(`English monitor target drifted: ${JSON.stringify(englishMonitorPreview.normalized_parameters)}`);
    if (englishMonitorPreview.normalized_parameters.stop_condition !== "goal_complete") throw new Error(`English monitor stop condition drifted: ${JSON.stringify(englishMonitorPreview.normalized_parameters)}`);
    if (api.durableWriteCount !== writesBeforeEnglishPreviews) throw new Error("English write previews mutated durable state before confirmation");
    await page.getByRole("button", { name: "Close", exact: true }).click();

    await page.getByRole("button", { name: "Goal details" }).click();
    await page.getByRole("button", { name: "Set up Heartbeat", exact: true }).click();
    const englishHeartbeatDraft = await page.getByLabel("Send a message to LoopX").inputValue();
    for (const field of ["Frequency: Daily", "Stop condition: Goal completes", "Notification: Only notify me when needed"]) {
      if (!englishHeartbeatDraft.includes(field)) throw new Error("English Heartbeat draft missing " + field + ": " + englishHeartbeatDraft);
    }
    await page.locator(".personal-channel-composer > button").last().click();
    await page.getByText("Confirm execution", { exact: true }).waitFor({ state: "visible" });
    const englishHeartbeatPreview = api.actionPreviews.at(-1);
    if (englishHeartbeatPreview?.action_kind !== "heartbeat.bind") throw new Error("English Heartbeat input did not create a heartbeat preview: " + JSON.stringify(englishHeartbeatPreview));
    if (englishHeartbeatPreview.normalized_parameters.cadence !== "1d") throw new Error("English Heartbeat cadence drifted: " + JSON.stringify(englishHeartbeatPreview.normalized_parameters));
    if (englishHeartbeatPreview.normalized_parameters.stop_condition !== "goal_complete") throw new Error("English Heartbeat stop condition drifted: " + JSON.stringify(englishHeartbeatPreview.normalized_parameters));
    const writesBeforeEnglishHeartbeatApply = api.durableWriteCount;
    api.allowNextHeartbeatApply = true;
    await page.getByRole("button", { name: "Confirm and apply", exact: true }).click();
    await page.getByText("Applied. LoopX state will refresh.", { exact: true }).waitFor({ state: "visible" });
    if (api.durableWriteCount !== writesBeforeEnglishHeartbeatApply + 1) throw new Error("English Heartbeat apply did not produce exactly one durable write");
    await page.getByRole("button", { name: "View updated Goal", exact: true }).click();
    await page.getByRole("navigation", { name: "Goal view" }).getByRole("button", { name: "Chat", exact: true }).click();
    const englishHeartbeatSchedule = page.locator(".personal-schedule-row", { hasText: "Goal Heartbeat" }).first();
    await englishHeartbeatSchedule.waitFor({ state: "visible" });
    const englishHeartbeatScheduleText = await englishHeartbeatSchedule.innerText();
    if (!englishHeartbeatScheduleText.includes("1d")) throw new Error("Applied English Heartbeat lost cadence: " + englishHeartbeatScheduleText);
    await englishHeartbeatSchedule.click();
    const englishHeartbeatDrawer = page.locator('.personal-context-drawer[data-context-kind="schedule"]');
    await englishHeartbeatDrawer.getByText("goal_complete", { exact: true }).waitFor({ state: "visible" });
    await englishHeartbeatDrawer.getByText("Asia/Shanghai", { exact: true }).waitFor({ state: "visible" });
    const englishHeartbeatReadback = await englishHeartbeatDrawer.innerText();
    for (const forbidden of ["等待下次宿主唤醒", "仅在需要你时通知", "由 heartbeat-prompt 生命周期驱动", "Goal 完成或 owner 停止"]) {
      if (englishHeartbeatReadback.includes(forbidden)) throw new Error("Applied English Heartbeat exposed Chinese fallback " + forbidden + ": " + englishHeartbeatReadback);
    }
    await page.getByRole("button", { name: /Close details/ }).click();
    pass(20, "English Goal and monitor previews stay read-only until confirmation, and applied Heartbeat readback preserves typed schedule semantics.");

    await page.getByRole("button", { name: "Settings", exact: true }).click();
    await page.getByRole("button", { name: /Language/ }).click();
    await page.getByRole("radio", { name: /Simplified Chinese/ }).click();
    await page.getByRole("heading", { level: 1, name: "语言", exact: true }).waitFor({ state: "visible" });
    if (await page.evaluate(() => localStorage.getItem("loopx-pw-locale")) !== "zh-CN") throw new Error("Simplified Chinese locale was not persisted");
    await page.getByRole("button", { name: "返回工作区", exact: true }).click();
    await page.locator(".personal-manager-link").first().click();
    await page.getByTestId("personal-goal-home").waitFor({ state: "visible" });

    if (await page.locator(".personal-manager-conversation-tray").count()) {
      throw new Error("Historical manager messages kept a conversation receipt permanently visible before a new send");
    }
    const managerNavigation = page.getByRole("navigation", { name: "管家视图" });
    await managerNavigation.waitFor({ state: "visible" });
    if (await managerNavigation.getByRole("button", { name: "总览", exact: true }).getAttribute("aria-current") !== "page") {
      throw new Error("Manager overview did not expose its persistent selected tab");
    }
    await managerNavigation.getByRole("button", { name: "Chat", exact: true }).click();
    if (await managerNavigation.getByRole("button", { name: "Chat", exact: true }).getAttribute("aria-current") !== "page") {
      throw new Error("Manager Chat did not become the selected view");
    }
    if (await page.locator(".personal-home-board").isVisible()) throw new Error("Manager Chat kept the overview board visible");
    await managerNavigation.getByRole("button", { name: "总览", exact: true }).click();
    await page.locator(".personal-home-board").waitFor({ state: "visible" });

    await page.getByRole("button", { name: "汇总所有 Goal 进展" }).click();
    const reportDeadline = Date.now() + 5_000;
    while (!api.turnRequests.some((turn) => turn.message.includes("汇总所有活跃 Goal 的最新进展与阻塞")) && Date.now() < reportDeadline) {
      await new Promise((resolveWait) => setTimeout(resolveWait, 50));
    }
    if (!api.turnRequests.some((turn) => turn.message.includes("汇总所有活跃 Goal 的最新进展与阻塞"))) throw new Error("Progress report shortcut did not send a useful scoped request");
    while (await page.getByRole("button", { name: "汇总所有 Goal 进展" }).isDisabled()) await new Promise((resolveWait) => setTimeout(resolveWait, 50));
    await page.locator(".personal-manager-conversation-tray").waitFor({ state: "visible" });
    if (!(await page.getByTestId("personal-home-lane-running").isVisible())) throw new Error("Manager send replaced the four-lane home overview");
    const managerUrlBefore = page.url();
    await page.getByRole("button", { name: "询问全局待办", exact: true }).click();
    await page.getByLabel("向 LoopX 发送消息").fill("我现在该做什么？只读回答，不要创建或修改任何状态。");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText(/^先处理「.+」：.+/u).waitFor({ state: "visible" });
    await page.getByText("查看完整对话", { exact: true }).waitFor({ state: "visible" });
    if (page.url() !== managerUrlBefore) throw new Error(`Manager send navigated away from the overview: ${managerUrlBefore} -> ${page.url()}`);
    await page.screenshot({ path: resolve(outputDir, "manager-conversation-tray-compact.png"), fullPage: false, animations: "disabled" });
    await page.getByText("查看完整对话", { exact: true }).click();
    await page.getByRole("navigation", { name: "管家视图" }).waitFor({ state: "visible" });
    if (await page.locator(".personal-home-board").isVisible()) throw new Error("Full manager Chat left the Goal overview visible behind the conversation");
    if (await page.locator(".personal-manager-conversation-tray").count()) throw new Error("Full manager Chat kept the compact home tray visible");
    if (await page.locator(".personal-channel-timeline .personal-message").count() < 4) throw new Error("Manager Chat did not show the complete conversation history");
    await page.screenshot({ path: resolve(outputDir, "manager-chat.png"), fullPage: false, animations: "disabled" });
    await page.getByRole("button", { name: "总览", exact: true }).click();
    await page.locator(".personal-home-board").waitFor({ state: "visible" });
    if (await page.locator(".personal-manager-conversation-tray").count()) {
      throw new Error("Manager conversation receipt stayed permanently visible after returning to the overview");
    }

    const [fileChooser] = await Promise.all([
      page.waitForEvent("filechooser"),
      page.getByRole("button", { name: "添加图片" }).click(),
    ]);
    await fileChooser.setFiles({
      buffer: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8WQAAAAASUVORK5CYII=", "base64"),
      mimeType: "image/png",
      name: "loopx-smoke.png",
    });
    await page.getByRole("img", { name: "loopx-smoke.png" }).waitFor({ state: "visible" });
    if (await page.getByRole("button", { name: "发送", exact: true }).isDisabled()) throw new Error("A valid image attachment did not enable the composer send action");
    await page.getByRole("button", { name: "移除图片 loopx-smoke.png" }).click();
    pass(18, "The visible attachment button opens a file chooser; a valid PNG renders a preview and enables send.");

    await page.getByLabel("向 LoopX 发送消息").evaluate((target) => {
      const png = Uint8Array.from(atob("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z8WQAAAAASUVORK5CYII="), (char) => char.charCodeAt(0));
      const file = new File([png], "loopx-pasted.png", { type: "image/png" });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      target.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: transfer }));
    });
    await page.getByRole("img", { name: "loopx-pasted.png" }).waitFor({ state: "visible" });
    await page.getByRole("button", { name: "移除图片 loopx-pasted.png" }).click();
    pass(19, "Pasting a clipboard PNG attaches through the same validated composer path.");

    const writesBeforeGoalCreate = api.durableWriteCount;
    await page.getByRole("button", { name: "创建新 Goal" }).click();
    const goalDraft = await page.getByLabel("向 LoopX 发送消息").inputValue();
    for (const field of ["目标：", "完成标准：", "执行边界（可选）：", "关联仓库（可选）：", "通知方式（可选）："]) {
      if (!goalDraft.includes(field)) throw new Error(`Create Goal draft missing ${field}`);
    }
    await page.getByLabel("向 LoopX 发送消息").fill([
      "我想创建一个长期 Goal：",
      "目标：整理我的每周工作复盘",
      "完成标准：列出已完成、阻塞、下周计划",
      "执行边界（可选）：不调用外部工具，不修改仓库",
      "关联仓库（可选）：",
      "通知方式（可选）：",
    ].join("\n"));
    await page.locator(".personal-channel-composer > button").last().click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    const goalPreview = api.actionPreviews.at(-1);
    for (const field of ["agent_id", "goal_id", "heartbeat", "initial_todos", "permission", "stop_condition", "workspace_ref"]) {
      if (!(field in (goalPreview?.normalized_parameters ?? {}))) throw new Error(`Goal preview missing ${field}`);
    }
    if (goalPreview?.normalized_parameters.title !== "整理我的每周工作复盘") throw new Error(`Structured Goal title drifted: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (goalPreview?.normalized_parameters.goal_id === "loopx" || !String(goalPreview?.normalized_parameters.goal_id).startsWith("goal-")) throw new Error(`Structured Goal id was derived from template chrome: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (!String(goalPreview?.normalized_parameters.objective).includes("列出已完成、阻塞、下周计划")) throw new Error(`Goal completion standard was lost: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (goalPreview?.normalized_parameters.completion_criteria !== "列出已完成、阻塞、下周计划") throw new Error(`Goal completion criteria were not preserved structurally: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (goalPreview?.normalized_parameters.execution_boundary !== "不调用外部工具，不修改仓库") throw new Error(`Goal execution boundary was not preserved structurally: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (goalPreview?.normalized_parameters.permission !== "read_only") throw new Error(`Goal execution boundary did not remain read-only: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (JSON.stringify(goalPreview?.normalized_parameters.initial_todos).includes("推进首个可验证结果")) throw new Error(`Goal preview kept unrelated generic Todos: ${JSON.stringify(goalPreview?.normalized_parameters)}`);
    if (api.durableWriteCount !== writesBeforeGoalCreate) throw new Error("Goal preview wrote durable state before confirmation");
    pass(7, "Goal preview includes Goal, Agent, workspace, permissions, Todos, heartbeat, and stop condition fields.");
    await page.getByRole("button", { name: "创建 Goal 并开始首轮", exact: true }).click();
    try {
      await page.getByText(/已应用/).first().waitFor({ state: "visible" });
    } catch (error) {
      await page.screenshot({ path: resolve(outputDir, "goal-apply-failed.png"), fullPage: true, animations: "disabled" });
      throw new Error(`${error.message}; applies=${JSON.stringify(api.actionApplies)}; errors=${pageErrors.join(" | ")}; body=${(await page.locator("body").innerText()).slice(0, 3000)}`);
    }
    if (api.durableWriteCount !== writesBeforeGoalCreate + 1) throw new Error("Goal apply did not create exactly one durable resource");
    await page.evaluate(async (proposalId) => {
      await fetch(`/api/actions/${proposalId}/apply`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
    }, goalPreview.proposalId);
    if (api.durableWriteCount !== writesBeforeGoalCreate + 1) throw new Error("Repeated proposal apply duplicated durable state");
    pass(9, "A repeated apply request kept one durable resource and one first-turn resource key.");
    await page.getByRole("button", { name: /关闭详情/ }).click();

    const goalButton = page.locator(".personal-goal-link").first();
    await goalButton.click();
    const goalNavigation = page.getByRole("navigation", { name: "Goal 视图" });
    const defaultTasksTab = goalNavigation.getByRole("button", { name: "Tasks" });
    if (await defaultTasksTab.getAttribute("aria-current") !== "page") throw new Error("Selecting a Goal did not prioritize its Tasks view");
    const readBoardGeometry = async () => {
      const kanban = page.locator(".personal-task-kanban");
      await kanban.waitFor({ state: "visible" });
      const kanbanBox = await kanban.boundingBox();
      const columns = await page.locator(".personal-task-kanban > .personal-object-list").evaluateAll((els) =>
        els.map((el) => { const rect = el.getBoundingClientRect(); return { left: rect.left, right: rect.right, width: rect.width }; })
      );
      return { kanbanBox, columns };
    };
    const assertBoardGeometry = (label, geometry) => {
      if (!geometry.kanbanBox || geometry.columns.length !== 4) {
        throw new Error(`${label}: expected 4 kanban columns, got ${geometry.columns?.length}`);
      }
      const kanbanRight = geometry.kanbanBox.x + geometry.kanbanBox.width;
      if (Math.abs(geometry.columns[3].right - kanbanRight) > 2) {
        throw new Error(`${label}: kanban columns do not fill the board (lastRight=${geometry.columns[3].right}, boardRight=${kanbanRight})`);
      }
      if (new Set(geometry.columns.map((column) => Math.round(column.width))).size !== 1) {
        throw new Error(`${label}: kanban columns are not equal width: ${JSON.stringify(geometry.columns)}`);
      }
    };
    const selectFirstGoal = async () => {
      await page.locator(".personal-goal-link").first().click();
      await page.locator(".personal-task-kanban").waitFor({ state: "visible" });
    };
    const selectProductReleaseGoal = async () => {
      const goal = page.locator(".personal-goal-link", { hasText: "Product Release" }).first();
      if (!await goal.isVisible()) {
        const stoppedGoals = page.locator(".personal-stopped-goals");
        if (await stoppedGoals.getAttribute("open") === null) await stoppedGoals.locator("summary").click();
      }
      await goal.click();
      await page.locator(".personal-task-kanban").waitFor({ state: "visible" });
    };
    const populatedGeometry = await readBoardGeometry();
    assertBoardGeometry("populated board", populatedGeometry);
    await selectProductReleaseGoal();
    const emptyGeometry = await readBoardGeometry();
    assertBoardGeometry("empty board", emptyGeometry);
    if (Math.abs(emptyGeometry.kanbanBox.width - populatedGeometry.kanbanBox.width) > 2) {
      throw new Error(`Empty board width ${emptyGeometry.kanbanBox.width} differs from populated ${populatedGeometry.kanbanBox.width}`);
    }
    const desktopViewport = page.viewportSize();
    await page.setViewportSize({ width: 2048, height: 1200 });
    await page.waitForTimeout(200);
    await selectFirstGoal();
    const populatedWide = await readBoardGeometry();
    assertBoardGeometry("populated board (wide)", populatedWide);
    await selectProductReleaseGoal();
    const emptyWide = await readBoardGeometry();
    assertBoardGeometry("empty board (wide)", emptyWide);
    if (Math.abs(emptyWide.kanbanBox.width - populatedWide.kanbanBox.width) > 2) {
      throw new Error(`Empty board width (wide) ${emptyWide.kanbanBox.width} differs from populated ${populatedWide.kanbanBox.width}`);
    }
    await page.setViewportSize(desktopViewport);
    await page.waitForTimeout(200);
    await selectFirstGoal();
    await page.locator(".personal-object-list").first().waitFor({ state: "visible" });
    await page.getByRole("button", { name: "Goal 详情" }).click();
    await page.getByText("仓库", { exact: true }).waitFor({ state: "visible" });
    await page.getByText("执行 Session", { exact: true }).waitFor({ state: "visible" });
    await page.getByText("只读", { exact: true }).waitFor({ state: "visible" });
    if (!(await page.getByText("loopx-ai/loopx", { exact: true }).isVisible())) throw new Error("Goal drawer did not show the read-only repository context");
    await page.getByRole("button", { name: /关闭详情/ }).click();

    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("heading", { name: "Lark", exact: true }).waitFor({ state: "visible" });
    if (await page.locator(".personal-workspace-shell").count()) throw new Error("Workspace Settings did not replace the workspace shell");
    if (await page.locator(".personal-channel-composer").count()) throw new Error("Workspace Settings left the chat composer visible");
    if (await page.locator("[data-context-drawer]").count()) throw new Error("Workspace Settings left the context drawer visible");
    await page.screenshot({ path: resolve(outputDir, "workspace-settings.png"), fullPage: false, animations: "disabled" });
    await page.getByRole("button", { name: /连接 Lark App/ }).click();
    const connectDialog = page.getByRole("dialog", { name: "连接 Lark App" });
    await connectDialog.waitFor({ state: "visible" });
    await connectDialog.getByRole("option", { name: "Product group" }).waitFor({ state: "attached" });
    await connectDialog.getByLabel("群聊").selectOption({ label: "Product group" });
    await connectDialog.getByLabel("接收范围").selectOption("configured_chat_all");
    const ingressGroup = connectDialog.getByRole("group", { name: "Agent 入站方式" });
    const ingressOptions = await ingressGroup.locator("input[type=radio]").evaluateAll((options) => options.map((option) => option.value));
    if (JSON.stringify(ingressOptions) !== JSON.stringify(["live_steering", "session_queue", "async_inbox"])) throw new Error(`Lark Agent ingress modes drifted: ${JSON.stringify(ingressOptions)}`);
    await ingressGroup.getByLabel("异步收件箱").check();
    await connectDialog.getByLabel("目标 Agent").waitFor({ state: "visible" });
    await connectDialog.getByLabel("回复方式").selectOption("topic_reply");
    await page.screenshot({ path: resolve(outputDir, "lark-routing-modes.png"), fullPage: false, animations: "disabled" });
    await connectDialog.getByRole("button", { name: "连接", exact: true }).click();
    await connectDialog.waitFor({ state: "hidden" });
    const connectionReadback = await page.evaluate(async () => (await fetch("/api/chat/lark/connections")).json());
    if (connectionReadback.connections?.length !== 1) throw new Error(`Lark connection API readback mismatch: ${JSON.stringify(connectionReadback)}`);
    try {
      await page.locator(".personal-lark-table-row", { hasText: "Product group" }).waitFor({ state: "visible", timeout: 10_000 });
    } catch (error) {
      await page.screenshot({ path: resolve(outputDir, "lark-connection-refresh-failed.png"), fullPage: true, animations: "disabled" });
      throw new Error(`${error.message}; body=${(await page.locator("body").innerText()).slice(0, 4000)}`);
    }
    const connectedRow = page.locator(".personal-lark-table-row", { hasText: "Product group" });
    if (!(await connectedRow.getByText("事件订阅待验证", { exact: false }).isVisible())) throw new Error("A zero-event listener was presented as automatic-reply ready");
    if (!(await connectedRow.getByRole("link", { name: "查看飞书事件配置" }).isVisible())) throw new Error("An unverified Lark event subscription lacked repair guidance");
    if (api.larkWrites.length !== 1 || api.larkWrites[0].execute !== true) throw new Error("Lark connect did not perform exactly one approved external write");
    if (api.larkWrites[0].capture_scope !== "configured_chat_all" || api.larkWrites[0].incoming_mode !== "all") throw new Error(`Lark capture mode was not projected: ${JSON.stringify(api.larkWrites[0])}`);
    if (api.larkWrites[0].ingress_mode !== "async_inbox" || !api.larkWrites[0].agent_id) throw new Error(`Lark Agent inbox mode lost its Agent binding: ${JSON.stringify(api.larkWrites[0])}`);
    if (api.larkWrites[0].reply_mode !== "topic_reply") throw new Error(`Lark reply mode was not projected: ${JSON.stringify(api.larkWrites[0])}`);
    Object.assign(api.larkConnections[0], {
      event_count: 1,
      health_error_code: "lark_event_route_mismatch",
      last_event_reason: "topic_mismatch",
      last_event_status: "ignored",
    });
    const mismatchReadback = await page.evaluate(async () => (await fetch("/api/chat/lark/connections")).json());
    if (mismatchReadback.connections?.[0]?.last_event_reason !== "topic_mismatch") {
      throw new Error(`Lark route mismatch API readback mismatch: ${JSON.stringify(mismatchReadback)}`);
    }
    await page.getByRole("button", { name: "返回工作区", exact: true }).click();
    await page.reload({ waitUntil: "networkidle" });
    await page.getByTestId("personal-goal-home").waitFor({ state: "visible" });
    await page.getByRole("button", { name: "设置", exact: true }).click();
    const routeMismatchRow = page.locator(".personal-lark-table-row", { hasText: "Product group" });
    try {
      await routeMismatchRow.getByText("消息未匹配当前 Goal Topic", { exact: false }).waitFor({ state: "visible" });
    } catch (error) {
      throw new Error(`${error.message}; body=${(await page.locator("body").innerText()).slice(0, 4000)}`);
    }
    await routeMismatchRow.getByText("请重新选择群聊并连接该 Goal", { exact: false }).waitFor({ state: "visible" });
    await page.locator(".personal-lark-table-row", { hasText: "Product group" }).getByRole("button", { name: /配置/ }).click();
    const editDialog = page.getByRole("dialog", { name: "编辑 Lark 连接" });
    await editDialog.waitFor({ state: "visible" });
    if (await editDialog.getByLabel("接收范围").inputValue() !== "configured_chat_all") throw new Error("Lark edit mode did not restore capture_scope");
    if (!await editDialog.getByRole("group", { name: "Agent 入站方式" }).getByLabel("异步收件箱").isChecked()) throw new Error("Lark edit mode did not restore ingress_mode");
    if (await editDialog.getByLabel("目标 Agent").inputValue() !== api.larkWrites[0].agent_id) throw new Error("Lark edit mode did not restore agent_id");
    await editDialog.getByRole("button", { name: "取消" }).click();
    await page.screenshot({ path: resolve(outputDir, "lark-goal-connections.png"), fullPage: false, animations: "disabled" });
    await page.getByRole("button", { name: "返回工作区", exact: true }).click();
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Tasks" }).click();
    await page.locator(".personal-object-list").first().waitFor({ state: "visible" });
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Files" }).click();
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Chat" }).click();

    const composer = page.getByLabel("向 LoopX 发送消息");
    const previewCountBeforeSemanticIntent = api.actionPreviews.length;
    async function expectConversationalProtectedTurn(message, answer, previewError) {
      await composer.fill(message);
      await page.getByRole("button", { name: "发送", exact: true }).click();
      await page.getByText(answer, { exact: true }).last().waitFor({ state: "visible", timeout: 10_000 });
      if (api.actionPreviews.length !== previewCountBeforeSemanticIntent) throw new Error(previewError);
    }
    await expectConversationalProtectedTurn("请只回复：合并后真实回复已收到", "合并后真实回复已收到", "An exact-wording protected-action mention created a typed preview");
    await expectConversationalProtectedTurn("请分析：合并 PR #123 后会有什么风险", "主要风险是检查未完成或目标分支发生变化；这里只做分析，不会创建合并预览。", "Protected-action analysis created a typed preview");
    await expectConversationalProtectedTurn("请合并", "请告诉我要合并的具体 PR 或 MR；在目标明确前不会创建执行预览。", "A targetless protected action created an incomplete preview");
    await expectConversationalProtectedTurn("请合并我刚才说的那个", "这个指代不够明确，请提供具体 PR 或 MR。", "A model-invented protected target created a typed preview");

    await composer.fill("请合并 PR #123");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible", timeout: 10_000 });
    const protectedMerge = api.actionPreviews.find((preview) => preview.action_kind === "goal.update" && preview.summary.includes("PR #123"));
    if (!protectedMerge) throw new Error("A clear Agent semantic proposal did not create the protected typed preview");
    await page.screenshot({ path: resolve(outputDir, "semantic-protected-action-preview.png"), fullPage: false, animations: "disabled" });
    await page.getByRole("button", { name: "关闭", exact: true }).click();

    await composer.fill("添加一个「补充回归测试」普通 Todo，并交给 Codex。不要设置 Heartbeat，也不要创建定时检查");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    const naturalTodo = api.actionPreviews.find((preview) => preview.action_kind === "todo.create" && preview.normalized_parameters.text === "补充回归测试");
    if (naturalTodo?.normalized_parameters.endpoint_id !== "codex") throw new Error(`Natural-language Todo creation lost the selected Endpoint: ${JSON.stringify(api.actionPreviews.at(-1))}`);
    if (api.actionPreviews.findLast((preview) => preview.summary.includes("补充回归测试"))?.action_kind !== "todo.create") throw new Error("A negated Heartbeat mention overrode explicit Todo creation");
    await page.getByRole("button", { name: "关闭", exact: true }).click();

    const previewCountBeforeAnalysis = api.actionPreviews.length;
    const turnCountBeforeAnalysis = api.turnRequests.length;
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Tasks" }).click();
    await composer.fill("做一次只读分析：判断刚刚新增的 Todo 是否与当前 Goal 一致，并在当前 Chat 返回两点理由。不要修改状态。");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const taskConversationReceipt = page.getByRole("region", { name: "最近对话" });
    await taskConversationReceipt.getByText("Agent 已回复", { exact: true }).waitFor({ state: "visible", timeout: 10_000 });
    await taskConversationReceipt.getByText("本次对话没有直接修改 Tasks。需要执行时，可先转成 Task 草稿并确认。", { exact: true }).waitFor({ state: "visible" });
    if (api.actionPreviews.length !== previewCountBeforeAnalysis) throw new Error("A read-only reference to an existing Todo created another Todo preview");
    if (api.turnRequests.length <= turnCountBeforeAnalysis) throw new Error("Read-only Todo analysis did not reach the Goal Chat Session");
    await page.screenshot({ path: resolve(outputDir, "task-chat-receipt.png"), fullPage: false, animations: "disabled" });
    await taskConversationReceipt.getByRole("button", { name: "查看回复" }).click();
    await page.getByText("已沿用当前 Goal 与 Agent Session。接下来会先核对状态，再继续推进。", { exact: true }).last().waitFor({ state: "visible", timeout: 10_000 });
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Tasks" }).click();
    await page.getByRole("region", { name: "最近对话" }).getByRole("button", { name: "转为 Task" }).click();
    if (!(await composer.inputValue()).startsWith("创建一个 Task：")) throw new Error("Converting the latest reply did not create an editable Task draft");
    await page.getByText("已根据回复生成 Task 草稿。编辑后发送，LoopX 会先展示确认预览。", { exact: true }).waitFor({ state: "visible" });
    await composer.fill("");
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Chat" }).click();

    await composer.fill("让 Claude Code 负责管理这个 Goal");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    const naturalBinding = api.actionPreviews.find((preview) => preview.action_kind === "agent.bind" && preview.normalized_parameters.agent_id === "claude-code");
    if (!naturalBinding) throw new Error("Natural-language Agent binding did not create a typed preview");
    await page.getByRole("button", { name: "关闭", exact: true }).click();

    const selectedGoalId = new URL(page.url()).searchParams.get("goalId");
    if (!selectedGoalId) throw new Error("Selected Goal URL did not preserve goalId for the Session authority smoke");
    const authoritativeSessionId = `session-authoritative-${selectedGoalId}`;
    page.__loopxRuntime.sessions.set(authoritativeSessionId, {
      session_id: authoritativeSessionId,
      goal_id: selectedGoalId,
      agent_id: "codex",
      adapter_kind: "codex",
      channel_id: "task.todo-session-authority-smoke",
      status: "stale",
      active_turn_id: null,
      last_error_code: null,
      created_at: "2026-08-13T01:00:00Z",
      updated_at: "2026-08-13T01:00:00Z",
      last_activity_at: "2026-08-13T01:00:00Z",
      resumable: true,
    });
    page.__loopxRuntime.messages.set(authoritativeSessionId, []);
    const authoritativeRun = page.locator(".personal-run-row", { hasText: "Agent 执行任务" });
    await authoritativeRun.waitFor({ state: "visible", timeout: 5_000 });
    page.__loopxRuntime.messages.set(authoritativeSessionId, [{
      message_id: "message-authoritative-result",
      turn_id: "turn-authoritative-result",
      role: "agent",
      text: "权威 Session 已完成只读分析，并返回可核验结果。",
      created_at: "2026-08-13T01:00:03Z",
    }]);
    await authoritativeRun.click();
    await page.getByText("执行 Session", { exact: true }).waitFor({ state: "visible" });
    if (await page.getByRole("tab", { name: "执行过程与结果" }).getAttribute("aria-selected") !== "true") throw new Error("Session drawer did not open on the execution record");
    const authoritativeRecord = page.locator(".personal-session-message-record");
    try {
      await authoritativeRecord.locator("header strong").filter({ hasText: "已完成" }).first().waitFor({ state: "visible", timeout: 8_000 });
    } catch (error) {
      await page.screenshot({ path: resolve(outputDir, "session-authority-refresh-failed.png"), fullPage: true, animations: "disabled" });
      throw new Error(`${error.message}; body=${(await page.locator("body").innerText()).slice(-5000)}`);
    }
    await page.getByLabel("执行 Session").getByText("1/1", { exact: true }).waitFor({ state: "visible" });
    await page.getByText("权威 Session 已完成只读分析，并返回可核验结果。", { exact: true }).waitFor({ state: "visible" });
    if (await page.getByText("stale", { exact: true }).count()) throw new Error("Fresh Session result left a stale status visible");
    await page.getByText("运行记录", { exact: true }).waitFor({ state: "visible" });
    await page.screenshot({ path: resolve(outputDir, "session-execution-record.png"), fullPage: false, animations: "disabled" });
    await page.getByRole("tab", { name: "详情与操作" }).click();
    const correction = page.getByLabel("输入纠偏信息");
    const turnCountBeforeCorrection = api.turnRequests.length;
    await correction.fill("先核对权限边界，再继续推进。");
    await page.getByRole("button", { name: "发送纠偏" }).click();
    try {
      const correctionDeadline = Date.now() + 10_000;
      while (api.turnRequests.length <= turnCountBeforeCorrection && Date.now() < correctionDeadline) {
        await page.waitForTimeout(100);
      }
      await page.getByText(/已沿用当前 Goal/).last().waitFor({ state: "visible", timeout: 10_000 });
    } catch (error) {
      await page.screenshot({ path: resolve(outputDir, "run-correction-failed.png"), fullPage: true, animations: "disabled" });
      throw new Error(`${error.message}; turns=${JSON.stringify(api.turnRequests)}; errors=${pageErrors.join(" | ")}; body=${(await page.locator("body").innerText()).slice(0, 4000)}`);
    }
    const firstCorrection = api.turnRequests.slice(turnCountBeforeCorrection).find((turn) => turn.message === "先核对权限边界，再继续推进。");
    if (!firstCorrection?.sessionId || firstCorrection.sessionId.includes("manager")) throw new Error(`Run correction did not use the selected Goal's execution Session: ${JSON.stringify(firstCorrection)}`);
    pass(5, "Run-detail correction used a recoverable Goal-scoped Agent Session.");
    await page.getByRole("button", { name: /关闭详情/ }).click();

    const writesBeforeHeartbeat = api.durableWriteCount;
    await composer.fill("每天推进这个 Goal，设置 heartbeat");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    await page.getByRole("button", { name: "确认并应用", exact: true }).click();
    await page.getByText("需要宿主确认").waitFor({ state: "visible" });
    if (api.durableWriteCount !== writesBeforeHeartbeat) throw new Error("Protected heartbeat gate wrote durable state");
    pass(8, "Agent semantic protected intent creates only a typed preview, while discussion and targetless requests remain conversational and all protected-gate paths perform zero durable writes before confirmation.");
    pass(11, "Heartbeat apply surfaced an explicit host-activation gate.");
    const heartbeatPreview = api.actionPreviews.find((preview) => preview.action_kind === "heartbeat.bind");
    if (!heartbeatPreview) throw new Error("Continuation intent did not map to heartbeat.bind");
    await page.getByRole("button", { name: "关闭", exact: true }).click();

    await page.getByRole("button", { name: "Goal 详情" }).click();
    await page.getByRole("button", { name: "Tasks" }).click();
    const taskRow = page.locator(".personal-object-list", { hasText: "进行中" }).locator("button").first();
    await taskRow.click();
    await page.getByText("Todo 详情").waitFor({ state: "visible" });
    await page.getByRole("button", { name: "查看处理方式" }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    if (!api.actionPreviews.some((preview) => preview.action_kind === "todo.update" && preview.normalized_parameters.operation === "reassign")) throw new Error("Todo reassign did not create a typed preview");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await taskRow.click();
    await page.getByLabel("Todo 暂缓恢复条件").fill("pr_merged:huangruiteng/loopx#3399");
    await page.screenshot({ path: resolve(outputDir, "todo-defer-resume-condition.png"), fullPage: false, animations: "disabled" });
    await page.getByRole("button", { name: "检查暂缓", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    const explicitDefer = api.actionPreviews.findLast((preview) => preview.action_kind === "todo.update" && preview.normalized_parameters.operation === "defer");
    if (explicitDefer?.normalized_parameters.resume_when !== "pr_merged:huangruiteng/loopx#3399") throw new Error(`Todo defer did not preserve its supported resume condition: ${JSON.stringify(explicitDefer)}`);
    if (JSON.stringify(api.actionPreviews).includes("owner_resume")) throw new Error("Personal Workspace emitted the unsupported owner_resume sentinel");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    for (const [label, actionKind, operation] of [
      ["标记阻塞", "todo.update", "block"],
      ["标记完成", "todo.update", "complete"],
      ["创建后续 Todo", "todo.create", null],
    ]) {
      await taskRow.click();
      const moreMenu = page.locator("details.personal-compact-menu", { hasText: "更多操作" });
      if (!(await moreMenu.getAttribute("open"))) await moreMenu.locator("summary").click();
      await page.getByRole("button", { name: label, exact: true }).click();
      await page.getByText("确认执行").waitFor({ state: "visible" });
      if (!api.actionPreviews.some((preview) => preview.action_kind === actionKind && (operation === null || preview.normalized_parameters.operation === operation))) throw new Error(`Todo ${label} did not create the expected typed preview`);
      await page.getByRole("button", { name: "关闭", exact: true }).click();
    }
    await page.getByRole("navigation", { name: "Goal 视图" }).getByRole("button", { name: "Chat" }).click();
    await page.getByRole("dialog").filter({ hasText: "确认执行" }).waitFor({ state: "hidden" });

    await page.getByRole("button", { name: "配置定时检查" }).click();
    await page.getByLabel("向 LoopX 发送消息").fill("为当前 Goal 添加定时检查：\n检查内容：复盘是否包含已完成、阻塞、下周计划\n频率：每周五 17:00\n停止条件：Goal 完成");
    const previewsBeforeUnsupportedSchedule = api.actionPreviews.length;
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText(/不支持精确到星期或时刻的日历计划/).waitFor({ state: "visible" });
    if (api.actionPreviews.length !== previewsBeforeUnsupportedSchedule) throw new Error("Unsupported weekly schedule created a misleading preview");
    if (!(await page.getByLabel("向 LoopX 发送消息").inputValue()).includes("每周五 17:00")) throw new Error("Unsupported schedule draft was discarded");
    await page.getByLabel("向 LoopX 发送消息").fill("为当前 Goal 添加定时检查：\n检查内容：复盘是否包含已完成、阻塞、下周计划\n频率：每 2 小时\n停止条件：Goal 完成");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    const monitorCreate = api.actionPreviews.findLast((preview) => preview.action_kind === "monitor.create");
    if (!monitorCreate) throw new Error("Bounded monitor configuration did not map to monitor.create");
    if (monitorCreate.normalized_parameters.cadence !== "2h") throw new Error(`Monitor cadence drifted: ${JSON.stringify(monitorCreate.normalized_parameters)}`);
    if (monitorCreate.normalized_parameters.target !== "复盘是否包含已完成、阻塞、下周计划") throw new Error(`Monitor target drifted: ${JSON.stringify(monitorCreate.normalized_parameters)}`);
    await page.getByRole("button", { name: "关闭", exact: true }).click();

    await goalNavigation.getByRole("button", { name: "Chat" }).click();
    const schedule = page.locator(".personal-schedule-row").first();
    for (const [label, operation] of [["立即运行", "run_now"], ["暂停", "pause"], ["改为每 2 小时", "edit"], ["停止定时检查", "stop"]]) {
      await schedule.click();
      await page.getByText("定时检查", { exact: true }).last().waitFor({ state: "visible" });
      await page.getByRole("button", { name: label, exact: true }).click();
      await page.getByText("确认执行").waitFor({ state: "visible" });
      const monitorUpdate = api.actionPreviews.find((preview) => preview.action_kind === "monitor.update" && preview.normalized_parameters.operation === operation);
      if (!monitorUpdate) throw new Error(`Monitor ${operation} did not map to monitor.update`);
      if (operation === "pause") {
        const writesBeforeApply = api.durableWriteCount;
        await page.getByRole("button", { name: "确认并应用", exact: true }).click();
        await page.getByText("执行结果", { exact: true }).waitFor({ state: "visible" });
        await page.getByText("已应用，LoopX 状态将刷新。").waitFor({ state: "visible" });
        if (api.durableWriteCount !== writesBeforeApply + 1) throw new Error("Monitor confirmation did not produce exactly one durable write");
        if (!api.actionApplies.includes(monitorUpdate.proposalId)) throw new Error("Monitor confirmation did not apply the previewed proposal");
        await page.getByRole("button", { name: "查看更新后的 Goal", exact: true }).click();
        await goalNavigation.getByRole("button", { name: "Chat" }).click();
      } else {
        await page.getByRole("button", { name: "关闭", exact: true }).click();
      }
    }
    pass(10, "Continuation mapped to heartbeat.bind and bounded monitoring mapped to monitor.create/continuous_monitor UI.");

    const agentSelect = page.getByLabel("选择 Agent");
    const unavailableAgent = agentSelect.locator('option[value="offline-agent"]');
    if ((await unavailableAgent.count()) !== 1) throw new Error(`Unavailable Agent missing; options=${await agentSelect.locator("option").allTextContents()}`);
    const unavailableDisabled = (await unavailableAgent.getAttribute("disabled")) !== null;
    const unavailableLabel = await unavailableAgent.textContent();
    if (!unavailableDisabled || !unavailableLabel?.includes("不可用")) {
      throw new Error(`Unavailable Agent is selectable or lacks explanation; disabled=${unavailableDisabled}; label=${unavailableLabel}`);
    }
    pass(14, "Codex remained the healthy default and the unavailable Agent option was disabled with explanation.");
    await agentSelect.selectOption("claude-code");
    if ((await agentSelect.inputValue()) !== "claude-code") throw new Error("Healthy Agent selection did not update");
    await page.getByRole("button", { name: "刷新状态" }).click();

    await page.locator(".personal-run-row").first().click();
    await page.getByRole("tab", { name: "详情与操作" }).click();
    const runningCorrection = page.getByLabel("输入纠偏信息");
    await runningCorrection.fill("保持运行，等我检查中断控制。 ");
    await page.getByRole("button", { name: "发送纠偏" }).click();
    await page.getByText("更多运行操作").click();
    const interruptButton = page.getByRole("button", { name: "中断本次运行" });
    try {
      await interruptButton.waitFor({ state: "visible", timeout: 8_000 });
    } catch (error) {
      await page.screenshot({ path: resolve(outputDir, "interrupt-state-failed.png"), fullPage: true, animations: "disabled" });
      throw new Error(`${error.message}; body=${(await page.locator("body").innerText()).slice(-4000)}`);
    }
    await interruptButton.click();
    const secondCorrection = api.turnRequests.find((turn) => turn.message.includes("中断控制"));
    if (!secondCorrection || secondCorrection.sessionId === firstCorrection.sessionId) {
      throw new Error("Agent change reused the earlier Agent Session or failed to start the second correction");
    }
    if (!api.interrupts.some((turn) => turn.sessionId === secondCorrection.sessionId && turn.turnId === secondCorrection.turnId)) {
      throw new Error("Interrupt did not target the active Session and Turn");
    }
    await page.getByRole("button", { name: /关闭详情/ }).click();
    await page.getByText("已中断。你可以在当前会话继续发送消息。", { exact: true }).waitFor({ state: "visible", timeout: 10_000 });

    await page.locator(".personal-run-row").first().click();
    const rowHandle = page.locator(".personal-run-row").first();
    await page.getByRole("button", { name: /关闭详情/ }).press("Escape");
    await rowHandle.waitFor({ state: "visible" });
    if (!(await rowHandle.evaluate((element) => element === document.activeElement))) throw new Error("Drawer Escape did not restore focus to the selected row");

    await page.getByRole("button", { name: /LoopX 管家/ }).first().click();
    const needsYouCard = page.getByTestId("personal-home-lane-needs_you").locator(".personal-home-goal-card").first();
    const needsYouSource = await needsYouCard.locator("strong").innerText();
    const needsYouAction = await needsYouCard.locator("p").innerText();
    await needsYouCard.click();
    await page.getByRole("heading", { name: needsYouSource }).waitFor({ state: "visible" }).catch(() => {});
    await page.getByText(needsYouAction, { exact: true }).first().waitFor({ state: "visible" });
    await page.locator(".personal-object-list").first().getByRole("button").first().click();
    await page.getByText("需要你", { exact: true }).last().waitFor({ state: "visible" });
    await page.getByText("更多决定").click();
    await page.getByRole("button", { name: "稍后决定", exact: true }).click();
    await page.getByText("确认执行").waitFor({ state: "visible" });
    const deferredDecision = api.actionPreviews.find((preview) => preview.action_kind === "gate.resolve" && preview.normalized_parameters.decision === "defer");
    if (!deferredDecision) throw new Error("Decision defer did not create a Gate preview");
    await page.getByRole("button", { name: "稍后", exact: true }).click();
    await page.getByText(/已暂缓/).waitFor({ state: "visible" });
    if (!api.actionTransitions.some((transition) => transition.transition === "defer")) throw new Error("Proposal defer transition was not sent");
    await page.getByRole("button", { name: "关闭", exact: true }).click();
    await page.locator(".personal-manager-link").first().click();
    const sourceGoalCard = page.locator(".personal-home-goal-card").first();
    await sourceGoalCard.click();
    await goalNavigation.getByRole("button", { name: "Chat" }).click();
    if (!(await page.locator(".personal-run-row").count())) throw new Error("Source Goal did not expose its execution row after direct navigation");
    pass(3, "Needs-you and running cards navigate directly to their source Goal and expose typed details.");

    const visibleText = await page.locator("body").innerText();
    if (/session-goal-|turn-\d{6,}|\/Users\/|credential|provider payload|tool output/u.test(visibleText)) {
      fail(12, "Default surface exposes a raw runtime identifier, path, credential, or provider/tool payload.");
    } else {
      pass(12, "Default surface kept raw runtime ids, paths, credentials, and provider/tool payloads hidden.");
    }
    pass(13, "Manager cards retain Goal source lineage and Goal views retain Agent, schedule, and execution lineage.");

    await page.locator(".personal-goal-link").first().click();
    await goalNavigation.getByRole("button", { name: "Chat" }).click();
    await page.locator(".personal-run-row").first().click();
    await page.getByRole("tab", { name: "详情与操作" }).click();
    await page.getByLabel("输入纠偏信息").fill("保持运行，用于验证刷新恢复。 ");
    await page.getByRole("button", { name: "发送纠偏" }).click();
    let recoveryTurn;
    for (let attempt = 0; attempt < 40 && !recoveryTurn; attempt += 1) {
      recoveryTurn = api.turnRequests.find((turn) => turn.message.includes("刷新恢复"));
      if (!recoveryTurn) await page.waitForTimeout(50);
    }
    if (!recoveryTurn) throw new Error("Active recovery Turn was not accepted");

    try {
      await page.reload({ waitUntil: "networkidle" });
      await page.getByTestId("personal-goal-home").waitFor({ state: "visible" });
      await page.locator(".personal-goal-link").first().click();
      await goalNavigation.getByRole("button", { name: "Chat" }).click();
      await page.getByText("保持运行，用于验证刷新恢复。").waitFor({ state: "visible", timeout: 10_000 });
      await page.getByText("正在整理…").waitFor({ state: "hidden", timeout: 10_000 });
      const recovered = page.__loopxRuntime.sessions.get(recoveryTurn.sessionId);
      if (recovered?.active_turn_id !== null && recovered?.active_turn_id !== recoveryTurn.turnId) {
        throw new Error("Recovered Session points at a different active Turn");
      }
      pass(6, "Reload restored visible Goal history and resumed the active Turn SSE stream.");
    } catch (error) {
      fail(6, "Reload did not restore the active Goal conversation and reconnect its active Turn within 10 seconds.");
      await page.screenshot({ path: resolve(outputDir, "refresh-recovery-failed.png"), fullPage: true, animations: "disabled" });
      observations.push(`Refresh recovery failure: ${error.message}`);
    }

    const remote = await browser.newPage({ viewport: { width: 1512, height: 982 } });
    await installApi(remote);
    await remote.goto(url, { waitUntil: "networkidle" });
    await remote.getByRole("button", { name: "添加 SSH 隧道来源" }).click();
    await remote.getByLabel("本机 SSH Host").fill("remote-lab");
    await remote.getByText("ssh -N -L 8876:127.0.0.1:8766 remote-lab", { exact: true }).waitFor({ state: "visible" });
    await remote.getByRole("button", { name: "添加只读来源" }).click();
    await remote.getByText("远端只读投影", { exact: true }).waitFor({ state: "visible" });
    await remote.getByRole("button", { name: "添加 SSH 隧道来源" }).click();
    await remote.getByRole("tab", { name: "手动 URL" }).click();
    await remote.getByLabel("名称").fill("Remote build host");
    await remote.getByLabel("本地转发 URL").fill("http://127.0.0.1:8976/status.json");
    await remote.getByRole("button", { name: "添加只读来源" }).click();
    const remoteSourceSelect = remote.getByLabel("选择控制面来源");
    // 3 saved sources (本机 + remote-lab + Remote build host) plus the
    // quick-add optgroup exposing the remaining configured host (remote-build).
    if (await remoteSourceSelect.locator("option").count() !== 4) throw new Error("Multiple SSH tunnel sources were not retained in the source catalog");
    if (await remoteSourceSelect.locator("optgroup").count() !== 1) throw new Error("Configured SSH Host quick-add group is missing");
    await remoteSourceSelect.selectOption({ label: "remote-build" });
    await remote.locator(".personal-read-only-source", { hasText: "remote-build" }).waitFor({ state: "visible", timeout: 10_000 });
    pass(21, "Quick-add configured SSH host from the control-plane source dropdown.");
    await remoteSourceSelect.selectOption({ label: "remote-lab" });
    await remote.locator(".personal-read-only-source", { hasText: "remote-lab" }).waitFor({ state: "visible", timeout: 10_000 });
    await remote.locator(".personal-channel-composer").waitFor({ state: "detached", timeout: 3_000 });
    await remote.screenshot({ path: resolve(outputDir, "remote-read-only-source.png"), fullPage: false, animations: "disabled" });
    const visibleRemoteCreateButtons = await visibleElementCount(remote.locator('button[aria-label="创建 Goal"]'));
    if (visibleRemoteCreateButtons) throw new Error("Remote read-only source still exposed Goal creation");
    if (!(await remote.getByText("remote-lab", { exact: true }).count())) throw new Error("Remote source identity is not visible");
    await remote.locator(".personal-goal-link").first().click();
    await remote.getByRole("button", { name: "Tasks", current: "page" }).waitFor({ state: "visible" });
    await remote.locator(".personal-object-list", { hasText: "进行中" }).locator("button").first().click();
    await remote.getByText("Todo 详情").waitFor({ state: "visible" });
    const remoteTodoDrawer = remote.getByRole("dialog", { name: "Todo 详情" });
    for (const label of ["标记完成", "检查变更", "检查暂缓"]) {
      const visibleMatches = await visibleElementCount(remoteTodoDrawer.getByRole("button", { name: label, exact: true }));
      if (visibleMatches) throw new Error(`Remote Todo drawer exposed ${label}`);
    }
    await remote.getByRole("button", { name: /关闭详情/ }).click();
    await remote.locator(".personal-object-list", { hasText: "定时与持续" }).locator("button").first().click();
    await remote.getByText("定时检查", { exact: true }).last().waitFor({ state: "visible" });
    const remoteScheduleDrawer = remote.getByRole("dialog", { name: "定时检查" });
    for (const label of ["立即运行", "暂停", "改为每 2 小时", "停止定时检查"]) {
      const visibleMatches = await visibleElementCount(remoteScheduleDrawer.getByRole("button", { name: label, exact: true }));
      if (visibleMatches) {
        throw new Error(`Remote schedule drawer exposed ${label}: ${(await remoteScheduleDrawer.innerText()).slice(0, 2000)}`);
      }
    }
    await remote.close();

    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true });
    await installApi(mobile);
    await mobile.goto(url, { waitUntil: "networkidle" });
    await mobile.getByTestId("personal-goal-home").waitFor({ state: "visible" });
    const mobileOverflow = await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (mobileOverflow > 1) throw new Error(`Mobile workspace has ${mobileOverflow}px horizontal overflow`);
    await mobile.screenshot({ path: resolve(outputDir, "mobile-first-screen.png"), fullPage: false, animations: "disabled" });
    const mobileComposer = mobile.getByLabel("向 LoopX 发送消息");
    const composerBox = await mobileComposer.boundingBox();
    if (!composerBox || composerBox.y + composerBox.height > 844) throw new Error("Mobile composer is outside the visible safe area");
    const mobileNavigationTrigger = mobile.locator(".personal-mobile-menu");
    await mobileNavigationTrigger.click();
    if (await mobileNavigationTrigger.getAttribute("aria-expanded") !== "true") {
      throw new Error(`Mobile navigation state did not open: ${await mobile.locator(".personal-workspace-shell").getAttribute("class")}`);
    }
    const mobileNavigationDialog = mobile.getByRole("dialog", { name: "Goal 导航" });
    await mobileNavigationDialog.waitFor({ state: "visible" });
    const mobileNavigationClose = mobile.getByRole("button", { name: "关闭 Goal 导航" });
    if (!(await mobileNavigationClose.evaluate((element) => element === document.activeElement))) {
      throw new Error("Mobile navigation did not move focus into its close control");
    }
    const mobileMain = mobile.locator(".personal-workspace-main");
    if (await mobileMain.getAttribute("aria-hidden") !== "true" || !(await mobileMain.evaluate((element) => element.inert))) {
      throw new Error("Mobile navigation left the background workspace exposed to assistive navigation");
    }
    await mobile.keyboard.press("Shift+Tab");
    if (!(await mobileNavigationDialog.evaluate((element) => element.contains(document.activeElement)))) {
      throw new Error("Mobile navigation focus escaped its modal boundary");
    }
    await mobile.keyboard.press("Tab");
    if (!(await mobileNavigationClose.evaluate((element) => element === document.activeElement))) {
      throw new Error("Mobile navigation focus did not wrap to its first control");
    }
    const mobileSidebarProbe = await mobile.locator(".personal-workspace-sidebar").evaluate((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return { className: element.parentElement?.className, display: style.display, height: rect.height, width: rect.width, x: rect.x };
    });
    if (mobileSidebarProbe.display === "none" || mobileSidebarProbe.width < 100) {
      throw new Error(`Mobile sidebar did not become visible: ${JSON.stringify(mobileSidebarProbe)}`);
    }
    const mobileStoppedDirectory = mobile.locator(".personal-stopped-goals");
    if (await mobileStoppedDirectory.getAttribute("open") === null) await mobileStoppedDirectory.locator("summary").click();
    await mobile.screenshot({ path: resolve(outputDir, "mobile-goal-directory.png"), fullPage: false, animations: "disabled" });
    await mobile.keyboard.press("Escape");
    if (await mobileNavigationTrigger.getAttribute("aria-expanded") !== "false") {
      throw new Error("Mobile navigation did not close on Escape");
    }
    if (!(await mobileNavigationTrigger.evaluate((element) => element === document.activeElement))) {
      throw new Error("Mobile navigation did not restore focus to its trigger");
    }
    await mobileNavigationTrigger.click();
    const mobileManagerLink = mobile.locator(".personal-manager-link");
    try {
      await mobileManagerLink.waitFor({ state: "visible", timeout: 1500 });
    } catch {
      throw new Error(`Mobile manager link hidden after open: sidebar=${JSON.stringify(mobileSidebarProbe)} chain=${JSON.stringify(await mobileManagerLink.evaluate((element) => { const chain = []; let current = element; while (current && chain.length < 6) { const style = getComputedStyle(current); const rect = current.getBoundingClientRect(); chain.push({ className: current.className, display: style.display, height: rect.height, position: style.position, width: rect.width, x: rect.x }); current = current.parentElement; } return chain; }))}`);
    }
    await mobileManagerLink.click();
    await mobile.locator(".personal-home-board").waitFor({ state: "visible" });
    await mobile.close();
    if (await page.locator(".personal-workspace-shell").getAttribute("data-pw-theme") !== "paper") throw new Error("Personal workspace did not start with the default theme");
    if (await page.getByRole("button", { name: /切换到野兽主题|切换到默认主题/ }).count()) throw new Error("Workspace header still exposes the old theme toggle");
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("button", { name: /外观/ }).click();
    await page.getByRole("radio", { name: /高对比/ }).click();
    if (await page.locator(".personal-settings-page").getAttribute("data-pw-theme") !== "brutal") throw new Error("Settings did not enable the high-contrast theme");
    await page.getByRole("radio", { name: /默认/ }).click();
    if (await page.locator(".personal-settings-page").getAttribute("data-pw-theme") !== "paper") throw new Error("Settings did not restore the default theme");
    await page.getByRole("button", { name: "返回工作区", exact: true }).click();
    if (await page.locator(".personal-workspace-shell").getAttribute("data-pw-theme") !== "paper") throw new Error("Workspace did not apply the Settings theme readback");
    pass(16, "The Settings appearance tab toggles the high-contrast theme and returns to the default theme.");
    await page.locator(".personal-manager-link").first().click();
    await page.waitForTimeout(600);
    const workerCards = await page.locator(".personal-worker-strip > button").count();
    if (workerCards !== 0) throw new Error(`Redundant Agent worker strip is still visible: ${workerCards}`);
    if (!(await page.locator(".personal-digest-card").isVisible().catch(() => false))) throw new Error("Morning digest card did not render on the manager home");
    pass(17, "Manager home keeps the morning digest while omitting the redundant Agent worker strip.");
    pass(20, "Empty and populated Tasks boards keep identical width and four equal columns at desktop and wide desktop viewports.");
    const report = { criteria: Object.fromEntries(results), observations };
    await writeFile(resolve(outputDir, "acceptance-results.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
    console.log(`personal-workspace-browser-smoke: ok\npreview=${url}\nscreenshot=${resolve(outputDir, "desktop-first-screen.png")}`);
    const failures = [...results.entries()].filter(([, result]) => result.status !== "PASS");
    if (failures.length) throw new Error(`Acceptance failures: ${failures.map(([criterion, result]) => `${criterion} ${result.status}: ${result.note}`).join(" | ")}`);
  } finally {
    if ([...results.values()].some((result) => result.status !== "PASS")) {
      await writeFile(resolve(outputDir, "acceptance-results.json"), `${JSON.stringify({ criteria: Object.fromEntries(results), observations }, null, 2)}\n`, "utf8");
    }
    await browser?.close();
    server.kill("SIGTERM");
  }
}

await main();

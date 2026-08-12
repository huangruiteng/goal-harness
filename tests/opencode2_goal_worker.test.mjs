import assert from "node:assert/strict"
import test from "node:test"

import {
  CONTINUATION_PROMPT,
  createApiTransport,
  createStateStore,
  isTerminalNoFollowup,
  leaseIsLive,
  parseWorkerArgs,
  retryPlan,
  runWorker,
  sanitizedStateName,
  shouldRunNow,
  turnVerdict,
  waitPlan,
} from "../loopx/opencode2_goal_mode/opencode2-goal-worker.mjs"


function terminalDecision() {
  return {
    should_run: false,
    effective_action: "terminal_no_followup",
    reason: "validated closure",
    goal_frontier_projection: {
      terminal_state: {
        schema_version: "goal_terminal_state_v0",
        kind: "no_followup",
        derived: true,
        source: "validated_goal_closure",
      },
      source_completeness: {
        schema_version: "goal_terminal_source_completeness_v0",
        user_todos: "valid",
        agent_todos: "valid",
      },
    },
  }
}


function waitDecision() {
  return {
    should_run: false,
    scheduler_hint: {
      action: "backoff_waiting_for_user",
      reset_policy: { reset_token: "wait-token" },
      unchanged_poll: {
        local_scheduler: {
          recommended_interval_minutes: 3,
          example_progression_minutes: [3, 6, 12],
          unchanged_poll_limit: 3,
        },
      },
    },
  }
}


function memoryStateStore() {
  const states = new Map()
  const locks = new Map()
  return {
    states,
    locks,
    async read(goalId) {
      return states.get(goalId) || null
    },
    async write(goalId, state) {
      const value = {
        schemaVersion: "loopx_opencode2_goal_worker_v0",
        goalId,
        ...state,
        updatedAt: new Date().toISOString(),
      }
      states.set(goalId, value)
      return value
    },
    lockPath(goalId) {
      return `memory://${goalId}.lock`
    },
    async acquireLock(goalId, options = {}) {
      if (locks.get(goalId)) {
        return {
          acquired: false,
          holder: locks.get(goalId),
          reason: "held by another driver",
        }
      }
      locks.set(goalId, { pid: process.pid, heartbeatAt: new Date().toISOString() })
      return {
        acquired: true,
        holder: { pid: process.pid },
        reason: "",
        release: async () => {
          locks.delete(goalId)
        },
      }
    },
  }
}


function fakeTransport({ pausedUserId = null } = {}) {
  const calls = { prompts: [], synthetics: [], sessions: 0, exists: 0 }
  const userMessages = []
  const assistantMessages = []
  let nextId = 1
  return {
    calls,
    userMessages,
    assistantMessages,
    async createSession() {
      calls.sessions += 1
      return `ses_fake_${nextId++}`
    },
    async sessionExists() {
      calls.exists += 1
      return true
    },
    async listMessages() {
      await new Promise((resolve) => setImmediate(resolve))
      const lastUser = userMessages.at(-1)
      const lastAssistant = assistantMessages.at(-1)
      if (lastUser && (!lastAssistant || lastAssistant.created < lastUser.created)) {
        assistantMessages.push({
          id: `msg_asst_${nextId++}`,
          created: lastUser.created + 1,
          completed: lastUser.created + 2,
        })
      }
      const messages = [
        ...userMessages.map((user) => ({
          id: user.id,
          type: "user",
          text: user.text,
          time: { created: user.created },
        })),
        ...assistantMessages.map((assistant) => ({
          id: assistant.id,
          type: "assistant",
          finish: assistant.finish ?? "stop",
          time: { created: assistant.created, completed: assistant.completed },
        })),
      ]
      return messages
    },
    async sendPrompt(_sessionID, text) {
      const message = { id: `msg_user_${nextId}`, text, created: Date.now() + nextId }
      nextId += 1
      userMessages.push(message)
      calls.prompts.push(text)
      return message.id
    },
    async sendSynthetic(_sessionID, text) {
      calls.synthetics.push(text)
      return `msg_syn_${nextId++}`
    },
    async waitForSession() {
      await new Promise((resolve) => setImmediate(resolve))
      return true
    },
    async sessionInfo() {
      return { time: { updated: Date.now() } }
    },
    addUserMessage(text) {
      const message = { id: `msg_ext_${nextId++}`, text, created: Date.now() + 100_000 }
      userMessages.push(message)
      return message.id
    },
  }
}


function makeWorkerOverrides({ decisions, transport, stateStore, sleepMs = [] } = {}) {
  let probeIndex = 0
  return {
    transport,
    stateStore,
    quotaProbe: async () => {
      const decision = decisions[Math.min(probeIndex, decisions.length - 1)]
      probeIndex += 1
      if (decision instanceof Error) throw decision
      return decision
    },
    sleepImpl: async () => {
      sleepMs.push("slept")
    },
  }
}


test("sanitizedStateName keeps goal ids filesystem-safe", () => {
  assert.equal(sanitizedStateName("a/b\\c d"), "a_b_c_d")
  assert.throws(() => sanitizedStateName(""), /goal id is required/)
})


test("leaseIsLive honors fresh heartbeats and stale heartbeats from dead pids", async () => {
  const now = () => 1_000_000
  // A fresh heartbeat holds the lease even when the pid already exited;
  // the worker must wait out the staleness window instead of double-driving.
  assert.equal(
    await leaseIsLive({ pid: 999_999_999, heartbeatAt: new Date(now() - 1000).toISOString() }, { staleMs: 5000, now }),
    true,
  )
  // A stale heartbeat from a dead pid releases the lease.
  assert.equal(
    await leaseIsLive({ pid: 999_999_999, heartbeatAt: new Date(now() - 9000).toISOString() }, { staleMs: 5000, now }),
    false,
  )
  // A live pid with a stale heartbeat still holds the lease.
  assert.equal(
    await leaseIsLive({ pid: process.pid, heartbeatAt: new Date(now() - 9000).toISOString() }, { staleMs: 5000, now }),
    true,
  )
})


test("turnVerdict completes only after a final non-tool-call reply to the newest own prompt", () => {
  const own = (id, created) => ({ id, type: "user", text: "go", time: { created } })
  const assistant = (created, completed, finish = "stop") => ({ id: "a", type: "assistant", time: { created, completed }, finish })
  assert.equal(turnVerdict([], ["own-1"]).waiting, true)
  assert.equal(turnVerdict([assistant(10, 20)], ["own-1"]).waiting, true)
  assert.equal(turnVerdict([own("own-1", 10)], ["own-1"]).waiting, true)
  assert.equal(
    turnVerdict([own("own-1", 10), assistant(11, 12)], ["own-1"]).completed,
    true,
  )
  // A stale assistant reply from a previous turn must not complete a new prompt.
  assert.equal(
    turnVerdict([own("own-1", 10), assistant(11, 12), own("own-2", 20)], ["own-1", "own-2"]).completed,
    false,
  )
  // An intermediate tool-call step completes its message but not the turn.
  assert.equal(
    turnVerdict([own("own-1", 10), assistant(11, 12, "tool-calls")], ["own-1"]).completed,
    false,
  )
  // A later final step ends the same turn.
  assert.equal(
    turnVerdict(
      [own("own-1", 10), assistant(11, 12, "tool-calls"), assistant(13, 14, "stop")],
      ["own-1"],
    ).completed,
    true,
  )
  const paused = turnVerdict([own("stranger", 30)], ["own-1", "own-2"])
  assert.equal(paused.completed, false)
  assert.equal(paused.pausedByUser.id, "stranger")
})


test("waitPlan stops at the unchanged-poll limit and follows the progression ladder", () => {
  const decision = waitDecision()
  assert.deepEqual(waitPlan(decision, { schedulerToken: "", unchangedPolls: 0 }), {
    stop: false,
    minutes: 3,
    schedulerToken: "wait-token",
    unchangedPolls: 1,
  })
  assert.deepEqual(waitPlan(decision, { schedulerToken: "wait-token", unchangedPolls: 1 }), {
    stop: false,
    minutes: 6,
    schedulerToken: "wait-token",
    unchangedPolls: 2,
  })
  assert.deepEqual(waitPlan(decision, { schedulerToken: "wait-token", unchangedPolls: 2 }), {
    stop: false,
    minutes: 12,
    schedulerToken: "wait-token",
    unchangedPolls: 3,
  })
  assert.equal(waitPlan(decision, { schedulerToken: "wait-token", unchangedPolls: 3 }).stop, true)
  assert.equal(waitPlan({ should_run: false, scheduler_hint: {} }, {}).stop, true)
})


test("retryPlan backs off exponentially with a ceiling", () => {
  assert.equal(retryPlan({}, {}).minutes, 3)
  assert.equal(retryPlan({}, { probeRetryCount: 1 }).minutes, 6)
  assert.equal(retryPlan({}, { probeRetryCount: 4 }).minutes, 30)
  assert.equal(retryPlan({}, { probeRetryCount: 9 }).minutes, 30)
})


test("decision helpers recognize terminal closure and run_now", () => {
  assert.equal(isTerminalNoFollowup(terminalDecision()), true)
  assert.equal(shouldRunNow({ should_run: true }), true)
  assert.equal(shouldRunNow({ scheduler_hint: { action: "run_now" } }), true)
  assert.equal(shouldRunNow({ should_run: false }), false)
})


test("worker drives a full loop: task prompt, run_now continuation, then terminal", async () => {
  const stateStore = memoryStateStore()
  const transport = fakeTransport()
  const sleepMs = []
  const overrides = makeWorkerOverrides({
    transport,
    stateStore,
    sleepMs,
    decisions: [
      { should_run: true, scheduler_hint: { action: "run_now" } },
      terminalDecision(),
    ],
  })
  const result = await runWorker({
    goalId: "goal-e2e",
    directory: "/workspace",
    taskBody: "Ship the task.",
    ...overrides,
  })
  assert.equal(result.kind, "terminal")
  assert.deepEqual(transport.calls.prompts, ["Ship the task.", CONTINUATION_PROMPT])
  assert.equal(transport.calls.synthetics.length, 1)
  const state = await stateStore.read("goal-e2e")
  assert.equal(state.phase, "terminal")
  assert.equal(state.autoResume, false)
  assert.equal(state.turnCount, 1)
})


test("worker waits quietly between quota polls without prompting", async () => {
  const stateStore = memoryStateStore()
  const transport = fakeTransport()
  const sleepMs = []
  const overrides = makeWorkerOverrides({
    transport,
    stateStore,
    sleepMs,
    decisions: [waitDecision(), terminalDecision()],
  })
  const result = await runWorker({ goalId: "goal-wait", directory: "/workspace", taskBody: "Task.", ...overrides })
  assert.equal(result.kind, "terminal")
  assert.equal(transport.calls.prompts.length, 1)
  assert.ok(sleepMs.length >= 1)
  const state = await stateStore.read("goal-wait")
  assert.equal(state.unchangedPolls, 1)
  assert.equal(state.schedulerToken, "wait-token")
})


test("worker pauses visibly when the unchanged-poll limit stops the loop", async () => {
  const stateStore = memoryStateStore()
  const transport = fakeTransport()
  const limitDecision = {
    should_run: false,
    scheduler_hint: {
      action: "backoff_waiting_for_user",
      reset_policy: { reset_token: "stop-token" },
      unchanged_poll: {
        local_scheduler: {
          recommended_interval_minutes: 3,
          example_progression_minutes: [3, 6],
          unchanged_poll_limit: 1,
        },
      },
    },
  }
  const overrides = makeWorkerOverrides({
    transport,
    stateStore,
    decisions: [limitDecision],
  })
  const result = await runWorker({ goalId: "goal-stop", directory: "/workspace", taskBody: "Task.", ...overrides })
  assert.equal(result.kind, "limit_stopped")
  assert.equal(transport.calls.prompts.length, 1)
  assert.ok(transport.calls.synthetics.some((text) => text.includes("unchanged-poll limit")))
  const state = await stateStore.read("goal-stop")
  assert.equal(state.phase, "limit_stopped")
  assert.equal(state.autoResume, false)
  assert.equal(state.pausedReason, "unchanged_poll_limit")
})


test("worker pauses visibly after an external user message", async () => {
  const stateStore = memoryStateStore()
  const transport = fakeTransport()
  const overrides = makeWorkerOverrides({
    transport,
    stateStore,
    decisions: [{ should_run: true, scheduler_hint: { action: "run_now" } }],
  })
  const run = runWorker({ goalId: "goal-pause", directory: "/workspace", taskBody: "Task.", ...overrides })
  await new Promise((resolve) => setTimeout(resolve, 0))
  transport.addUserMessage("hold on")
  const result = await run
  assert.equal(result.kind, "paused_user_intervention")
  const state = await stateStore.read("goal-pause")
  assert.equal(state.autoResume, false)
  assert.equal(state.pausedReason, "user_message")
  assert.ok(transport.calls.synthetics.some((text) => text.includes("user intervention")))
})


test("worker refuses to start while another live lease holds the goal", async () => {
  const stateStore = memoryStateStore()
  await stateStore.acquireLock("goal-held")
  const transport = fakeTransport()
  const overrides = makeWorkerOverrides({
    transport,
    stateStore,
    decisions: [],
  })
  const result = await runWorker({
    goalId: "goal-held",
    directory: "/workspace",
    taskBody: "Task.",
    ...overrides,
  })
  assert.equal(result.kind, "lease_held")
  assert.equal(transport.calls.prompts.length, 0)
})


test("worker backs off quota probe failures and resets on success", async () => {
  const stateStore = memoryStateStore()
  const transport = fakeTransport()
  const sleepMs = []
  const decisions = [
    new Error("probe timeout"),
    { should_run: true, scheduler_hint: { action: "run_now" } },
    terminalDecision(),
  ]
  const overrides = makeWorkerOverrides({ transport, stateStore, sleepMs, decisions })
  const result = await runWorker({ goalId: "goal-probe-fail", directory: "/workspace", taskBody: "Task.", ...overrides })
  assert.equal(result.kind, "terminal")
  const state = await stateStore.read("goal-probe-fail")
  assert.equal(state.probeRetryCount, 0)
})


test("worker skips a paused state unless forceResume is set", async () => {
  const stateStore = memoryStateStore()
  await stateStore.write("goal-paused-state", {
    directory: "/workspace",
    agentId: "",
    registryPath: "",
    availableCapabilities: [],
    sessionID: "ses_fake_1",
    autoResume: false,
    phase: "paused_user_intervention",
    schedulerToken: "",
    unchangedPolls: 0,
    probeRetryCount: 0,
    turnCount: 1,
    sentPromptIds: [],
  })
  const transport = fakeTransport()
  const overrides = makeWorkerOverrides({ transport, stateStore, decisions: [] })
  const result = await runWorker({
    goalId: "goal-paused-state",
    directory: "/workspace",
    ...overrides,
  })
  assert.equal(result.kind, "paused_state")
  assert.equal(transport.calls.prompts.length, 0)
})


test("worker reports a deleted bound session instead of recreating it", async () => {
  const stateStore = memoryStateStore()
  await stateStore.write("goal-deleted", {
    directory: "/workspace",
    agentId: "",
    registryPath: "",
    availableCapabilities: [],
    sessionID: "ses_gone",
    autoResume: true,
    phase: "working",
    schedulerToken: "",
    unchangedPolls: 0,
    probeRetryCount: 0,
    turnCount: 1,
    sentPromptIds: [],
  })
  const transport = fakeTransport()
  transport.sessionExists = async () => false
  const overrides = makeWorkerOverrides({ transport, stateStore, decisions: [] })
  const result = await runWorker({
    goalId: "goal-deleted",
    directory: "/workspace",
    ...overrides,
  })
  assert.equal(result.kind, "session_deleted")
  const state = await stateStore.read("goal-deleted")
  assert.equal(state.phase, "session_deleted")
})


test("worker stops after the turn budget and posts a visible notice", async () => {
  const stateStore = memoryStateStore()
  await stateStore.write("goal-turns", {
    directory: "/workspace",
    agentId: "",
    registryPath: "",
    availableCapabilities: [],
    sessionID: "ses_fake_1",
    autoResume: true,
    phase: "working",
    schedulerToken: "",
    unchangedPolls: 0,
    probeRetryCount: 0,
    turnCount: 3,
    sentPromptIds: ["msg_user_old"],
  })
  const transport = fakeTransport()
  const overrides = makeWorkerOverrides({ transport, stateStore, decisions: [] })
  const result = await runWorker({
    goalId: "goal-turns",
    directory: "/workspace",
    maxTurns: 3,
    ...overrides,
  })
  assert.equal(result.kind, "turn_limit")
  assert.ok(transport.calls.synthetics.some((text) => text.includes("turn budget")))
})


test("createApiTransport probes the opencode2 api CLI shape", () => {
  assert.equal(typeof createApiTransport().sendPrompt, "function")
  assert.equal(typeof createApiTransport().sendSynthetic, "function")
})


test("parseWorkerArgs maps repeated capabilities and rejects unknown flags", () => {
  const args = parseWorkerArgs([
    "--goal-id",
    "goal-args",
    "--directory",
    "/tmp",
    "--capability",
    "shell",
    "--capability",
    "edit",
    "--force-resume",
  ])
  assert.equal(args.goalId, "goal-args")
  assert.equal(args.directory, "/tmp")
  assert.deepEqual(args.availableCapabilities, ["shell", "edit"])
  assert.equal(args.forceResume, true)
  assert.throws(() => parseWorkerArgs(["--bogus"]), /unknown argument/)
})


test("createQuotaProbe reads a denied decision that exits non-zero", async () => {
  const { createQuotaProbe } = await import("../loopx/opencode2_goal_mode/opencode2-goal-worker.mjs")
  const denied = JSON.stringify({
    ok: false,
    should_run: false,
    effective_action: "operator_gate_notify",
    scheduler_hint: { unchanged_poll: { local_scheduler: null } },
  })
  const execFileImpl = async () => {
    const error = new Error("Command failed")
    error.stdout = denied
    throw error
  }
  const probe = createQuotaProbe({ execFileImpl })
  const decision = await probe(
    { goalId: "goal-denied", directory: "/workspace", registryPath: "", agentId: "", availableCapabilities: [] },
    { directory: "/workspace" },
  )
  assert.equal(decision.should_run, false)
})


test("worker pauses when the session stops making progress", async () => {
  const stateStore = memoryStateStore()
  const transport = fakeTransport()
  const frozenAt = Date.now() - 100_000
  transport.sessionInfo = async () => ({ time: { updated: frozenAt } })
  transport.listMessages = async () => {
    await new Promise((resolve) => setImmediate(resolve))
    return transport.userMessages.map((user) => ({
      id: user.id,
      type: "user",
      text: user.text,
      time: { created: user.created },
    }))
  }
  const overrides = makeWorkerOverrides({
    transport,
    stateStore,
    decisions: [],
  })
  const result = await runWorker({
    goalId: "goal-stalled",
    directory: "/workspace",
    taskBody: "Task.",
    ...overrides,
    waitTurnOptions: { stallMs: 1000 },
  })
  assert.equal(result.kind, "session_stalled")
  const state = await stateStore.read("goal-stalled")
  assert.equal(state.phase, "session_stalled")
  assert.equal(state.autoResume, false)
  assert.equal(state.pausedReason, "session_stalled")
  assert.ok(transport.calls.synthetics.some((text) => text.includes("stopped making progress")))
})

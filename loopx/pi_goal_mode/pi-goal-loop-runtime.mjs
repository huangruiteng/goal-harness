// <!-- loopx-managed-slash-command:v1 command=/loopx surface=pi-extension-runtime -->
//
// LoopX Pi goal loop runtime — the pure, directly executable core of the Pi
// host adapter. The installed extension (loopx-goal.ts) wires Pi's
// ExtensionAPI into createGoalLoop; node:test drives this same module through
// injected dependencies (tests/pi_goal_loop_runtime.test.mjs), so the
// store/quota/wait lifecycle is verified at runtime instead of by string
// matching.
//
// Lifecycle contract:
// - Only LoopX-derived terminal state stops auto-continuation; the loop never
//   self-declares closure.
// - Quota probe failures fail closed with a bounded retry instead of guessing.
// - dispose() atomically invalidates the extension instance: every timer is
//   cancelled, and an evaluation that is mid-flight across an await returns to
//   an epoch guard before any write / notify / send / timer side effect, so it
//   can never continue the old session past a reload / session-replacement
//   boundary.
// - Goal identity is a binding contract: every binding carries a per-session
//   generation that activate() increments, and every evaluation write commits
//   through the store's compare-and-swap (expected generation + goalId). A
//   stale evaluation whose write was already in-flight when the same session
//   activated a new goal is rejected at the store commit boundary, so it can
//   never merge old terminal/scheduler state or send the old task body.
// - Sessions without a session file (pi --no-session, ephemeral) use a unique
//   in-memory identity per extension instance and are never persisted, so a
//   later run cannot inherit the previous run's binding.
import { createHash, randomUUID } from "node:crypto"
import { promises as fs } from "node:fs"
import path from "node:path"

export const BRIDGE_SCHEMA_VERSION = "loopx_pi_goal_bridge_v0"
export const TERMINAL_STATE_SCHEMA_VERSION = "goal_terminal_state_v0"
export const SOURCE_COMPLETENESS_SCHEMA_VERSION = "goal_terminal_source_completeness_v0"
export const DEFAULT_RETRY_MINUTES = 3

// The label prefix of a session key reserves room for the digest suffix so
// that createBindingStore's filename sanitization (160 chars) can never cut
// the digest off: label(48) + "-" + digest(16) = 65 chars.
const SESSION_KEY_LABEL_MAX = 48
const SESSION_KEY_DIGEST_LENGTH = 16

export function sanitizedKey(value) {
  const cleaned = String(value || "")
    .replace(/[^A-Za-z0-9_-]/g, "_")
    .slice(0, 160)
  return cleaned || "session"
}

// Collision-resistant session key from the full session file path. Uses a
// short human-readable basename prefix plus a SHA-256 digest of the complete
// path, so two files whose first 161 bytes are identical never produce the
// same durable key and the digest always survives filename sanitization.
export function sessionKey(sessionFile) {
  const digest = createHash("sha256")
    .update(sessionFile)
    .digest("hex")
    .slice(0, SESSION_KEY_DIGEST_LENGTH)
  const label = sanitizedKey(path.basename(sessionFile)).slice(0, SESSION_KEY_LABEL_MAX)
  return label ? `${label}-${digest}` : `session-${digest}`
}

export function stateRoot(directory) {
  if (process.env.LOOPX_PI_STATE_DIR) {
    return path.resolve(process.env.LOOPX_PI_STATE_DIR)
  }
  return path.join(directory, ".loopx", "pi")
}

function bindingDefaults(directory) {
  return {
    schemaVersion: BRIDGE_SCHEMA_VERSION,
    directory,
    goalId: "",
    agentId: "",
    registryPath: "",
    availableCapabilities: [],
    taskBody: "",
    autoResume: true,
    terminal: false,
    generation: 0,
    schedulerToken: "",
    unchangedPolls: 0,
    lastInjectedPrompt: "",
  }
}

function casMatches(current, expected) {
  if (!expected) return true
  if (expected.generation !== undefined && (current?.generation || 0) !== expected.generation) {
    return false
  }
  if (expected.goalId !== undefined && (current?.goalId || "") !== expected.goalId) {
    return false
  }
  return true
}

// File-backed binding store scoped to one project. Bindings live under the
// gitignored `.loopx/` tree so they survive Pi restarts without touching
// tracked repository state. Writes for one key are serialized through a queue,
// and the optional `expected` argument turns a write into a compare-and-swap:
// the commit is rejected (returns null) unless the persisted generation and
// goalId still match, so a stale evaluation can never overwrite a newly
// activated binding.
export function createBindingStore(directory) {
  const root = stateRoot(directory)
  const target = (key) => path.join(root, `${sanitizedKey(key)}.json`)
  const queues = new Map()
  const enqueue = (key, task) => {
    const previous = queues.get(key) || Promise.resolve()
    const next = previous.then(task)
    queues.set(
      key,
      next.then(
        () => {},
        () => {},
      ),
    )
    return next
  }
  return {
    async read(key) {
      try {
        const payload = JSON.parse(await fs.readFile(target(key), "utf8"))
        if (payload?.schemaVersion !== BRIDGE_SCHEMA_VERSION || payload?.sessionKey !== key) {
          return null
        }
        return payload
      } catch (error) {
        if (error?.code === "ENOENT") return null
        throw error
      }
    },
    async write(key, changes, expected) {
      return enqueue(key, async () => {
        const current = await this.read(key)
        if (!casMatches(current, expected)) return null
        const payload = {
          ...bindingDefaults(directory),
          sessionKey: key,
          ...(current || {}),
          ...changes,
          updatedAt: new Date().toISOString(),
        }
        await fs.mkdir(root, { recursive: true, mode: 0o700 })
        const destination = target(key)
        const temporary = `${destination}.${process.pid}.${Date.now()}.tmp`
        await fs.writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, {
          encoding: "utf8",
          mode: 0o600,
        })
        await fs.rename(temporary, destination)
        return payload
      })
    },
    async remove(key) {
      return enqueue(key, async () => {
        try {
          await fs.unlink(target(key))
        } catch (error) {
          if (error?.code !== "ENOENT") throw error
        }
      })
    },
  }
}

// In-memory binding store for ephemeral sessions: nothing ever reaches the
// filesystem, so a `pi --no-session` run cannot leak a binding to a later run.
// Single-threaded Map access makes the compare-and-swap atomic.
export function createMemoryBindingStore() {
  const bindings = new Map()
  return {
    bindings,
    async read(key) {
      return bindings.get(key) || null
    },
    async write(key, changes, expected) {
      const current = bindings.get(key) || {}
      if (!casMatches(current, expected)) return null
      const payload = {
        ...bindingDefaults(""),
        sessionKey: key,
        ...current,
        ...changes,
      }
      bindings.set(key, payload)
      return payload
    },
    async remove(key) {
      bindings.delete(key)
    },
  }
}

// Per-extension-instance identity for sessions without a session file. Every
// instance gets a unique key and its own in-memory store, so consecutive
// `--no-session` runs can never inherit a previous run's binding; the current
// run must activate the goal again through loopx_goal_activate.
export function createEphemeralSessionIdentity() {
  return {
    key: `ephemeral-${randomUUID()}`,
    store: createMemoryBindingStore(),
  }
}

// Mirrors the OpenCode bridge probe: LoopX quota should-run is the only
// continuation authority for the visible goal loop.
export function buildQuotaArgs(binding) {
  const args = []
  if (binding.registryPath) args.push("--registry", binding.registryPath)
  args.push(
    "--format",
    "json",
    "quota",
    "should-run",
    "--goal-id",
    binding.goalId,
    "--runtime-profile",
    "generic_cli",
    "--include-detail",
    "scheduler",
  )
  if (binding.agentId) args.push("--agent-id", binding.agentId)
  for (const capability of binding.availableCapabilities || []) {
    args.push("--available-capability", capability)
  }
  return args
}

export function isTerminalNoFollowup(decision) {
  const frontier = decision?.goal_frontier_projection
  const terminal = frontier?.terminal_state
  const completeness = frontier?.source_completeness
  return Boolean(
    decision?.should_run === false &&
      decision?.effective_action === "terminal_no_followup" &&
      terminal?.schema_version === TERMINAL_STATE_SCHEMA_VERSION &&
      terminal?.kind === "no_followup" &&
      terminal?.derived === true &&
      terminal?.source === "validated_goal_closure" &&
      completeness?.schema_version === SOURCE_COMPLETENESS_SCHEMA_VERSION &&
      completeness?.user_todos === "valid" &&
      completeness?.agent_todos === "valid",
  )
}

export function shouldRunNow(decision) {
  const hint = decision?.scheduler_hint
  return hint?.action === "run_now" || decision?.should_run === true
}

export function waitPlan(decision, binding) {
  const hint = decision?.scheduler_hint || {}
  const unchanged = hint?.unchanged_poll || {}
  const local = unchanged?.local_scheduler
  if (!local || local === "stop") {
    return {
      stop: true,
      minutes: DEFAULT_RETRY_MINUTES,
      schedulerToken: binding.schedulerToken,
      unchangedPolls: binding.unchangedPolls,
    }
  }
  const reset = hint?.reset_policy || {}
  const token = String(reset?.reset_token || "")
  const sameIdentity = Boolean(token) && token === binding.schedulerToken
  const unchangedPolls = sameIdentity ? Number(binding.unchangedPolls || 0) : 0
  const limit = Number.isInteger(local.unchanged_poll_limit)
    ? Number(local.unchanged_poll_limit)
    : null
  if (limit !== null && unchangedPolls >= limit) {
    return {
      stop: true,
      minutes: DEFAULT_RETRY_MINUTES,
      schedulerToken: token,
      unchangedPolls,
    }
  }
  const progression = Array.isArray(local.example_progression_minutes)
    ? local.example_progression_minutes.filter((value) => Number(value) > 0)
    : []
  const fallback = Number(local.recommended_interval_minutes || DEFAULT_RETRY_MINUTES)
  const minutes = progression.length
    ? Number(progression[Math.min(unchangedPolls, progression.length - 1)])
    : fallback
  return {
    stop: false,
    minutes: Number.isFinite(minutes) && minutes > 0 ? minutes : DEFAULT_RETRY_MINUTES,
    schedulerToken: token,
    unchangedPolls: unchangedPolls + 1,
  }
}

// The quota-gated auto-continuation loop for one extension instance.
//
// options:
//   quotaProbe(binding)      async LoopX quota should-run probe
//   sendMessage(prompt)      inject the heartbeat task body as a follow-up
//   setTimer(cb, delayMs)    schedule a timer, returns an opaque handle
//   clearTimer(handle)       cancel a scheduled timer
//
// The loop keeps per-session timers and evaluations but owns one instance-wide
// epoch, so session shutdown atomically invalidates every session's scheduled
// and in-flight work at once. Goal identity is enforced through the binding's
// persisted generation: activate() increments it and every evaluation write
// commits via the store's compare-and-swap with the captured generation and
// goalId, so a stale evaluation cannot commit past a re-activation even when
// its write was already in-flight.
export function createGoalLoop(options) {
  const { quotaProbe, sendMessage, setTimer, clearTimer } = options
  const timers = new Map()
  const evaluations = new Map()
  const contexts = new Map()
  let disposed = false
  let epoch = 0

  const cancelScheduled = (key) => {
    const timer = timers.get(key)
    if (timer !== undefined) clearTimer(timer)
    timers.delete(key)
  }

  const cancelAll = () => {
    for (const timer of timers.values()) clearTimer(timer)
    timers.clear()
    evaluations.clear()
  }

  const scheduleEvaluation = (key, minutes) => {
    if (disposed) return
    cancelScheduled(key)
    const scheduledEpoch = epoch
    const timer = setTimer(async () => {
      timers.delete(key)
      if (disposed || epoch !== scheduledEpoch) return
      try {
        await evaluateIdle(key)
      } catch {
        // Evaluation must never crash the host; fail closed with a retry.
        scheduleEvaluation(key, DEFAULT_RETRY_MINUTES)
      }
    }, Math.max(1, minutes) * 60_000)
    timers.set(key, timer)
  }

  const evaluateIdleOnce = async (key) => {
    if (disposed) return
    const instanceEpoch = epoch
    const services = contexts.get(key)
    if (!services) {
      cancelScheduled(key)
      return
    }
    const { store, isIdle } = services
    // Every store write inside this evaluation can throw (disk error,
    // permission denied). The timer callback already reschedules on error;
    // this top-level catch gives the direct evaluation path the same
    // fail-closed-with-retry contract.
    try {
    let binding = null
    try {
      binding = await store.read(key)
    } catch {
      cancelScheduled(key)
      return
    }
    if (disposed || epoch !== instanceEpoch) return
    if (!binding || binding.terminal) {
      cancelScheduled(key)
      return
    }
    if (binding.autoResume === false || !isIdle()) {
      cancelScheduled(key)
      return
    }

    // Capture the binding identity so every commit below can CAS against it:
    // a re-activation that happens while this evaluation is in-flight bumps
    // the persisted generation and rejects the stale commit.
    const capturedGen = binding.generation || 0
    const capturedGoalId = binding.goalId
    const expected = { generation: capturedGen, goalId: capturedGoalId }

    let decision
    try {
      decision = await quotaProbe(binding)
    } catch {
      if (disposed || epoch !== instanceEpoch) return
      // Fail closed: never continue without LoopX authority. Bounded retry.
      scheduleEvaluation(key, DEFAULT_RETRY_MINUTES)
      return
    }
    if (disposed || epoch !== instanceEpoch) return

    const current = await store.read(key)
    if (disposed || epoch !== instanceEpoch) return
    if (
      !current ||
      current.terminal ||
      current.autoResume === false ||
      current.generation !== capturedGen ||
      current.goalId !== capturedGoalId
    ) {
      cancelScheduled(key)
      return
    }

    if (isTerminalNoFollowup(decision)) {
      // Commit through the store's compare-and-swap: if the same session
      // activated a new goal while this write was in-flight, the commit is
      // rejected and the new binding stays alive.
      const committed = await store.write(key, { terminal: true, autoResume: false }, expected)
      if (!committed) {
        cancelScheduled(key)
        return
      }
      if (disposed || epoch !== instanceEpoch) return
      cancelScheduled(key)
      services.notify(
        `LoopX goal ${current.goalId} reached validated terminal no-follow-up; loop stopped.`,
        "info",
      )
      return
    }

    if (shouldRunNow(decision)) {
      cancelScheduled(key)
      const schedulerCommit = await store.write(
        key,
        { schedulerToken: "", unchangedPolls: 0 },
        expected,
      )
      if (!schedulerCommit) {
        cancelScheduled(key)
        return
      }
      if (disposed || epoch !== instanceEpoch) return
      const prompt = current.taskBody || current.goalId
      const promptCommit = await store.write(key, { lastInjectedPrompt: prompt }, expected)
      if (!promptCommit) {
        cancelScheduled(key)
        return
      }
      if (disposed || epoch !== instanceEpoch) return
      sendMessage(prompt)
      return
    }

    const wait = waitPlan(decision, current)
    if (wait.stop) {
      cancelScheduled(key)
      return
    }
    const waitCommit = await store.write(
      key,
      {
        schedulerToken: wait.schedulerToken,
        unchangedPolls: wait.unchangedPolls,
      },
      expected,
    )
    if (!waitCommit) {
      cancelScheduled(key)
      return
    }
    if (disposed || epoch !== instanceEpoch) return
    scheduleEvaluation(key, wait.minutes)
    } catch {
      // Fail closed with bounded retry: any unhandled error (store write
      // failure, etc.) must not break the evaluation chain permanently.
      cancelScheduled(key)
      scheduleEvaluation(key, DEFAULT_RETRY_MINUTES)
    }
  }

  const evaluateIdle = (key) => {
    if (disposed) return Promise.resolve()
    const existing = evaluations.get(key)
    if (existing) return existing
    const evaluation = evaluateIdleOnce(key).finally(() => {
      if (evaluations.get(key) === evaluation) evaluations.delete(key)
    })
    evaluations.set(key, evaluation)
    return evaluation
  }

  return {
    // Bind the ctx-derived services (store, isIdle, notify) for a session key.
    // Re-binding on every event keeps the loop free of host types while still
    // using the freshest context available. The adapter must pass one stable
    // store instance per key so the store's per-key commit queue is shared.
    bind(key, services) {
      contexts.set(key, services)
    },
    cancel(key) {
      cancelScheduled(key)
    },
    async activate(key, fields) {
      if (disposed) return null
      const services = contexts.get(key)
      if (!services) throw new Error("loopx_goal_activate requires a bound session context")
      // Increment the persisted generation so every in-flight evaluation for
      // this key is rejected at its next compare-and-swap commit.
      const current = await services.store.read(key)
      const generation = (current?.generation || 0) + 1
      const binding = await services.store.write(key, { ...fields, generation })
      if (disposed) return null
      cancelScheduled(key)
      services.notify(
        `LoopX goal ${binding.goalId} activated; continuation gated by LoopX quota.`,
        "info",
      )
      return binding
    },
    async settle(key) {
      if (disposed) return
      const instanceEpoch = epoch
      const services = contexts.get(key)
      if (!services) return
      let binding = null
      try {
        binding = await services.store.read(key)
      } catch {
        return
      }
      if (disposed || epoch !== instanceEpoch) return
      if (!binding || binding.terminal || binding.autoResume === false) return
      await evaluateIdle(key)
    },
    async userPrompt(key, prompt) {
      if (disposed) return
      const instanceEpoch = epoch
      const services = contexts.get(key)
      if (!services) return
      let binding = null
      try {
        binding = await services.store.read(key)
      } catch {
        return
      }
      if (disposed || epoch !== instanceEpoch) return
      if (!binding || binding.terminal) return
      if (String(prompt || "") !== binding.lastInjectedPrompt) {
        const expected = { generation: binding.generation || 0, goalId: binding.goalId }
        const committed = await services.store.write(key, { autoResume: false }, expected)
        if (!committed) return
        if (disposed || epoch !== instanceEpoch) return
        cancelScheduled(key)
      }
    },
    async resume(key) {
      if (disposed) return null
      const services = contexts.get(key)
      if (!services) return null
      const binding = await services.store.write(key, { autoResume: true, terminal: false })
      if (disposed) return null
      cancelScheduled(key)
      services.notify(`LoopX goal ${binding.goalId} auto-continuation resumed.`, "info")
      return binding
    },
    // Session shutdown / session replacement: atomically invalidate this
    // extension instance and cancel every timer. A quota probe that is
    // already in flight — or an evaluation suspended on any later store
    // await — returns to the epoch guard, so it cannot write, notify, send
    // the old task body, or reschedule a timer past the boundary.
    dispose() {
      disposed = true
      epoch += 1
      cancelAll()
    },
  }
}

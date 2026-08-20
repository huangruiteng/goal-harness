import { randomUUID } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import type { FileRunner } from '../src/cli.ts'
import {
  LoopXContinuationDriver,
} from '../src/driver.ts'
import type { DriverClock } from '../src/driver.ts'

const goalId = 'goal-fixture'
const agentId = 'agent-fixture'
const sessionId = 'session-fixture'

interface FakeAgent {
  readonly agent: Agent
  readonly cancelCalls: number
  readonly nextTurn: UserMessage[]
  readonly nextStep: UserMessage[]
  replaceSession(headerId?: string): void
  setStatus(status: 'idle' | 'running'): void
}

function userMessage(text: string): UserMessage {
  return {
    id: randomUUID() as UserMessage['id'],
    role: 'user',
    content: [{ type: 'text', text }],
    source: { kind: 'user' },
  }
}

function fakeAgent(): FakeAgent {
  const nextTurn: UserMessage[] = []
  const nextStep: UserMessage[] = []
  let status: 'idle' | 'running' = 'idle'
  let cancelCalls = 0
  const inbox = {
    nextTurn,
    nextStep,
    get hasPending() {
      return nextTurn.length > 0 || nextStep.length > 0
    },
    remove(id: UserMessage['id']) {
      for (const queue of [nextStep, nextTurn]) {
        const index = queue.findIndex(message => message.id === id)
        if (index >= 0) {
          queue.splice(index, 1)
          return true
        }
      }
      return false
    },
  }
  let session = {
    id: sessionId,
    header: {
      version: 0,
      id: sessionId,
      createdAt: 1,
      cwd: '/fixture/project',
      seedLength: 0,
    },
    events: [],
    surface: { nodes: [] },
  }
  const agent = {
    id: sessionId,
    options: {},
    get session() { return session },
    inbox,
    ctx: {},
    get status() { return status },
    cancel() { cancelCalls += 1 },
    whenIdle: async () => {},
    runMaintenance: async <T>(task: (signal: AbortSignal) => Promise<T>) => (
      task(new AbortController().signal)
    ),
    send(message: UserMessage, target: 'next-turn' | 'next-step') {
      (target === 'next-step' ? nextStep : nextTurn).push(message)
    },
    followup(message: UserMessage) { nextTurn.push(message) },
    steer(message: UserMessage) { nextStep.push(message) },
    inject(message: UserMessage) { nextStep.push(message) },
  } as unknown as Agent
  return {
    agent,
    get cancelCalls() { return cancelCalls },
    nextTurn,
    nextStep,
    replaceSession(headerId) {
      session = {
        ...session,
        header: { ...session.header, ...(headerId === undefined ? {} : { id: headerId }) },
      }
    },
    setStatus(value) { status = value },
  }
}

interface RunnerFixture {
  readonly runner: FileRunner
  readonly calls: string[][]
  readonly quotaCalls: string[][]
  heartbeatCalls: number
}

function runnerFixture(options: {
  readonly quotaExitFailures?: number
  readonly shouldRun?: boolean
  readonly waitMinutes?: number
  readonly schedulerMode?: 'poll' | 'stop' | 'missing'
  readonly unchangedPollLimit?: number
  readonly quotaAgentId?: string
  readonly typedQuotaFailure?: boolean
} = {}): RunnerFixture {
  const calls: string[][] = []
  const quotaCalls: string[][] = []
  let quotaExitFailures = options.quotaExitFailures ?? 0
  const fixture: RunnerFixture = {
    calls,
    quotaCalls,
    heartbeatCalls: 0,
    runner: async (_file, args) => {
      calls.push([...args])
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      if (args.includes('resolve-agent-thread')) {
        return {
          exitCode: 0,
          stdout: JSON.stringify({
            ok: true,
            schema_version: 'loopx_thread_agent_binding_resolution_v0',
            host_surface: 'deepseek-harness-native',
            thread_id: sessionId,
            status: 'bound',
            goal_id: goalId,
            agent_id: agentId,
            matches: [{ goal_id: goalId, agent_id: agentId }],
          }),
          stderr: '',
        }
      }
      if (args.includes('should-run')) {
        quotaCalls.push([...args])
        if (quotaExitFailures > 0) {
          quotaExitFailures -= 1
          return { exitCode: 1, stdout: '', stderr: 'transient diagnostic' }
        }
        const shouldRun = options.shouldRun ?? true
        const schedulerHint = shouldRun
          ? { action: 'run_now' }
          : options.schedulerMode === 'stop'
            ? {
                action: 'stop_until_explicit_resume',
                unchanged_poll: { local_scheduler: 'stop' },
              }
            : options.schedulerMode === 'missing'
              ? { action: 'wait' }
              : {
                  action: 'wait',
                  reset_policy: { reset_token: 'scheduler-token' },
                  unchanged_poll: {
                    local_scheduler: {
                      recommended_interval_minutes: options.waitMinutes ?? 5,
                      ...(options.unchangedPollLimit === undefined
                        ? {}
                        : { unchanged_poll_limit: options.unchangedPollLimit }),
                    },
                  },
                }
        return {
          exitCode: shouldRun && !options.typedQuotaFailure ? 0 : 1,
          stdout: JSON.stringify({
            ok: options.typedQuotaFailure ? false : true,
            mode: 'should-run',
            goal_id: goalId,
            should_run: shouldRun,
            agent_identity: {
              agent_id: options.quotaAgentId ?? agentId,
              registered: true,
            },
            scheduler_hint: schedulerHint,
          }),
          stderr: '',
        }
      }
      if (args.includes('heartbeat-prompt')) {
        fixture.heartbeatCalls += 1
        return {
          exitCode: 0,
          stdout: JSON.stringify({
            ok: true,
            schema_version: 'loopx_heartbeat_prompt_v0',
            goal_id: goalId,
            agent_id: agentId,
            task_body: 'Continue through the authoritative LoopX workflow.',
          }),
          stderr: '',
        }
      }
      throw new Error(`unexpected argv: ${args.join(' ')}`)
    },
  }
  return fixture
}

async function waitFor(predicate: () => boolean): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return
    await new Promise<void>(resolve => setTimeout(resolve, 0))
  }
  throw new Error('condition was not reached')
}

function makeDriver(fixture: RunnerFixture): LoopXContinuationDriver {
  return new LoopXContinuationDriver({
    runner: fixture.runner,
    isLiveAgent: () => true,
    makeTurnInstanceId: () => 'turn-stable',
    retryDelaysMs: [0, 0],
  })
}

describe('same-session LoopX driver', () => {
  it('contains a synchronous detached-runner failure without retrying', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const warnings: string[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      runDetached: () => { throw new Error('detached runner unavailable') },
      warn: message => warnings.push(message),
    })

    expect(() => driver.observeAgent(host.agent)).not.toThrow()
    expect(warnings).toHaveLength(1)
    expect(fixture.calls).toHaveLength(0)
    await driver.dispose()
  })

  it('stays paused after any terminal Agent error until new human input', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)

    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)
    driver.onAgentError(host.agent)
    driver.onAgentStatus(host.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('stays paused after max-token termination outside an automatic reservation', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    host.setStatus('running')
    const driver = makeDriver(fixture)

    driver.observeAgent(host.agent)
    driver.onSessionEvent(host.agent, {
      type: 'turn/end',
      data: { reason: { kind: 'max-tokens' } },
    } as unknown as Parameters<LoopXContinuationDriver['onSessionEvent']>[1])
    host.setStatus('idle')
    driver.onAgentStatus(host.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('refuses a Session whose header id does not match the live Agent', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    host.replaceSession('different-session-header')
    const driver = makeDriver(fixture)

    driver.observeAgent(host.agent)
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('queues one authoritative task and revalidates the same receipt before entry', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)

    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)
    const queued = host.nextTurn[0] as UserMessage
    expect(queued.content).toEqual([
      { type: 'text', text: 'Continue through the authoritative LoopX workflow.' },
    ])
    expect(fixture.quotaCalls).toHaveLength(1)

    host.nextTurn.splice(0, 1)
    host.setStatus('running')
    driver.onInboxClaimed(host.agent, queued)
    const decision = await driver.onPreStep(
      host.agent,
      [queued],
      new AbortController().signal,
      async () => ({ kind: 'enter', messages: [queued] }),
    )

    expect(decision.kind).toBe('enter')
    expect(fixture.quotaCalls).toHaveLength(3)
    for (const call of fixture.quotaCalls) {
      const index = call.indexOf('--turn-instance-id')
      expect(call[index + 1]).toBe('turn-stable')
    }
    await driver.dispose()
  })

  it('removes its queued reservation when human input arrives', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)

    const human = userMessage('human priority')
    host.nextTurn.push(human)
    driver.onInboxInserted(host.agent, human)

    expect(host.nextTurn).toEqual([human])
    await driver.dispose()
  })

  it('cancels a claimed automatic step when the Driver is disposed', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)
    const queued = host.nextTurn.shift() as UserMessage
    host.setStatus('running')
    driver.onInboxClaimed(host.agent, queued)

    await driver.dispose()

    expect(host.cancelCalls).toBe(1)
  })

  it('retries an untyped CLI exit twice with one stable idempotency key', async () => {
    const fixture = runnerFixture({ quotaExitFailures: 2 })
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)

    expect(fixture.quotaCalls).toHaveLength(3)
    expect(new Set(fixture.quotaCalls.map(call => (
      call[call.indexOf('--turn-instance-id') + 1]
    )))).toEqual(new Set(['turn-stable']))
    await driver.dispose()
  })

  it('stops after the finite CLI attempt budget instead of scheduling an error loop', async () => {
    const fixture = runnerFixture({ quotaExitFailures: 3 })
    const host = fakeAgent()
    const timers: unknown[] = []
    const warnings: string[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      retryDelaysMs: [0, 0],
      warn: message => warnings.push(message),
      clock: {
        setTimeout(_callback, delay) {
          const value = { delay }
          timers.push(value)
          return value
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    await waitFor(() => fixture.quotaCalls.length === 3 && warnings.length === 1)

    expect(host.nextTurn).toHaveLength(0)
    expect(fixture.heartbeatCalls).toBe(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('recognizes a typed LoopX quota failure without retrying or scheduling', async () => {
    const fixture = runnerFixture({ typedQuotaFailure: true })
    const host = fakeAgent()
    const timers: unknown[] = []
    const warnings: string[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      retryDelaysMs: [0, 0],
      warn: message => warnings.push(message),
      clock: {
        setTimeout(_callback, delay) {
          const value = { delay }
          timers.push(value)
          return value
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    await waitFor(() => warnings.length === 1)

    expect(fixture.quotaCalls).toHaveLength(1)
    expect(warnings[0]).toContain('typed_failure')
    expect(host.nextTurn).toHaveLength(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('uses LoopX scheduler wait without invoking the heartbeat command', async () => {
    const fixture = runnerFixture({ shouldRun: false, waitMinutes: 7 })
    const host = fakeAgent()
    const timers: Array<{ delay: number; cleared: boolean }> = []
    const clock: DriverClock = {
      setTimeout(_callback, delay) {
        const timer = { delay, cleared: false }
        timers.push(timer)
        return timer
      },
      clearTimeout(handle) {
        (handle as { cleared: boolean }).cleared = true
      },
    }
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      makeTurnInstanceId: () => 'turn-stable',
      retryDelaysMs: [0, 0],
      clock,
    })
    driver.observeAgent(host.agent)
    await waitFor(() => timers.length === 1)

    expect(timers[0]?.delay).toBe(7 * 60_000)
    expect(fixture.heartbeatCalls).toBe(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('honors the typed unchanged-poll limit without an indefinite timer loop', async () => {
    const fixture = runnerFixture({
      shouldRun: false,
      waitMinutes: 2,
      unchangedPollLimit: 1,
    })
    const host = fakeAgent()
    const timers: Array<{ callback: () => void; delay: number }> = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      retryDelaysMs: [0, 0],
      clock: {
        setTimeout(callback, delay) {
          const timer = { callback, delay }
          timers.push(timer)
          return timer
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    await waitFor(() => timers.length === 1)
    timers[0]?.callback()
    await waitFor(() => fixture.quotaCalls.length === 2)

    expect(timers).toHaveLength(1)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('does not poll when LoopX omits a typed local scheduler plan', async () => {
    const fixture = runnerFixture({ shouldRun: false, schedulerMode: 'missing' })
    const host = fakeAgent()
    const timers: unknown[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      clock: {
        setTimeout(_callback, delay) {
          const value = { delay }
          timers.push(value)
          return value
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    await waitFor(() => fixture.quotaCalls.length === 1)
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('rejects a quota response for another Agent without scheduling it', async () => {
    const fixture = runnerFixture({
      shouldRun: false,
      quotaAgentId: 'another-agent',
    })
    const host = fakeAgent()
    const timers: unknown[] = []
    const warnings: string[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      warn: message => warnings.push(message),
      clock: {
        setTimeout(_callback, delay) {
          const value = { delay }
          timers.push(value)
          return value
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    await waitFor(() => warnings.length === 1)

    expect(host.nextTurn).toHaveLength(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('rejects an automatic message from a mixed human batch', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)
    const queued = host.nextTurn.shift() as UserMessage
    host.setStatus('running')
    driver.onInboxClaimed(host.agent, queued)
    const human = userMessage('new human work')
    driver.onInboxInserted(host.agent, human)

    const decision = await driver.onPreStep(
      host.agent,
      [queued, human],
      new AbortController().signal,
      async () => ({ kind: 'enter', messages: [queued, human] }),
    )

    expect(decision).toEqual({ kind: 'reject' })
    expect(host.nextStep).toEqual([human])
    expect(fixture.quotaCalls).toHaveLength(1)
    await driver.dispose()
  })

  it('pauses automatic continuation when a downstream pre-step fails', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)
    const queued = host.nextTurn.shift() as UserMessage
    host.setStatus('running')
    driver.onInboxClaimed(host.agent, queued)

    await expect(driver.onPreStep(
      host.agent,
      [queued],
      new AbortController().signal,
      async () => { throw new Error('downstream failed') },
    )).rejects.toThrow('downstream failed')

    host.setStatus('idle')
    driver.onAgentStatus(host.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('fences automatic work across a UI command lifecycle', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)

    driver.onSessionEvent(host.agent, {
      type: 'command/run',
      data: { commandId: 'command-1', name: 'loopx-init', source: { kind: 'user' } },
    } as unknown as Parameters<LoopXContinuationDriver['onSessionEvent']>[1])
    expect(host.nextTurn).toHaveLength(0)

    driver.onSessionEvent(host.agent, {
      type: 'command/done',
      data: { commandId: 'command-1', kind: 'success' },
    } as unknown as Parameters<LoopXContinuationDriver['onSessionEvent']>[1])
    await waitFor(() => host.nextTurn.length === 1)
    await driver.dispose()
  })

  it('does not queue after the exact live Agent is replaced during a CLI await', async () => {
    const base = runnerFixture()
    let live = true
    let resolveStarted = false
    let releaseResolve: (() => void) | undefined
    const gate = new Promise<void>(resolve => { releaseResolve = resolve })
    const controlled: RunnerFixture = {
      ...base,
      runner: async (file, args, options) => {
        if (args.includes('resolve-agent-thread')) {
          resolveStarted = true
          await gate
        }
        return base.runner(file, args, options)
      },
    }
    const host = fakeAgent()
    const timers: unknown[] = []
    const driver = new LoopXContinuationDriver({
      runner: controlled.runner,
      isLiveAgent: () => live,
      retryDelaysMs: [0, 0],
      clock: {
        setTimeout(_callback, delay) {
          const value = { delay }
          timers.push(value)
          return value
        },
        clearTimeout() {},
      },
    })
    driver.observeAgent(host.agent)
    await waitFor(() => resolveStarted)
    live = false
    releaseResolve?.()
    await waitFor(() => base.calls.some(args => args.includes('resolve-agent-thread')))

    expect(host.nextTurn).toHaveLength(0)
    expect(controlled.quotaCalls).toHaveLength(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('does not queue across replacement of the exact Session object', async () => {
    const base = runnerFixture()
    let resolveStarted = false
    let releaseResolve: (() => void) | undefined
    const gate = new Promise<void>(resolve => { releaseResolve = resolve })
    const controlled: RunnerFixture = {
      ...base,
      runner: async (file, args, options) => {
        if (args.includes('resolve-agent-thread')) {
          resolveStarted = true
          await gate
        }
        return base.runner(file, args, options)
      },
    }
    const host = fakeAgent()
    const driver = new LoopXContinuationDriver({
      runner: controlled.runner,
      isLiveAgent: () => true,
      retryDelaysMs: [0, 0],
    })

    driver.observeAgent(host.agent)
    await waitFor(() => resolveStarted)
    host.replaceSession()
    releaseResolve?.()
    await waitFor(() => base.calls.some(args => args.includes('resolve-agent-thread')))

    expect(host.nextTurn).toHaveLength(0)
    expect(controlled.quotaCalls).toHaveLength(0)
    await driver.dispose()
  })
})

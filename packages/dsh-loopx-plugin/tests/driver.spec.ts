import { randomUUID } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
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
  readonly maintenanceCalls: number
  readonly nextTurn: UserMessage[]
  readonly nextStep: UserMessage[]
  appendEvent(event: SessionEvent): void
  replaceSession(headerId?: string, events?: SessionEvent[]): void
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

function fakeAgent(id = sessionId): FakeAgent {
  const nextTurn: UserMessage[] = []
  const nextStep: UserMessage[] = []
  let status: 'idle' | 'running' = 'idle'
  let cancelCalls = 0
  let maintenanceCalls = 0
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
  let session: {
    id: string
    header: {
      version: number
      id: string
      createdAt: number
      cwd: string
      seedLength: number
    }
    events: SessionEvent[]
    surface: { nodes: never[] }
  } = {
    id,
    header: {
      version: 0,
      id,
      createdAt: 1,
      cwd: '/fixture/project',
      seedLength: 0,
    },
    events: [],
    surface: { nodes: [] },
  }
  const agent = {
    id,
    options: {},
    get session() { return session },
    inbox,
    ctx: {},
    get status() { return status },
    cancel() { cancelCalls += 1 },
    whenIdle: async () => {},
    runMaintenance: async <T>(task: (signal: AbortSignal) => Promise<T>) => {
      maintenanceCalls += 1
      return task(new AbortController().signal)
    },
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
    get maintenanceCalls() { return maintenanceCalls },
    nextTurn,
    nextStep,
    appendEvent(event) { session.events.push(event) },
    replaceSession(headerId, events = [...session.events]) {
      session = {
        ...session,
        events,
        header: {
          ...session.header,
          ...(headerId === undefined ? {} : { id: headerId }),
        },
      }
    },
    setStatus(value) { status = value },
  }
}

function sessionEvent(
  type: string,
  data: unknown,
): SessionEvent {
  return { type, data } as unknown as SessionEvent
}

function userSkillInvocationEvent(
  name = 'loopx',
  form = 'instructions',
): SessionEvent {
  return sessionEvent('user/message', {
    id: randomUUID(),
    role: 'user',
    content: [{ type: 'text', text: `Loaded ${name}.` }],
    source: { kind: 'skill-invocation', name, form },
  })
}

function modelSkillCallEvent(
  callId: string,
  rawArguments: string,
  name = 'skill',
): SessionEvent {
  return sessionEvent('tool/call', {
    turn: 0,
    step: 0,
    callId,
    name,
    arguments: rawArguments,
  })
}

function modelSkillResultEvent(
  callId: string,
  options: {
    readonly blockCallId?: string
    readonly eventError?: { name: string; code: string }
    readonly extraBlock?: boolean
    readonly isError?: boolean
  } = {},
): SessionEvent {
  const resultBlock = {
    type: 'tool-result',
    toolCallId: options.blockCallId ?? callId,
    content: [],
    isError: options.isError ?? false,
  }
  return sessionEvent('tool/result', {
    turn: 0,
    step: 0,
    message: {
      id: randomUUID(),
      role: 'user',
      content: options.extraBlock
        ? [resultBlock, { type: 'text', text: 'unexpected extra block' }]
        : [resultBlock],
      source: { kind: 'tool', callId },
    },
    ...(options.eventError === undefined ? {} : { error: options.eventError }),
  })
}

function observeActivated(
  driver: LoopXContinuationDriver,
  host: FakeAgent,
): void {
  host.appendEvent(userSkillInvocationEvent())
  driver.observeAgent(host.agent)
}

function publishEvent(
  driver: LoopXContinuationDriver,
  host: FakeAgent,
  event: SessionEvent,
): void {
  host.appendEvent(event)
  driver.onSessionEvent(host.agent, event)
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
  readonly bindingStatus?: 'bound' | 'missing'
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
        const threadIdIndex = args.indexOf('--thread-id')
        const threadId = args[threadIdIndex + 1]
        if (options.bindingStatus === 'missing') {
          return {
            exitCode: 0,
            stdout: JSON.stringify({
              ok: true,
              schema_version: 'loopx_thread_agent_binding_resolution_v0',
              host_surface: 'deepseek-harness-native',
              thread_id: threadId,
              status: 'unbound',
              matches: [],
            }),
            stderr: '',
          }
        }
        return {
          exitCode: 0,
          stdout: JSON.stringify({
            ok: true,
            schema_version: 'loopx_thread_agent_binding_resolution_v0',
            host_surface: 'deepseek-harness-native',
            thread_id: threadId,
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
  it('keeps a newly observed inactive Agent at zero LoopX I/O and zero timers', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const timers: unknown[] = []
    let detachedCalls = 0
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      runDetached: operation => {
        detachedCalls += 1
        return operation()
      },
      clock: {
        setTimeout(_callback, delay) {
          const timer = { delay }
          timers.push(timer)
          return timer
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.maintenanceCalls).toBe(0)
    expect(detachedCalls).toBe(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('keeps every ordinary inactive lifecycle transition at zero LoopX I/O', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const timers: unknown[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      clock: {
        setTimeout(_callback, delay) {
          const timer = { delay }
          timers.push(timer)
          return timer
        },
        clearTimeout() {},
      },
    })

    driver.observeAgent(host.agent)
    driver.onSessionStart(host.agent)
    const human = userMessage('ordinary work mentioning loopx only as prose')
    driver.onInboxInserted(host.agent, human)
    driver.onInboxClaimed(host.agent, human)
    publishEvent(driver, host, sessionEvent('user/message', human))
    publishEvent(driver, host, sessionEvent('turn/end', {
      turn: 0,
      reason: { kind: 'completed' },
    }))
    driver.onAgentStatus(host.agent, 'idle')
    driver.onAgentStatus(host.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.maintenanceCalls).toBe(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('activates only the exact Session with a user-explicit loopx invocation', async () => {
    const fixture = runnerFixture()
    const first = fakeAgent()
    const second = fakeAgent('another-session')
    const driver = makeDriver(fixture)

    driver.observeAgent(first.agent)
    driver.observeAgent(second.agent)
    expect(fixture.calls).toHaveLength(0)

    publishEvent(driver, first, userSkillInvocationEvent())
    await waitFor(() => first.nextTurn.length === 1)
    const activatedCalls = fixture.calls.length

    driver.onSessionStart(second.agent)
    driver.onAgentStatus(second.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(second.nextTurn).toHaveLength(0)
    expect(fixture.calls).toHaveLength(activatedCalls)

    publishEvent(driver, second, userSkillInvocationEvent())
    await waitFor(() => second.nextTurn.length === 1)

    const resolvedThreadIds = fixture.calls
      .filter(call => call.includes('resolve-agent-thread'))
      .map(call => call[call.indexOf('--thread-id') + 1])
    expect(resolvedThreadIds).toEqual([sessionId, 'another-session'])
    expect(first.nextTurn).toHaveLength(1)
    expect(second.nextTurn).toHaveLength(1)
    expect(fixture.heartbeatCalls).toBe(2)
    await driver.dispose()
  })

  it('activates after a successful paired model skill call for loopx', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)

    driver.observeAgent(host.agent)
    publishEvent(driver, host, modelSkillCallEvent('call-loopx', '{"name":"loopx"}'))
    await new Promise<void>(resolve => setTimeout(resolve, 0))
    expect(fixture.calls).toHaveLength(0)

    publishEvent(driver, host, modelSkillResultEvent('call-loopx'))
    await waitFor(() => host.nextTurn.length === 1)

    expect(fixture.heartbeatCalls).toBe(1)
    await driver.dispose()
  })

  it('ignores malformed, failed, unrelated, prose-only, and plugin-authored signals', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    driver.observeAgent(host.agent)

    const nonSignals = [
      userSkillInvocationEvent('another-skill'),
      userSkillInvocationEvent('loopx', 'catalog'),
      sessionEvent('user/message', userMessage('please run loopx')),
      sessionEvent('user/message', {
        ...userMessage('LoopX initialization finished.'),
        source: { kind: 'plugin', plugin: 'dsh-loopx-plugin/init-command' },
      }),
      sessionEvent('user/message', {
        ...userMessage('Continue through LoopX.'),
        source: { kind: 'plugin', plugin: 'dsh-loopx-plugin/driver' },
      }),
      modelSkillCallEvent('malformed', '{not-json'),
      modelSkillResultEvent('malformed'),
      modelSkillCallEvent('json-null', 'null'),
      modelSkillResultEvent('json-null'),
      modelSkillCallEvent('json-array', '[{"name":"loopx"}]'),
      modelSkillResultEvent('json-array'),
      modelSkillCallEvent('json-string', '"loopx"'),
      modelSkillResultEvent('json-string'),
      modelSkillCallEvent('other-skill', '{"name":"another-skill"}'),
      modelSkillResultEvent('other-skill'),
      modelSkillCallEvent('missing-result', '{"name":"loopx"}'),
      modelSkillCallEvent('errored', '{"name":"loopx"}'),
      modelSkillResultEvent('errored', {
        eventError: { name: 'SkillError', code: 'UNAVAILABLE' },
      }),
      modelSkillCallEvent('block-error', '{"name":"loopx"}'),
      modelSkillResultEvent('block-error', { isError: true }),
      modelSkillCallEvent('mismatched-block', '{"name":"loopx"}'),
      modelSkillResultEvent('mismatched-block', { blockCallId: 'different-call' }),
      modelSkillCallEvent('extra-block', '{"name":"loopx"}'),
      modelSkillResultEvent('extra-block', { extraBlock: true }),
      modelSkillCallEvent('wrong-source', '{"name":"loopx"}'),
      sessionEvent('tool/result', {
        turn: 0,
        step: 0,
        message: {
          id: randomUUID(),
          role: 'user',
          content: [{
            type: 'tool-result',
            toolCallId: 'wrong-source',
            content: [],
            isError: false,
          }],
          source: {
            kind: 'plugin',
            plugin: 'not-a-tool',
            callId: 'wrong-source',
          },
        },
      }),
      modelSkillCallEvent('duplicate-result', '{"name":"loopx"}'),
      modelSkillResultEvent('duplicate-result', {
        eventError: { name: 'SkillError', code: 'FAILED' },
      }),
      modelSkillResultEvent('duplicate-result'),
      modelSkillResultEvent('unmatched'),
      modelSkillCallEvent('shell-loopx', '{"name":"loopx"}', 'shell'),
      modelSkillResultEvent('shell-loopx'),
      modelSkillCallEvent('superseded', '{"name":"loopx"}'),
      modelSkillCallEvent('superseded', '{"name":"another-skill"}'),
      modelSkillResultEvent('superseded'),
    ]
    for (const event of nonSignals) publishEvent(driver, host, event)
    driver.onSessionStart(host.agent)
    driver.onAgentStatus(host.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.maintenanceCalls).toBe(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('restores activation from exact paired Session history in a fresh Driver', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    host.appendEvent(modelSkillCallEvent('historical-call', '{"name":"loopx"}'))
    host.appendEvent(modelSkillResultEvent('historical-call'))

    const driver = makeDriver(fixture)
    expect(fixture.calls).toHaveLength(0)
    driver.observeAgent(host.agent)
    await waitFor(() => host.nextTurn.length === 1)

    expect(fixture.calls.some(call => call.includes('resolve-agent-thread'))).toBe(true)
    await driver.dispose()
  })

  it('leaves legacy or compacted history without invocation evidence inactive', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    host.appendEvent(sessionEvent('user/message', userMessage('legacy continuation')))
    host.appendEvent(sessionEvent('user/message', {
      ...userMessage('compacted summary mentioning loopx'),
      source: { kind: 'plugin', plugin: 'dsh-compaction-basic' },
    }))
    const driver = makeDriver(fixture)

    driver.observeAgent(host.agent)
    driver.onAgentStatus(host.agent, 'idle')
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('stops an activated Session with a missing binding before quota, heartbeat, or timers', async () => {
    const fixture = runnerFixture({ bindingStatus: 'missing' })
    const host = fakeAgent()
    const timers: unknown[] = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      retryDelaysMs: [0, 0],
      clock: {
        setTimeout(_callback, delay) {
          const timer = { delay }
          timers.push(timer)
          return timer
        },
        clearTimeout() {},
      },
    })

    observeActivated(driver, host)
    await waitFor(() => fixture.calls.some(call => call.includes('resolve-agent-thread')))
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.quotaCalls).toHaveLength(0)
    expect(fixture.heartbeatCalls).toBe(0)
    expect(timers).toHaveLength(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

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

    host.appendEvent(userSkillInvocationEvent())
    expect(() => driver.observeAgent(host.agent)).not.toThrow()
    expect(warnings).toHaveLength(1)
    expect(fixture.calls).toHaveLength(0)
    await driver.dispose()
  })

  it('stays paused after any terminal Agent error until new human input', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)

    observeActivated(driver, host)
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

    observeActivated(driver, host)
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

    observeActivated(driver, host)
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(fixture.calls).toHaveLength(0)
    expect(host.nextTurn).toHaveLength(0)
    await driver.dispose()
  })

  it('queues one authoritative task and revalidates the same receipt before entry', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)

    observeActivated(driver, host)
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
    observeActivated(driver, host)
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
    observeActivated(driver, host)
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
    observeActivated(driver, host)
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

    observeActivated(driver, host)
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

    observeActivated(driver, host)
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
    observeActivated(driver, host)
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

    observeActivated(driver, host)
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

    observeActivated(driver, host)
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

    observeActivated(driver, host)
    await waitFor(() => warnings.length === 1)

    expect(host.nextTurn).toHaveLength(0)
    expect(timers).toHaveLength(0)
    await driver.dispose()
  })

  it('rejects an automatic message from a mixed human batch', async () => {
    const fixture = runnerFixture()
    const host = fakeAgent()
    const driver = makeDriver(fixture)
    observeActivated(driver, host)
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
    observeActivated(driver, host)
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
    observeActivated(driver, host)
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
    observeActivated(driver, host)
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

    observeActivated(driver, host)
    await waitFor(() => resolveStarted)
    host.replaceSession()
    releaseResolve?.()
    await waitFor(() => base.calls.some(args => args.includes('resolve-agent-thread')))

    expect(host.nextTurn).toHaveLength(0)
    expect(controlled.quotaCalls).toHaveLength(0)
    await driver.dispose()
  })

  it('recomputes activation from replacement history instead of carrying it over', async () => {
    const fixture = runnerFixture({ shouldRun: false, waitMinutes: 3 })
    const host = fakeAgent()
    const timers: Array<{
      callback: () => void
      cleared: boolean
      delay: number
    }> = []
    const driver = new LoopXContinuationDriver({
      runner: fixture.runner,
      isLiveAgent: () => true,
      retryDelaysMs: [0, 0],
      clock: {
        setTimeout(callback, delay) {
          const timer = { callback, cleared: false, delay }
          timers.push(timer)
          return timer
        },
        clearTimeout(handle) {
          (handle as { cleared: boolean }).cleared = true
        },
      },
    })

    observeActivated(driver, host)
    await waitFor(() => timers.length === 1)
    const callsBeforeReplacement = fixture.calls.length
    const maintenanceBeforeReplacement = host.maintenanceCalls

    host.replaceSession(undefined, [])
    driver.onSessionStart(host.agent)
    driver.onAgentStatus(host.agent, 'idle')
    timers[0]?.callback()
    await new Promise<void>(resolve => setTimeout(resolve, 0))

    expect(timers[0]?.cleared).toBe(true)
    expect(timers).toHaveLength(1)
    expect(fixture.calls).toHaveLength(callsBeforeReplacement)
    expect(host.maintenanceCalls).toBe(maintenanceBeforeReplacement)
    await driver.dispose()
  })
})

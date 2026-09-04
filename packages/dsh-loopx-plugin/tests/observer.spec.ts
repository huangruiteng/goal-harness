import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'
import {
  applyObserver,
  ENV_GOAL_ID,
  OBSERVER_ENVELOPE_SCHEMA_VERSION,
  OBSERVER_STATS_SCHEMA_VERSION,
  resolveShadowObserverConfig,
  ShadowObserver,
} from '../src/observer.ts'
import type {
  ObserverEnvelope,
  ObserverStats,
  ShadowObserverConfig,
} from '../src/observer.ts'

const goalId = 'goal-observer-fixture'
const config: ShadowObserverConfig = { goalId, ledgerDir: '/ledger', bufferBound: 4 }
const ENVELOPE_FIELDS = [
  'schema_version', 'capability_id', 'provider_id', 'goal_id', 'session_id',
  'sequence', 'observed_at', 'clock', 'event_kind', 'summary', 'source_refs',
]
const STATS_FIELDS = [
  'schema_version', 'capability_id', 'provider_id', 'observer_id', 'goal_id', 'emitted_at',
  'observed_event_count', 'accepted_event_count', 'rejected_event_count', 'rejected_by_reason',
  'buffer_bound', 'backpressure_drop_count', 'observer_failure_count', 'outbound_endpoints',
  'observation_entered_worker_context', 'clock_source',
]

function fakeSession(id = 'session-fixture'): Session {
  return { id } as unknown as Session
}

function fakeAgent(session: Session, id = 'agent-fixture'): Agent {
  return { id, session, status: 'idle' } as unknown as Agent
}

function sessionEvent(type: string, seq: number, time: number, data: unknown): SessionEvent {
  return { type, seq, time, data } as unknown as SessionEvent
}

interface Captured {
  readonly appended: string[][]
  readonly paths: string[]
  readonly observer: ShadowObserver
}

function observerWithCapture(options: {
  readonly bufferBound?: number
  readonly failAppend?: boolean
} = {}): Captured {
  const appended: string[][] = []
  const paths: string[] = []
  const observer = new ShadowObserver({
    config: { ...config, bufferBound: options.bufferBound ?? config.bufferBound },
    now: () => 1_756_728_000_000,
    observerId: 'observer-fixture',
    appendLines: async (path, lines) => {
      if (options.failAppend) throw new Error('disk full')
      paths.push(path)
      appended.push([...lines])
    },
  })
  return { appended, paths, observer }
}

function parsed(lines: string[][]): Array<ObserverEnvelope | ObserverStats> {
  return lines.flat().map(line => JSON.parse(line) as ObserverEnvelope | ObserverStats)
}

describe('shadow observer configuration', () => {
  it('is off unless one exact goal id is declared', () => {
    expect(resolveShadowObserverConfig({})).toBeUndefined()
    expect(resolveShadowObserverConfig({ [ENV_GOAL_ID]: '   ' })).toBeUndefined()
    expect(resolveShadowObserverConfig({ [ENV_GOAL_ID]: 'not an id' })).toBeUndefined()
    const resolved = resolveShadowObserverConfig({
      [ENV_GOAL_ID]: goalId,
      LOOPX_DSH_SHADOW_OBSERVER_LEDGER_DIR: '/tmp/ledger',
      LOOPX_DSH_SHADOW_OBSERVER_BUFFER_BOUND: '9',
    })
    expect(resolved).toEqual({ goalId, ledgerDir: '/tmp/ledger', bufferBound: 9 })
  })

  it('imports nothing from the driver and owns no send path', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const source = readFileSync(join(here, '../src/observer.ts'), 'utf8')
    expect(source).not.toMatch(/from '\.\/driver/u)
    expect(source).not.toMatch(/from '\.\/cli/u)
    expect(source).not.toMatch(/from '\.\/managed-runtime/u)
    expect(source).not.toMatch(/\.send\(/u)
    expect(source).not.toMatch(/\.inbox\b/u)
    expect(source).not.toMatch(/setTimeout|setInterval/u)
  })
})

describe('shadow observer envelopes', () => {
  it('maps DSH session events into the shared envelope shape', async () => {
    const { appended, paths, observer } = observerWithCapture({ bufferBound: 16 })
    const session = fakeSession()
    const agent = fakeAgent(session)
    observer.observeSessionStart(agent)
    observer.observeSessionEvent(session, sessionEvent('turn/start', 1, 1_756_728_001_000, { turn: 1 }))
    observer.observeSessionEvent(session, sessionEvent('tool/call', 2, 1_756_728_002_000, {
      turn: 1, step: 1, callId: 'call-1', name: 'bash', arguments: '{"cmd":"rm -rf /"}',
    }))
    observer.observeSessionEvent(session, sessionEvent('tool/result', 3, 1_756_728_003_000, {
      turn: 1, step: 1, message: { id: 'm', role: 'user', content: [], source: { kind: 'tool', callId: 'call-1' } },
      error: { name: 'ToolError', code: 'timeout' },
    }))
    observer.observeSessionEvent(session, sessionEvent('assistant/chunk', 4, 1_756_728_003_500, { turn: 1, step: 1 }))
    observer.observeSessionEvent(session, sessionEvent('todo/write', 5, 1_756_728_004_000, { todos: [] }))
    observer.observeSessionEvent(session, sessionEvent('turn/end', 6, 1_756_728_005_000, { turn: 1, reason: 'completed' }))
    await observer.flush()

    const records = parsed(appended)
    const envelopes = records.filter(
      (record): record is ObserverEnvelope => record.schema_version === OBSERVER_ENVELOPE_SCHEMA_VERSION,
    )
    expect(new Set(paths)).toEqual(new Set(['/ledger/goal-observer-fixture.ndjson']))
    expect(envelopes.map(item => item.event_kind)).toEqual([
      'session_started', 'turn_started', 'tool_called', 'tool_completed', 'unsupported', 'turn_ended',
    ])
    expect(envelopes.map(item => item.sequence)).toEqual([0, 1, 2, 3, 4, 5])
    for (const envelope of envelopes) {
      expect(Object.keys(envelope).filter(key => key !== 'agent_id').sort()).toEqual([...ENVELOPE_FIELDS].sort())
      expect(envelope.goal_id).toBe(goalId)
      expect(envelope.session_id).toBe('session-fixture')
    }
    expect(envelopes[0]?.clock).toEqual({ source: 'observer_wall_clock', uncertainty_ms: 50 })
    expect(envelopes[0]?.agent_id).toBe('agent-fixture')
    expect(envelopes[1]?.clock).toEqual({ source: 'harness_event_time', uncertainty_ms: 0 })
    expect(envelopes[1]?.observed_at).toBe('2025-09-01T12:00:01.000Z')
    expect(envelopes[2]?.summary).toEqual({ turn: 1, step: 1, tool_name: 'bash' })
    expect(envelopes[2]?.source_refs).toEqual({ event_seq: '2', tool_call_id: 'call-1' })
    expect(envelopes[3]?.summary).toEqual({ turn: 1, step: 1, status: 'error', error_class: 'timeout' })
    expect(envelopes[4]?.summary).toEqual({ source_event_type: 'todo/write' })
    expect(JSON.stringify(records)).not.toContain('rm -rf')

    const stats = records.at(-1) as ObserverStats
    expect(stats.schema_version).toBe(OBSERVER_STATS_SCHEMA_VERSION)
    expect(Object.keys(stats).sort()).toEqual([...STATS_FIELDS].sort())
    expect(stats.outbound_endpoints).toEqual([])
    expect(stats.observation_entered_worker_context).toBe(false)
    expect(stats.observed_event_count).toBe(6)
    expect(stats.accepted_event_count).toBe(6)
  })

  it('drops with a count while a flush is in flight and the buffer is full', async () => {
    const appended: string[][] = []
    let release: (() => void) | undefined
    const observer = new ShadowObserver({
      config: { ...config, bufferBound: 2 },
      now: () => 1_756_728_000_000,
      observerId: 'observer-fixture',
      appendLines: async (_path, lines) => {
        appended.push([...lines])
        if (release === undefined) await new Promise<void>(resolve => { release = resolve })
      },
    })
    const agent = fakeAgent(fakeSession())
    // Two observations fill the buffer and start a flush that stays pending.
    observer.observePreStep(agent, { turn: 1, step: 1 })
    observer.observePreStep(agent, { turn: 1, step: 2 })
    // Two more refill the bound; the fifth has nowhere to go and is dropped.
    observer.observePreStep(agent, { turn: 1, step: 3 })
    observer.observePreStep(agent, { turn: 1, step: 4 })
    observer.observePreStep(agent, { turn: 1, step: 5 })
    release?.()
    await observer.flush()
    const records = parsed(appended)
    const stats = records.at(-1) as ObserverStats
    expect(stats.buffer_bound).toBe(2)
    expect(stats.accepted_event_count).toBe(4)
    expect(stats.backpressure_drop_count).toBe(1)
    expect(stats.observed_event_count).toBe(5)
    // The sequence still advances for the dropped event so the loss is visible.
    const envelopes = records.filter(
      (record): record is ObserverEnvelope => record.schema_version === OBSERVER_ENVELOPE_SCHEMA_VERSION,
    )
    expect(envelopes.map(item => item.sequence)).toEqual([0, 1, 2, 3])
  })

  it('counts hook and flush failures instead of throwing', async () => {
    const { observer } = observerWithCapture({ failAppend: true })
    const session = fakeSession()
    expect(() => observer.observeSessionEvent(session, undefined as unknown as SessionEvent)).not.toThrow()
    observer.observeSessionStart(fakeAgent(session))
    await expect(observer.flush()).resolves.toBeUndefined()
    const stats = observer.stats()
    expect(stats.observer_failure_count).toBe(2)
    expect(stats.backpressure_drop_count).toBe(1)
  })
})

describe('applyObserver', () => {
  it('registers read-only hooks and passes pre-step decisions through unchanged', async () => {
    type Handler = (...args: unknown[]) => unknown
    const handlers = new Map<string, Handler[]>()
    let disposeEffect: (() => unknown) | undefined
    const warnings: string[] = []
    const ctx = {
      logger: { warn(message: string) { warnings.push(message) } },
      on(event: string, handler: Handler) {
        handlers.set(event, [...(handlers.get(event) ?? []), handler])
      },
      effect(effect: () => Generator<unknown, void, unknown>) {
        const yielded = effect().next().value
        if (typeof yielded === 'function') disposeEffect = yielded as () => unknown
      },
    } as unknown as Context
    const observer = applyObserver(ctx, config)
    expect([...handlers.keys()].sort()).toEqual([
      'agent/error', 'agent/pre-step', 'agent/session-start', 'agent/status', 'session/disposed', 'session/event',
    ])
    const session = fakeSession()
    const agent = fakeAgent(session)
    const decision = { kind: 'enter', messages: [] }
    let nextCalls = 0
    const preStep = handlers.get('agent/pre-step')?.[0]
    const result = await preStep?.({ agent, messages: [], turn: 1, step: 1, signal: new AbortController().signal }, async () => {
      nextCalls += 1
      return decision
    })
    expect(nextCalls).toBe(1)
    expect(result).toBe(decision)
    expect(observer.stats().observed_event_count).toBe(1)
    expect(warnings).toEqual([])
    expect(typeof disposeEffect).toBe('function')
  })
})

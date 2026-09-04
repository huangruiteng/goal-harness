/**
 * L1 shadow observer for DeepSeek Harness (`dsh-session-events` provider).
 *
 * One-way only: this module consumes read-only harness events and appends
 * `reliability_observer_envelope_v0` records plus a
 * `reliability_observer_stats_v0` record to the LoopX reliability-diagnostics
 * ledger. It imports nothing from `driver.ts`, owns no `agent.send`, inbox,
 * timer, LoopX CLI, or continuation path, and every hook body is isolated so a
 * failure is counted instead of propagating into the harness. Field names
 * mirror `loopx/capabilities/reliability_diagnostics/envelope.py` exactly.
 */

import { randomUUID } from 'node:crypto'
import { appendFile, mkdir } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent, AgentStatus } from '@deepseek-ai/dsh-agent'
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'

export const CAPABILITY_ID = 'reliability-diagnostics'
export const PROVIDER_ID = 'dsh-session-events'
export const OBSERVER_ENVELOPE_SCHEMA_VERSION = 'reliability_observer_envelope_v0'
export const OBSERVER_STATS_SCHEMA_VERSION = 'reliability_observer_stats_v0'
export const LEDGER_DIRNAME = 'reliability_diagnostics'
export const DEFAULT_BUFFER_BOUND = 256
export const MAX_BUFFER_BOUND = 65_536
/** Declared skew for events stamped by the observer instead of the harness log. */
export const WALL_CLOCK_UNCERTAINTY_MS = 50

export const ENV_GOAL_ID = 'LOOPX_DSH_SHADOW_OBSERVER_GOAL_ID'
export const ENV_LEDGER_DIR = 'LOOPX_DSH_SHADOW_OBSERVER_LEDGER_DIR'
export const ENV_BUFFER_BOUND = 'LOOPX_DSH_SHADOW_OBSERVER_BUFFER_BOUND'

const IDENTITY_TOKEN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,120}$/u
const SUMMARY_TOKEN = /^[A-Za-z0-9][A-Za-z0-9_./:-]{0,79}$/u

export type ObserverEventKind =
  | 'session_started'
  | 'turn_started'
  | 'turn_ended'
  | 'step_started'
  | 'step_ended'
  | 'user_message'
  | 'tool_called'
  | 'tool_completed'
  | 'agent_status'
  | 'agent_pre_step'
  | 'agent_error'
  | 'session_disposed'
  | 'unsupported'

export type ClockSource = 'harness_event_time' | 'observer_wall_clock' | 'fixture'

export interface ObserverEnvelope {
  readonly schema_version: typeof OBSERVER_ENVELOPE_SCHEMA_VERSION
  readonly capability_id: typeof CAPABILITY_ID
  readonly provider_id: typeof PROVIDER_ID
  readonly goal_id: string
  readonly session_id: string
  readonly agent_id?: string
  readonly sequence: number
  readonly observed_at: string
  readonly clock: { readonly source: ClockSource, readonly uncertainty_ms: number }
  readonly event_kind: ObserverEventKind
  readonly summary: Readonly<Record<string, number | string>>
  readonly source_refs: Readonly<Record<string, string>>
}

export interface ObserverStats {
  readonly schema_version: typeof OBSERVER_STATS_SCHEMA_VERSION
  readonly capability_id: typeof CAPABILITY_ID
  readonly provider_id: typeof PROVIDER_ID
  readonly observer_id: string
  readonly goal_id: string
  readonly emitted_at: string
  readonly observed_event_count: number
  readonly accepted_event_count: number
  readonly rejected_event_count: number
  readonly rejected_by_reason: Readonly<Record<string, number>>
  readonly buffer_bound: number
  readonly backpressure_drop_count: number
  readonly observer_failure_count: number
  /** Always empty: the observer has no outbound control path to declare. */
  readonly outbound_endpoints: readonly []
  readonly observation_entered_worker_context: false
  readonly clock_source: ClockSource
}

export interface ShadowObserverConfig {
  readonly goalId: string
  readonly ledgerDir: string
  readonly bufferBound: number
}

export type LedgerAppender = (path: string, lines: readonly string[]) => Promise<void>

export interface ShadowObserverOptions {
  readonly config: ShadowObserverConfig
  readonly now?: (() => number) | undefined
  readonly appendLines?: LedgerAppender | undefined
  readonly warn?: ((message: string) => void) | undefined
  readonly observerId?: string | undefined
}

export function defaultLedgerDir(env: NodeJS.ProcessEnv = process.env): string {
  const configured = env[ENV_LEDGER_DIR]
  return resolve(configured?.trim()
    ? configured
    : join(homedir(), '.codex', 'loopx', LEDGER_DIRNAME))
}

/**
 * The observer is OFF unless one exact goal id is declared. Returning
 * `undefined` is the feature-off path: no hooks, no files.
 */
export function resolveShadowObserverConfig(
  env: NodeJS.ProcessEnv = process.env,
): ShadowObserverConfig | undefined {
  const goalId = env[ENV_GOAL_ID]?.trim()
  if (!goalId || !IDENTITY_TOKEN.test(goalId)) return undefined
  const rawBound = Number.parseInt(env[ENV_BUFFER_BOUND] ?? '', 10)
  const bufferBound = Number.isInteger(rawBound) && rawBound >= 1 && rawBound <= MAX_BUFFER_BOUND
    ? rawBound
    : DEFAULT_BUFFER_BOUND
  return { goalId, ledgerDir: defaultLedgerDir(env), bufferBound }
}

export function ledgerPath(config: ShadowObserverConfig): string {
  return join(config.ledgerDir, `${config.goalId.replaceAll(':', '_')}.ndjson`)
}

async function appendLedgerLines(path: string, lines: readonly string[]): Promise<void> {
  if (lines.length === 0) return
  await mkdir(dirname(path), { recursive: true })
  await appendFile(path, `${lines.join('\n')}\n`, 'utf8')
}

function token(value: unknown): string | undefined {
  const text = String(value ?? '')
  return SUMMARY_TOKEN.test(text) ? text : undefined
}

function identity(value: unknown): string | undefined {
  const text = String(value ?? '')
  return IDENTITY_TOKEN.test(text) ? text : undefined
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined
}

interface CompactEvent {
  readonly kind: ObserverEventKind
  readonly summary: Record<string, number | string>
  readonly sourceRefs: Record<string, string>
}

function compactSessionEvent(event: SessionEvent): CompactEvent | undefined {
  const data = event.data as Record<string, unknown>
  const summary: Record<string, number | string> = {}
  const sourceRefs: Record<string, string> = { event_seq: String(event.seq) }
  const put = (key: string, value: number | string | undefined): void => {
    if (value !== undefined) summary[key] = value
  }
  const ref = (key: string, value: string | undefined): void => {
    if (value !== undefined) sourceRefs[key] = value
  }
  put('turn', count(data.turn))
  put('step', count(data.step))
  switch (event.type) {
    case 'turn/start':
      return { kind: 'turn_started', summary, sourceRefs }
    case 'turn/end':
      put('reason', token(data.reason))
      return { kind: 'turn_ended', summary, sourceRefs }
    case 'step/start':
      return { kind: 'step_started', summary, sourceRefs }
    case 'step/end':
      return { kind: 'step_ended', summary, sourceRefs }
    case 'user/message': {
      const source = data.source as Record<string, unknown> | undefined
      put('message_source_kind', token(source?.kind))
      ref('message_id', identity(data.id))
      return { kind: 'user_message', summary, sourceRefs }
    }
    case 'tool/call':
      put('tool_name', token(data.name))
      ref('tool_call_id', identity(data.callId))
      return { kind: 'tool_called', summary, sourceRefs }
    case 'tool/result': {
      const error = data.error as Record<string, unknown> | undefined
      const message = data.message as Record<string, unknown> | undefined
      const source = message?.source as Record<string, unknown> | undefined
      put('status', error === undefined ? 'ok' : 'error')
      put('error_class', error === undefined ? undefined : token(error.code))
      ref('tool_call_id', identity(source?.callId))
      return { kind: 'tool_completed', summary, sourceRefs }
    }
    case 'assistant/chunk':
      // Token-level chunks are not consumed: they carry model text and add no
      // stage signal. Their absence is visible through `event_kinds_consumed`.
      return undefined
    default:
      put('source_event_type', token(event.type))
      return { kind: 'unsupported', summary, sourceRefs }
  }
}

/**
 * Bounded, crash-isolated observer. Mirrors
 * `ShadowObserverIntake` on the Python side: overflow is counted, never
 * blocking; failures are counted, never thrown; the stats record travels with
 * every flush.
 */
export class ShadowObserver {
  private readonly config: ShadowObserverConfig
  private readonly now: () => number
  private readonly appendLines: LedgerAppender
  private readonly warn: (message: string) => void
  private readonly observerId: string
  private readonly sequences = new Map<string, number>()
  private buffer: ObserverEnvelope[] = []
  private flushing: Promise<void> | undefined
  private flushRequested = false
  private disposed = false
  private observedEventCount = 0
  private acceptedEventCount = 0
  private backpressureDropCount = 0
  private observerFailureCount = 0

  constructor(options: ShadowObserverOptions) {
    if (!IDENTITY_TOKEN.test(options.config.goalId)) throw new Error('goal id must be an identity token')
    if (!Number.isInteger(options.config.bufferBound)
      || options.config.bufferBound < 1
      || options.config.bufferBound > MAX_BUFFER_BOUND) {
      throw new Error(`buffer bound must be within 1..${MAX_BUFFER_BOUND}`)
    }
    this.config = options.config
    this.now = options.now ?? Date.now
    this.appendLines = options.appendLines ?? appendLedgerLines
    this.warn = options.warn ?? (() => {})
    this.observerId = options.observerId ?? `${PROVIDER_ID}-${randomUUID()}`
  }

  get path(): string {
    return ledgerPath(this.config)
  }

  observeSessionStart(agent: Agent): void {
    this.isolated(() => this.record('session_started', agent.session, agent, undefined, {}, {}))
  }

  observeAgentStatus(agent: Agent, status: AgentStatus): void {
    this.isolated(() => {
      const summary: Record<string, number | string> = {}
      const compact = token(status)
      if (compact !== undefined) summary.status = compact
      this.record('agent_status', agent.session, agent, undefined, summary, {})
      if (status === 'idle') this.requestFlush()
    })
  }

  observeAgentError(agent: Agent, detail: { readonly turn?: number, readonly step?: number, readonly error?: unknown }): void {
    this.isolated(() => {
      const summary: Record<string, number | string> = {}
      const turn = count(detail.turn)
      const step = count(detail.step)
      if (turn !== undefined) summary.turn = turn
      if (step !== undefined) summary.step = step
      const error = detail.error
      const errorClass = error instanceof Error ? token(error.name) : undefined
      if (errorClass !== undefined) summary.error_class = errorClass
      this.record('agent_error', agent.session, agent, undefined, summary, {})
      this.requestFlush()
    })
  }

  observePreStep(agent: Agent, detail: { readonly turn?: number, readonly step?: number }): void {
    this.isolated(() => {
      const summary: Record<string, number | string> = {}
      const turn = count(detail.turn)
      const step = count(detail.step)
      if (turn !== undefined) summary.turn = turn
      if (step !== undefined) summary.step = step
      this.record('agent_pre_step', agent.session, agent, undefined, summary, {})
    })
  }

  observeSessionEvent(session: Session, event: SessionEvent): void {
    this.isolated(() => {
      const compact = compactSessionEvent(event)
      if (compact === undefined) return
      const time = typeof event.time === 'number' && Number.isFinite(event.time) ? event.time : undefined
      this.record(compact.kind, session, undefined, time, compact.summary, compact.sourceRefs)
      if (event.type === 'turn/end') this.requestFlush()
    })
  }

  observeSessionDisposed(session: Session): void {
    this.isolated(() => {
      this.record('session_disposed', session, undefined, undefined, {}, {})
      this.sequences.delete(String(session.id))
      this.requestFlush()
    })
  }

  stats(): ObserverStats {
    return {
      schema_version: OBSERVER_STATS_SCHEMA_VERSION,
      capability_id: CAPABILITY_ID,
      provider_id: PROVIDER_ID,
      observer_id: this.observerId,
      goal_id: this.config.goalId,
      emitted_at: new Date(this.now()).toISOString(),
      observed_event_count: this.observedEventCount,
      accepted_event_count: this.acceptedEventCount,
      rejected_event_count: 0,
      rejected_by_reason: {},
      buffer_bound: this.config.bufferBound,
      backpressure_drop_count: this.backpressureDropCount,
      observer_failure_count: this.observerFailureCount,
      outbound_endpoints: [],
      observation_entered_worker_context: false,
      clock_source: 'harness_event_time',
    }
  }

  /** Write buffered envelopes plus a stats record; never rejects. */
  async flush(): Promise<void> {
    if (this.flushing !== undefined) {
      this.flushRequested = true
      await this.flushing
      return
    }
    const taken = this.buffer
    this.buffer = []
    const lines = [...taken, this.stats()].map(record => JSON.stringify(record))
    this.flushing = this.appendLines(this.path, lines).then(
      () => undefined,
      (error: unknown) => {
        this.observerFailureCount += 1
        this.backpressureDropCount += taken.length
        this.warn(`dsh-loopx shadow observer flush failed: ${error instanceof Error ? error.name : 'unknown'}`)
      },
    )
    try {
      await this.flushing
    } finally {
      this.flushing = undefined
    }
    if (this.flushRequested) {
      this.flushRequested = false
      await this.flush()
    }
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    await this.flush()
  }

  private isolated(body: () => void): void {
    if (this.disposed) return
    try {
      body()
    } catch (error: unknown) {
      this.observerFailureCount += 1
      this.warn(`dsh-loopx shadow observer hook failed: ${error instanceof Error ? error.name : 'unknown'}`)
    }
  }

  private record(
    kind: ObserverEventKind,
    session: Session,
    agent: Agent | undefined,
    harnessTimeMs: number | undefined,
    summary: Record<string, number | string>,
    sourceRefs: Record<string, string>,
  ): void {
    this.observedEventCount += 1
    const sessionId = identity(session.id)
    if (sessionId === undefined) throw new Error('session id is not an identity token')
    const sequence = this.sequences.get(sessionId) ?? 0
    this.sequences.set(sessionId, sequence + 1)
    if (this.buffer.length >= this.config.bufferBound) {
      this.backpressureDropCount += 1
      this.requestFlush()
      return
    }
    const observedAtMs = harnessTimeMs ?? this.now()
    const agentId = agent === undefined ? undefined : identity(agent.id)
    const envelope: ObserverEnvelope = {
      schema_version: OBSERVER_ENVELOPE_SCHEMA_VERSION,
      capability_id: CAPABILITY_ID,
      provider_id: PROVIDER_ID,
      goal_id: this.config.goalId,
      session_id: sessionId,
      ...(agentId === undefined ? {} : { agent_id: agentId }),
      sequence,
      observed_at: new Date(observedAtMs).toISOString(),
      clock: harnessTimeMs === undefined
        ? { source: 'observer_wall_clock', uncertainty_ms: WALL_CLOCK_UNCERTAINTY_MS }
        : { source: 'harness_event_time', uncertainty_ms: 0 },
      event_kind: kind,
      summary,
      source_refs: sourceRefs,
    }
    this.buffer.push(envelope)
    this.acceptedEventCount += 1
    if (this.buffer.length >= this.config.bufferBound) this.requestFlush()
  }

  private requestFlush(): void {
    void this.flush()
  }
}

/**
 * Register read-only hooks only. Called by the Driver row's `apply()` solely
 * when `resolveShadowObserverConfig()` returns a config; when it returns
 * `undefined`, nothing here runs and feature-off parity holds.
 */
export function applyObserver(ctx: Context, config: ShadowObserverConfig): ShadowObserver {
  const observer = new ShadowObserver({
    config,
    warn: message => { ctx.logger.warn(message) },
  })
  ctx.effect(function* () {
    ctx.on('agent/session-start', ({ agent }) => { observer.observeSessionStart(agent) })
    ctx.on('agent/status', ({ agent, status }) => { observer.observeAgentStatus(agent, status) })
    ctx.on('agent/error', ({ agent, turn, step, error }) => {
      observer.observeAgentError(agent, { turn, step, error })
    })
    // Waterfall hook: observe, then hand the unchanged decision through.
    ctx.on('agent/pre-step', ({ agent, turn, step }, next) => {
      observer.observePreStep(agent, { turn, step })
      return next()
    })
    ctx.on('session/event', (session, event) => { observer.observeSessionEvent(session, event) })
    ctx.on('session/disposed', session => { observer.observeSessionDisposed(session) })
    yield async () => {
      await observer.dispose()
    }
  }, 'dsh-loopx shadow observer lifecycle')
  return observer
}

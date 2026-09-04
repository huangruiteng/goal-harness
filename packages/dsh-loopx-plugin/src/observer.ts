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
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'

export const name = 'dsh-loopx-shadow-observer'
export const inject: readonly string[] = []

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
export const ENV_SESSION_ID = 'LOOPX_DSH_SHADOW_OBSERVER_SESSION_ID'
export const ENV_RUN_IDENTITY = 'LOOPX_DSH_SHADOW_OBSERVER_RUN_IDENTITY_JSON'
export const ENV_LEDGER_DIR = 'LOOPX_DSH_SHADOW_OBSERVER_LEDGER_DIR'
export const ENV_BUFFER_BOUND = 'LOOPX_DSH_SHADOW_OBSERVER_BUFFER_BOUND'

export const EVENT_SOURCES = [
  'session/created',
  'session/disposed',
  'session/event',
] as const
export const SOURCE_FIELDS_CONSUMED = [
  'event.data.callId',
  'event.data.error.code',
  'event.data.id',
  'event.data.message.source.callId',
  'event.data.name',
  'event.data.reason.kind',
  'event.data.source.kind',
  'event.data.step',
  'event.data.turn',
  'event.seq',
  'event.time',
  'event.type',
  'session.id',
] as const
export const RUN_IDENTITY_FIELDS = [
  'worker_id',
  'model_id',
  'task_id',
  'environment_id',
  'tools_id',
  'budget_id',
  'adapter_revision',
  'observer_revision',
] as const

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
  readonly observer_id: string
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

export interface ObserverRunIdentity {
  readonly worker_id: string
  readonly model_id: string
  readonly task_id: string
  readonly environment_id: string
  readonly tools_id: string
  readonly budget_id: string
  readonly adapter_revision: string
  readonly observer_revision: string
}

export interface ObserverStats {
  readonly schema_version: typeof OBSERVER_STATS_SCHEMA_VERSION
  readonly capability_id: typeof CAPABILITY_ID
  readonly provider_id: typeof PROVIDER_ID
  readonly observer_id: string
  readonly goal_id: string
  readonly run_identity: ObserverRunIdentity
  readonly event_sources: readonly string[]
  readonly source_fields_consumed: readonly string[]
  readonly emitted_at: string
  readonly observed_event_count: number
  readonly accepted_event_count: number
  readonly rejected_event_count: number
  readonly rejected_by_reason: Readonly<Record<string, number>>
  readonly buffer_bound: number
  readonly backpressure_drop_count: number
  readonly observer_failure_count: number
  readonly peak_buffered_event_count: number
  readonly flush_attempt_count: number
  /** Always empty: the observer has no outbound control path to declare. */
  readonly outbound_endpoints: readonly []
  readonly observation_entered_worker_context: false
  readonly observation_entered_scheduler_inputs: false
  readonly clock_source: ClockSource
}

export interface ShadowObserverConfig {
  readonly goalId: string
  readonly sessionId: string
  readonly runIdentity: ObserverRunIdentity
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
 * The observer is OFF unless one exact goal, session, and pinned run identity
 * are declared. Returning `undefined` is the feature-off path: no hooks or
 * files. Partial or malformed configuration never broadens observation.
 */
export function resolveShadowObserverConfig(
  env: NodeJS.ProcessEnv = process.env,
): ShadowObserverConfig | undefined {
  const goalId = env[ENV_GOAL_ID]?.trim()
  const sessionId = env[ENV_SESSION_ID]?.trim()
  const runIdentity = parseRunIdentity(env[ENV_RUN_IDENTITY])
  if (!goalId || !IDENTITY_TOKEN.test(goalId)
    || !sessionId || !IDENTITY_TOKEN.test(sessionId)
    || runIdentity === undefined) return undefined
  const rawBound = Number.parseInt(env[ENV_BUFFER_BOUND] ?? '', 10)
  const bufferBound = Number.isInteger(rawBound) && rawBound >= 1 && rawBound <= MAX_BUFFER_BOUND
    ? rawBound
    : DEFAULT_BUFFER_BOUND
  return { goalId, sessionId, runIdentity, ledgerDir: defaultLedgerDir(env), bufferBound }
}

function validRunIdentity(value: unknown): value is ObserverRunIdentity {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  const actual = Object.keys(record).sort()
  const expected = [...RUN_IDENTITY_FIELDS].sort()
  return actual.length === expected.length
    && expected.every((field, index) => actual[index] === field)
    && RUN_IDENTITY_FIELDS.every((field) => {
      const item = record[field]
      return typeof item === 'string' && IDENTITY_TOKEN.test(item)
    })
}

function parseRunIdentity(raw: string | undefined): ObserverRunIdentity | undefined {
  if (raw === undefined) return undefined
  try {
    const parsed = JSON.parse(raw) as unknown
    return validRunIdentity(parsed) ? parsed : undefined
  } catch {
    return undefined
  }
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
      put('reason', token((data.reason as Record<string, unknown> | undefined)?.kind))
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
  private nextSequence = 0
  private buffer: ObserverEnvelope[] = []
  private flushing: Promise<void> | undefined
  private flushRequested = false
  private disposed = false
  private observedEventCount = 0
  private acceptedEventCount = 0
  private rejectedEventCount = 0
  private readonly rejectedByReason = new Map<string, number>()
  private backpressureDropCount = 0
  private observerFailureCount = 0
  private peakBufferedEventCount = 0
  private flushAttemptCount = 0

  constructor(options: ShadowObserverOptions) {
    if (!IDENTITY_TOKEN.test(options.config.goalId)) throw new Error('goal id must be an identity token')
    if (!IDENTITY_TOKEN.test(options.config.sessionId)) throw new Error('session id must be an identity token')
    if (!validRunIdentity(options.config.runIdentity)) throw new Error('run identity must be fully pinned')
    if (!Number.isInteger(options.config.bufferBound)
      || options.config.bufferBound < 1
      || options.config.bufferBound > MAX_BUFFER_BOUND) {
      throw new Error(`buffer bound must be within 1..${MAX_BUFFER_BOUND}`)
    }
    const observerId = options.observerId ?? `${PROVIDER_ID}-${randomUUID()}`
    if (!IDENTITY_TOKEN.test(observerId)) throw new Error('observer id must be an identity token')
    this.config = {
      ...options.config,
      runIdentity: { ...options.config.runIdentity },
    }
    this.now = options.now ?? Date.now
    this.appendLines = options.appendLines ?? appendLedgerLines
    this.warn = options.warn ?? (() => {})
    this.observerId = observerId
  }

  get path(): string {
    return ledgerPath(this.config)
  }

  observeSessionCreated(session: Session): void {
    this.isolated(() => this.record('session_started', session, undefined, {}, {}))
  }

  observeSessionEvent(session: Session, event: SessionEvent): void {
    this.isolated(() => {
      if (this.rejectIfUnbound(session)) return
      const compact = compactSessionEvent(event)
      if (compact === undefined) return
      const time = typeof event.time === 'number' && Number.isFinite(event.time) ? event.time : undefined
      this.record(compact.kind, session, time, compact.summary, compact.sourceRefs)
      if (event.type === 'turn/end') this.requestFlush()
    })
  }

  observeSessionDisposed(session: Session): void {
    this.isolated(() => {
      this.record('session_disposed', session, undefined, {}, {})
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
      run_identity: { ...this.config.runIdentity },
      event_sources: EVENT_SOURCES,
      source_fields_consumed: SOURCE_FIELDS_CONSUMED,
      emitted_at: new Date(this.now()).toISOString(),
      observed_event_count: this.observedEventCount,
      accepted_event_count: this.acceptedEventCount,
      rejected_event_count: this.rejectedEventCount,
      rejected_by_reason: Object.fromEntries([...this.rejectedByReason].sort(([left], [right]) => left.localeCompare(right))),
      buffer_bound: this.config.bufferBound,
      backpressure_drop_count: this.backpressureDropCount,
      observer_failure_count: this.observerFailureCount,
      peak_buffered_event_count: this.peakBufferedEventCount,
      flush_attempt_count: this.flushAttemptCount,
      outbound_endpoints: [],
      observation_entered_worker_context: false,
      observation_entered_scheduler_inputs: false,
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
    this.flushAttemptCount += 1
    const lines = [...taken, this.stats()].map(record => JSON.stringify(record))
    this.flushing = this.appendLines(this.path, lines).then(
      () => undefined,
      (error: unknown) => {
        this.observerFailureCount += 1
        this.acceptedEventCount -= taken.length
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
    const observedBefore = this.observedEventCount
    try {
      body()
    } catch (error: unknown) {
      this.observerFailureCount += 1
      if (this.observedEventCount === observedBefore) this.observedEventCount += 1
      this.reject('observer_internal_failure')
      this.warn(`dsh-loopx shadow observer hook failed: ${error instanceof Error ? error.name : 'unknown'}`)
    }
  }

  private record(
    kind: ObserverEventKind,
    session: Session,
    harnessTimeMs: number | undefined,
    summary: Record<string, number | string>,
    sourceRefs: Record<string, string>,
  ): void {
    this.observedEventCount += 1
    const sessionId = identity(session.id)
    if (sessionId === undefined || sessionId !== this.config.sessionId) {
      this.reject('identity_invalid')
      return
    }
    const sequence = this.nextSequence
    this.nextSequence += 1
    if (this.buffer.length >= this.config.bufferBound) {
      this.backpressureDropCount += 1
      this.requestFlush()
      return
    }
    const observedAtMs = harnessTimeMs ?? this.now()
    const observedAt = new Date(observedAtMs)
    if (!Number.isFinite(observedAt.getTime())) {
      this.reject('clock_invalid')
      return
    }
    const envelope: ObserverEnvelope = {
      schema_version: OBSERVER_ENVELOPE_SCHEMA_VERSION,
      capability_id: CAPABILITY_ID,
      provider_id: PROVIDER_ID,
      observer_id: this.observerId,
      goal_id: this.config.goalId,
      session_id: sessionId,
      sequence,
      observed_at: observedAt.toISOString(),
      clock: harnessTimeMs === undefined
        ? { source: 'observer_wall_clock', uncertainty_ms: WALL_CLOCK_UNCERTAINTY_MS }
        : { source: 'harness_event_time', uncertainty_ms: 0 },
      event_kind: kind,
      summary,
      source_refs: sourceRefs,
    }
    this.buffer.push(envelope)
    this.acceptedEventCount += 1
    this.peakBufferedEventCount = Math.max(this.peakBufferedEventCount, this.buffer.length)
    if (this.buffer.length >= this.config.bufferBound) this.requestFlush()
  }

  private reject(reason: string): void {
    this.rejectedEventCount += 1
    this.rejectedByReason.set(reason, (this.rejectedByReason.get(reason) ?? 0) + 1)
  }

  private rejectIfUnbound(session: Session): boolean {
    const sessionId = identity(session.id)
    if (sessionId === this.config.sessionId) return false
    this.observedEventCount += 1
    this.reject('identity_invalid')
    return true
  }

  private requestFlush(): void {
    void this.flush()
  }
}

/** Register only the session log's read-only publication hooks. */
export function registerShadowObserver(ctx: Context, config: ShadowObserverConfig): ShadowObserver {
  const observer = new ShadowObserver({
    config,
    warn: message => { ctx.logger.warn(message) },
  })
  ctx.effect(function* () {
    ctx.on('session/created', session => { observer.observeSessionCreated(session) })
    ctx.on('session/event', (session, event) => { observer.observeSessionEvent(session, event) })
    ctx.on('session/disposed', session => { observer.observeSessionDisposed(session) })
    yield async () => {
      await observer.dispose()
    }
  }, 'dsh-loopx shadow observer lifecycle')
  return observer
}

/** Cordis entrypoint. Partial configuration is the exact feature-off path. */
export function apply(ctx: Context): void {
  const config = resolveShadowObserverConfig()
  if (config === undefined) return
  registerShadowObserver(ctx, config)
}

import { randomUUID } from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent, AgentStatus, PreStepDecision } from '@deepseek-ai/dsh-agent'
import type {} from '@deepseek-ai/dsh-commands'
import type {} from '@deepseek-ai/dsh-session'
import type { SessionEvent, UserMessage } from '@deepseek-ai/dsh-session'
import {
  LoopXCliError,
  resolveLoopXCommand,
  runJsonCommand,
} from './cli.ts'
import type { FileRunner, LoopXCommand } from './cli.ts'

export const name = 'dsh-loopx-driver'
export const inject = ['agents']

const DRIVER_SOURCE_ID = 'dsh-loopx-plugin/driver'
const HOST_SURFACE = 'deepseek-harness-native'
const RESOLUTION_SCHEMA = 'loopx_thread_agent_binding_resolution_v0'
const HEARTBEAT_SCHEMA = 'loopx_heartbeat_prompt_v0'
const DEFAULT_WAIT_MS = 5 * 60_000
const MAX_WAIT_MS = 24 * 60 * 60_000

type TimerHandle = unknown
type ReservationPhase = 'queued' | 'claimed' | 'admitted' | 'retired'

export interface DriverClock {
  setTimeout(callback: () => void, delayMs: number): TimerHandle
  clearTimeout(handle: TimerHandle): void
}

interface Binding {
  readonly goalId: string
  readonly agentId: string
}

interface Reservation extends Binding {
  readonly session: Agent['session']
  readonly messageId: UserMessage['id']
  readonly content: UserMessage['content']
  readonly turnInstanceId: string
  phase: ReservationPhase
}

interface DriverState {
  readonly agent: Agent
  requested: boolean
  stopping: boolean
  competing: boolean
  pauseAfterTurnError: boolean
  schedulerToken: string
  unchangedPolls: number
  readonly commands: Set<string>
  run?: Promise<void> | undefined
  controller?: AbortController | undefined
  timer?: TimerHandle | undefined
  reservation?: Reservation | undefined
}

interface QueuePlan extends Binding {
  readonly kind: 'queue'
  readonly session: Agent['session']
  readonly turnInstanceId: string
  readonly taskBody: string
}

interface WaitPlan {
  readonly kind: 'wait'
  readonly delayMs?: number | undefined
  readonly schedulerToken?: string | undefined
  readonly unchangedPolls?: number | undefined
}

type EvaluationPlan = QueuePlan | WaitPlan

export interface LoopXDriverOptions {
  readonly isLiveAgent: (agent: Agent) => boolean
  readonly runner?: FileRunner | undefined
  readonly clock?: DriverClock | undefined
  readonly makeTurnInstanceId?: (() => string) | undefined
  readonly retryDelaysMs?: readonly number[] | undefined
  readonly runDetached?: (<T>(operation: () => Promise<T>) => Promise<T>) | undefined
  readonly warn?: ((message: string) => void) | undefined
}

const systemClock: DriverClock = Object.freeze({
  setTimeout(callback: () => void, delayMs: number) {
    return setTimeout(callback, delayMs)
  },
  clearTimeout(handle: TimerHandle) {
    clearTimeout(handle as ReturnType<typeof setTimeout>)
  },
})

function isDriverMessage(message: UserMessage): boolean {
  return message.source.kind === 'plugin' && message.source.plugin === DRIVER_SOURCE_ID
}

function sameReservation(message: UserMessage, reservation: Reservation): boolean {
  return message.id === reservation.messageId
    && isDriverMessage(message)
    && isDeepStrictEqual(message.content, reservation.content)
}

function automaticMessage(taskBody: string): UserMessage {
  const content: UserMessage['content'] = Object.freeze([
    Object.freeze({ type: 'text' as const, text: taskBody }),
  ]) as UserMessage['content']
  return Object.freeze({
    id: randomUUID() as UserMessage['id'],
    role: 'user' as const,
    content,
    source: Object.freeze({ kind: 'plugin' as const, plugin: DRIVER_SOURCE_ID }),
  })
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function exactBinding(
  payload: Record<string, unknown>,
  threadId: string,
): Binding | undefined {
  if (payload.schema_version !== RESOLUTION_SCHEMA
    || payload.ok !== true
    || payload.status !== 'bound'
    || payload.host_surface !== HOST_SURFACE
    || payload.thread_id !== threadId) return undefined
  const goalId = typeof payload.goal_id === 'string' ? payload.goal_id : ''
  const agentId = typeof payload.agent_id === 'string' ? payload.agent_id : ''
  const matches = Array.isArray(payload.matches) ? payload.matches : []
  const match = matches.length === 1 ? record(matches[0]) : undefined
  return goalId.length > 0
    && goalId.trim() === goalId
    && agentId.length > 0
    && agentId.trim() === agentId
    && match?.goal_id === goalId
    && match.agent_id === agentId
    ? { goalId, agentId }
    : undefined
}

function exactQuotaContext(
  payload: Record<string, unknown>,
  binding: Binding,
): boolean {
  const identity = record(payload.agent_identity)
  return payload.mode === 'should-run'
    && payload.goal_id === binding.goalId
    && identity?.agent_id === binding.agentId
    && identity.registered === true
}

function exactQuota(
  payload: Record<string, unknown>,
  binding: Binding,
): boolean {
  return exactQuotaContext(payload, binding)
    && payload.ok === true
    && payload.should_run === true
}

function schedulerWait(
  payload: Record<string, unknown>,
  currentToken: string,
  currentPolls: number,
): WaitPlan {
  const scheduler = record(payload.scheduler_hint)
  const unchanged = record(scheduler?.unchanged_poll)
  const local = record(unchanged?.local_scheduler)
  if (local === undefined) return { kind: 'wait' }

  const reset = record(scheduler?.reset_policy)
  const token = typeof reset?.reset_token === 'string' ? reset.reset_token : ''
  const unchangedPolls = token.length > 0 && token === currentToken
    ? currentPolls
    : 0
  const rawLimit = local.unchanged_poll_limit
  const limit = typeof rawLimit === 'number'
    && Number.isSafeInteger(rawLimit)
    && rawLimit >= 0
    ? rawLimit
    : undefined
  if (limit !== undefined && unchangedPolls >= limit) {
    return { kind: 'wait', schedulerToken: token, unchangedPolls }
  }

  const progression = Array.isArray(local.example_progression_minutes)
    ? local.example_progression_minutes.filter((value): value is number => (
        typeof value === 'number' && Number.isFinite(value) && value > 0
      ))
    : []
  const recommended = local.recommended_interval_minutes
  const fallback = typeof recommended === 'number'
    && Number.isFinite(recommended)
    && recommended > 0
    ? recommended
    : DEFAULT_WAIT_MS / 60_000
  const minutes = progression.length > 0
    ? progression[Math.min(unchangedPolls, progression.length - 1)] ?? fallback
    : fallback
  return {
    kind: 'wait',
    delayMs: Math.min(Math.round(minutes * 60_000), MAX_WAIT_MS),
    schedulerToken: token,
    unchangedPolls: unchangedPolls + 1,
  }
}

function exactHeartbeat(
  payload: Record<string, unknown>,
  binding: Binding,
): string | undefined {
  if (payload.schema_version !== HEARTBEAT_SCHEMA
    || payload.ok !== true
    || payload.goal_id !== binding.goalId
    || payload.agent_id !== binding.agentId) return undefined
  const taskBody = typeof payload.task_body === 'string' ? payload.task_body : ''
  return taskBody.length > 0 && taskBody.length <= 32_000 ? taskBody : undefined
}

function renderThrown(value: unknown): string {
  if (value instanceof LoopXCliError) return `${value.kind}:${value.message}`
  return value instanceof Error ? value.message : String(value)
}

/** Exact-session driver with no local activation, binding mirror, or failure counter. */
export class LoopXContinuationDriver {
  private readonly states = new Map<Agent, DriverState>()
  private readonly isLiveAgent: (agent: Agent) => boolean
  private readonly runner: FileRunner | undefined
  private readonly clock: DriverClock
  private readonly makeTurnInstanceId: () => string
  private readonly retryDelaysMs: readonly number[]
  private readonly runDetached: <T>(operation: () => Promise<T>) => Promise<T>
  private readonly warn: (message: string) => void
  private command?: LoopXCommand | undefined
  private disposed = false

  constructor(options: LoopXDriverOptions) {
    this.isLiveAgent = options.isLiveAgent
    this.runner = options.runner
    this.clock = options.clock ?? systemClock
    this.makeTurnInstanceId = options.makeTurnInstanceId
      ?? (() => `dsh-loopx-${randomUUID()}`)
    this.retryDelaysMs = options.retryDelaysMs ?? [200, 750]
    this.runDetached = options.runDetached ?? (operation => operation())
    this.warn = options.warn ?? (() => {})
  }

  observeAgent(agent: Agent): void {
    this.stateFor(agent)
    if (agent.status === 'idle') this.requestEvaluation(this.stateFor(agent))
  }

  onAgentDisposed(agent: Agent): void {
    const state = this.states.get(agent)
    if (state === undefined) return
    this.stopState(state)
    this.states.delete(agent)
  }

  onSessionStart(agent: Agent): void {
    const state = this.stateFor(agent)
    this.cancelPending(state)
    this.retireReservation(state)
    state.competing = agent.inbox.hasPending
    state.pauseAfterTurnError = false
    state.schedulerToken = ''
    state.unchangedPolls = 0
    state.commands.clear()
    this.requestEvaluation(state)
  }

  onAgentStatus(agent: Agent, status: AgentStatus): void {
    if (status !== 'idle') return
    const state = this.stateFor(agent)
    if (state.reservation?.phase === 'claimed' || state.reservation?.phase === 'admitted') {
      this.retireReservation(state)
    }
    state.competing = agent.inbox.hasPending
    if (!state.pauseAfterTurnError) this.requestEvaluation(state)
  }

  onInboxInserted(agent: Agent, message: UserMessage): void {
    const state = this.stateFor(agent)
    if (state.reservation !== undefined && sameReservation(message, state.reservation)) return
    state.competing = true
    if (message.source.kind === 'user') state.pauseAfterTurnError = false
    this.cancelPending(state)
  }

  onInboxClaimed(agent: Agent, message: UserMessage): void {
    const state = this.stateFor(agent)
    if (state.reservation !== undefined && sameReservation(message, state.reservation)) {
      state.reservation.phase = 'claimed'
      return
    }
    state.competing = true
  }

  onInboxDiscarded(agent: Agent, message: UserMessage): void {
    const state = this.states.get(agent)
    if (state?.reservation !== undefined && sameReservation(message, state.reservation)) {
      this.retireReservation(state)
    }
  }

  onAgentError(agent: Agent): void {
    const state = this.stateFor(agent)
    state.pauseAfterTurnError = true
    this.cancelPending(state)
  }

  onSessionEvent(agent: Agent, event: SessionEvent): void {
    const state = this.states.get(agent)
    if (state === undefined) return
    if (event.type === 'command/run') {
      state.commands.add(String(event.data.commandId))
      state.competing = true
      this.cancelPending(state)
      return
    }
    if (event.type === 'command/done') {
      state.commands.delete(String(event.data.commandId))
      if (state.commands.size === 0) {
        state.competing = agent.inbox.hasPending
        if (agent.status === 'idle' && !state.pauseAfterTurnError) {
          this.requestEvaluation(state)
        }
      }
      return
    }
    if (event.type === 'user/message'
      && state.reservation !== undefined
      && event.data.id === state.reservation.messageId) {
      state.reservation.phase = 'admitted'
      return
    }
    if (event.type === 'turn/end'
      && (event.data.reason.kind === 'max-tokens' || event.data.reason.kind === 'aborted')) {
      state.pauseAfterTurnError = true
      this.cancelPending(state)
    }
  }

  async onPreStep(
    agent: Agent,
    messages: UserMessage[],
    signal: AbortSignal,
    next: () => Promise<PreStepDecision>,
  ): Promise<PreStepDecision> {
    const state = this.stateFor(agent)
    const submitted = messages.find(message => isDriverMessage(message))
    if (submitted === undefined) return next()
    const reservation = state.reservation
    if (reservation === undefined || !sameReservation(submitted, reservation)
      || reservation.phase !== 'claimed') {
      this.restoreOtherMessages(agent, messages, submitted)
      return { kind: 'reject' }
    }
    if (messages.some(message => message.id !== submitted.id)) {
      this.retireReservation(state)
      this.restoreOtherMessages(agent, messages, submitted)
      return { kind: 'reject' }
    }

    if (!(await this.authorityStillAllows(state, reservation, signal))) {
      this.retireReservation(state)
      this.restoreOtherMessages(agent, messages, submitted)
      this.requestEvaluation(state)
      return { kind: 'reject' }
    }

    let decision: PreStepDecision
    try {
      decision = await next()
    } catch (error: unknown) {
      state.pauseAfterTurnError = true
      this.retireReservation(state)
      throw error
    }
    if (signal.aborted) {
      state.pauseAfterTurnError = true
      this.retireReservation(state)
      return decision
    }
    if (decision.kind === 'reject') {
      state.pauseAfterTurnError = true
      this.retireReservation(state)
      return decision
    }
    if (!(await this.authorityStillAllows(state, reservation, signal))) {
      this.retireReservation(state)
      this.restoreOtherMessages(agent, decision.messages, submitted)
      return { kind: 'reject' }
    }
    return decision
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    const waits: Promise<void>[] = []
    for (const state of this.states.values()) {
      const activeAutomaticStep = state.reservation?.phase === 'claimed'
        || state.reservation?.phase === 'admitted'
      this.stopState(state)
      if (activeAutomaticStep && state.agent.status === 'running') {
        try {
          state.agent.cancel({ kind: 'parent' })
          waits.push(state.agent.whenIdle())
        } catch (error: unknown) {
          this.warn(`dsh-loopx-driver: could not cancel active work: ${renderThrown(error)}`)
        }
      }
      if (state.run !== undefined) waits.push(state.run)
    }
    await Promise.allSettled(waits)
    this.states.clear()
  }

  private stateFor(agent: Agent): DriverState {
    const existing = this.states.get(agent)
    if (existing !== undefined) return existing
    const state: DriverState = {
      agent,
      requested: false,
      stopping: false,
      competing: agent.inbox.hasPending,
      pauseAfterTurnError: false,
      schedulerToken: '',
      unchangedPolls: 0,
      commands: new Set(),
    }
    this.states.set(agent, state)
    return state
  }

  private ready(state: DriverState): boolean {
    return !this.disposed
      && !state.stopping
      && !state.pauseAfterTurnError
      && !state.competing
      && state.commands.size === 0
      && state.reservation === undefined
      && this.isLiveAgent(state.agent)
      && state.agent.status === 'idle'
      && !state.agent.inbox.hasPending
      && state.agent.id === state.agent.session.id
      && state.agent.id === state.agent.session.header.id
      && typeof state.agent.session.header.cwd === 'string'
      && state.agent.session.header.cwd.length > 0
  }

  private requestEvaluation(state: DriverState): void {
    if (state.stopping || this.disposed) return
    state.requested = true
    if (state.run !== undefined) return
    let run: Promise<void>
    try {
      run = this.runDetached(async () => {
        while (state.requested && !state.stopping) {
          state.requested = false
          await this.evaluate(state)
        }
      })
    } catch (error: unknown) {
      state.requested = false
      this.warn(`dsh-loopx-driver: could not start evaluation: ${renderThrown(error)}`)
      return
    }
    state.run = run
    const retire = (): void => {
      state.run = undefined
      if (state.requested && !state.stopping) this.requestEvaluation(state)
    }
    void run.then(retire, error => {
      this.warn(`dsh-loopx-driver: evaluation failed: ${renderThrown(error)}`)
      retire()
    })
  }

  private async evaluate(state: DriverState): Promise<void> {
    if (!this.ready(state)) return
    const controller = new AbortController()
    state.controller = controller
    let plan: EvaluationPlan
    try {
      plan = await state.agent.runMaintenance(async maintenanceSignal => {
        const signal = AbortSignal.any([controller.signal, maintenanceSignal])
        return this.buildPlan(state, signal)
      })
    } catch (error: unknown) {
      const cancelled = error instanceof LoopXCliError && error.kind === 'aborted'
      if (error instanceof LoopXCliError && error.kind === 'missing') {
        this.command = undefined
      }
      if (!controller.signal.aborted && !cancelled) {
        this.warn(`dsh-loopx-driver: LoopX admission failed: ${renderThrown(error)}`)
      }
      return
    } finally {
      if (state.controller === controller) state.controller = undefined
    }

    if (plan.kind === 'wait') {
      if (plan.schedulerToken !== undefined) state.schedulerToken = plan.schedulerToken
      if (plan.unchangedPolls !== undefined) state.unchangedPolls = plan.unchangedPolls
      if (plan.delayMs !== undefined) this.schedule(state, plan.delayMs)
      return
    }
    state.schedulerToken = ''
    state.unchangedPolls = 0
    if (!this.ready(state) || state.agent.session !== plan.session) return
    const message = automaticMessage(plan.taskBody)
    const reservation: Reservation = {
      messageId: message.id,
      content: message.content,
      session: plan.session,
      goalId: plan.goalId,
      agentId: plan.agentId,
      turnInstanceId: plan.turnInstanceId,
      phase: 'queued',
    }
    state.reservation = reservation
    try {
      state.agent.followup(message)
    } catch (error: unknown) {
      this.retireReservation(state)
      this.warn(`dsh-loopx-driver: could not queue same-session work: ${renderThrown(error)}`)
    }
  }

  private ensureReady(
    state: DriverState,
    signal: AbortSignal,
    session: Agent['session'],
  ): void {
    if (signal.aborted || !this.ready(state) || state.agent.session !== session) {
      throw new LoopXCliError('aborted', 'automatic admission was fenced', false)
    }
  }

  private async buildPlan(
    state: DriverState,
    signal: AbortSignal,
  ): Promise<EvaluationPlan> {
    const session = state.agent.session
    this.ensureReady(state, signal, session)
    const command = await this.loopXCommand(signal)
    this.ensureReady(state, signal, session)
    const bindingPayload = await this.resolveBinding(command, state.agent, signal)
    this.ensureReady(state, signal, session)
    if (bindingPayload.ok !== true) {
      throw new LoopXCliError(
        'typed_failure',
        'LoopX binding authority rejected automatic continuation',
        false,
      )
    }
    const binding = exactBinding(bindingPayload, String(state.agent.id))
    if (binding === undefined) {
      return { kind: 'wait', schedulerToken: '', unchangedPolls: 0 }
    }

    const turnInstanceId = this.makeTurnInstanceId()
    const quota = await this.readQuota(command, state.agent, binding, turnInstanceId, signal)
    this.ensureReady(state, signal, session)
    if (quota.ok !== true) {
      throw new LoopXCliError(
        'typed_failure',
        'LoopX quota authority rejected automatic continuation',
        false,
      )
    }
    if (!exactQuotaContext(quota, binding)) {
      throw new LoopXCliError(
        'invalid_schema',
        'LoopX quota response did not match the bound Goal and Agent',
        false,
      )
    }
    if (quota.should_run !== true) {
      return schedulerWait(quota, state.schedulerToken, state.unchangedPolls)
    }
    const heartbeat = await this.readHeartbeat(command, state.agent, binding, signal)
    this.ensureReady(state, signal, session)
    if (heartbeat.ok !== true) {
      throw new LoopXCliError(
        'typed_failure',
        'LoopX heartbeat authority rejected automatic continuation',
        false,
      )
    }
    const taskBody = exactHeartbeat(heartbeat, binding)
    if (taskBody === undefined) {
      throw new LoopXCliError(
        'invalid_schema',
        'LoopX heartbeat response did not match the bound Goal and Agent',
        false,
      )
    }
    return { kind: 'queue', ...binding, session, turnInstanceId, taskBody }
  }

  private async authorityStillAllows(
    state: DriverState,
    reservation: Reservation,
    signal: AbortSignal,
  ): Promise<boolean> {
    if (signal.aborted || !this.isLiveAgent(state.agent)
      || state.agent.session !== reservation.session
      || state.stopping || state.pauseAfterTurnError
      || state.competing || state.reservation !== reservation) return false
    try {
      const command = await this.loopXCommand(signal)
      const bindingPayload = await this.resolveBinding(command, state.agent, signal)
      const binding = exactBinding(bindingPayload, String(state.agent.id))
      if (binding?.goalId !== reservation.goalId || binding.agentId !== reservation.agentId) {
        return false
      }
      const quota = await this.readQuota(
        command,
        state.agent,
        reservation,
        reservation.turnInstanceId,
        signal,
      )
      return !signal.aborted
        && state.reservation === reservation
        && state.agent.session === reservation.session
        && exactQuota(quota, reservation)
    } catch (error: unknown) {
      if (error instanceof LoopXCliError && error.kind === 'missing') {
        this.command = undefined
      }
      if (!(error instanceof LoopXCliError && error.kind === 'aborted')) {
        this.warn(`dsh-loopx-driver: pre-step authority check failed: ${renderThrown(error)}`)
      }
      return false
    }
  }

  private async loopXCommand(signal: AbortSignal): Promise<LoopXCommand> {
    if (this.command !== undefined) return this.command
    const resolved = await resolveLoopXCommand({ runner: this.runner, signal })
    if (!signal.aborted) this.command = resolved
    return resolved
  }

  private resolveBinding(
    command: LoopXCommand,
    agent: Agent,
    signal: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return runJsonCommand(
      command,
      [
        '--registry', '.loopx/registry.json',
        '--format', 'json',
        'resolve-agent-thread',
        '--host-surface', HOST_SURFACE,
        '--thread-id', String(agent.id),
      ],
      {
        runner: this.runner,
        cwd: agent.session.header.cwd,
        signal,
        attempts: 3,
        retryDelaysMs: this.retryDelaysMs,
        validate: payload => payload.schema_version === RESOLUTION_SCHEMA
          && payload.host_surface === HOST_SURFACE
          && payload.thread_id === String(agent.id),
      },
    )
  }

  private readQuota(
    command: LoopXCommand,
    agent: Agent,
    binding: Binding,
    turnInstanceId: string,
    signal: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return runJsonCommand(
      command,
      [
        '--registry', '.loopx/registry.json',
        '--format', 'json',
        'quota', 'should-run',
        '--goal-id', binding.goalId,
        '--agent-id', binding.agentId,
        '--runtime-profile', 'generic_cli',
        '--include-detail', 'scheduler',
        '--turn-instance-id', turnInstanceId,
      ],
      {
        runner: this.runner,
        cwd: agent.session.header.cwd,
        signal,
        attempts: 3,
        retryDelaysMs: this.retryDelaysMs,
        validate: payload => payload.goal_id === binding.goalId
          && typeof payload.ok === 'boolean'
          && typeof payload.should_run === 'boolean',
      },
    )
  }

  private readHeartbeat(
    command: LoopXCommand,
    agent: Agent,
    binding: Binding,
    signal: AbortSignal,
  ): Promise<Record<string, unknown>> {
    return runJsonCommand(
      command,
      [
        '--registry', '.loopx/registry.json',
        '--format', 'json',
        'heartbeat-prompt', '--thin',
        '--goal-id', binding.goalId,
        '--agent-id', binding.agentId,
        '--runtime-profile', 'generic_cli',
      ],
      {
        runner: this.runner,
        cwd: agent.session.header.cwd,
        signal,
        attempts: 3,
        retryDelaysMs: this.retryDelaysMs,
        validate: payload => payload.schema_version === HEARTBEAT_SCHEMA
          && payload.goal_id === binding.goalId
          && payload.agent_id === binding.agentId,
      },
    )
  }

  private schedule(state: DriverState, delayMs: number): void {
    if (state.stopping || this.disposed) return
    if (state.timer !== undefined) this.clock.clearTimeout(state.timer)
    const handle = this.clock.setTimeout(() => {
      if (state.timer !== handle) return
      state.timer = undefined
      this.requestEvaluation(state)
    }, Math.max(0, Math.min(delayMs, MAX_WAIT_MS)))
    state.timer = handle
  }

  private cancelPending(state: DriverState): void {
    state.requested = false
    state.controller?.abort()
    state.controller = undefined
    if (state.timer !== undefined) {
      this.clock.clearTimeout(state.timer)
      state.timer = undefined
    }
    const reservation = state.reservation
    if (reservation === undefined || reservation.phase !== 'queued') return
    state.agent.inbox.remove(reservation.messageId)
    this.retireReservation(state)
  }

  private retireReservation(state: DriverState): void {
    if (state.reservation === undefined) return
    state.reservation.phase = 'retired'
    state.reservation = undefined
  }

  private restoreOtherMessages(
    agent: Agent,
    messages: UserMessage[],
    submitted: UserMessage,
  ): void {
    for (const message of messages) {
      if (message.id === submitted.id || isDriverMessage(message)) continue
      if (agent.inbox.nextStep.some(candidate => candidate.id === message.id)
        || agent.inbox.nextTurn.some(candidate => candidate.id === message.id)) continue
      agent.send(message, 'next-step', true)
    }
  }

  private stopState(state: DriverState): void {
    state.stopping = true
    this.cancelPending(state)
  }
}

export function apply(ctx: Context): void {
  const driver = new LoopXContinuationDriver({
    isLiveAgent: agent => ctx.agents.get(agent.id) === agent,
    runDetached: operation => ctx.agents.withoutInitiator(operation),
    warn: message => { ctx.logger.warn(message) },
  })

  ctx.effect(function* () {
    ctx.on('agent/created', ({ agent }) => { driver.observeAgent(agent) })
    ctx.on('agent/disposed', ({ agent }) => { driver.onAgentDisposed(agent) })
    ctx.on('agent/session-start', ({ agent }) => { driver.onSessionStart(agent) })
    ctx.on('agent/status', ({ agent, status }) => { driver.onAgentStatus(agent, status) })
    ctx.on('agent/inbox/inserted', ({ agent, message }) => driver.onInboxInserted(agent, message))
    ctx.on('agent/inbox/claimed', ({ agent, message }) => driver.onInboxClaimed(agent, message))
    ctx.on('agent/inbox/discarded', ({ agent, message }) => driver.onInboxDiscarded(agent, message))
    ctx.on('agent/error', ({ agent }) => { driver.onAgentError(agent) })
    ctx.on('agent/pre-step', ({ agent, messages, signal }, next) => (
      driver.onPreStep(agent, messages, signal, next)
    ))
    ctx.on('session/event', (session, event) => {
      const agent = ctx.agents.get(session.id)
      if (agent?.session === session) driver.onSessionEvent(agent, event)
    })
    for (const agent of ctx.agents.list()) driver.observeAgent(agent)
    yield () => driver.dispose()
  }, 'dsh-loopx-driver lifecycle')
}

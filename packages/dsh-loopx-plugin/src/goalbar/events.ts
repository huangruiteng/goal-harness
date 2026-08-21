import type { Agent } from '@deepseek-ai/dsh-agent'
import type { Session, SessionEvent } from '@deepseek-ai/dsh-session'

export interface GoalBarSessionCapture {
  readonly agent: Agent
  readonly session: Session
}

export interface GoalBarTurnEndNotification {
  readonly sessionId: string
  readonly turnEndSeq: number
}

export type GoalBarTurnEndWaitReceipt =
  | ({ readonly kind: 'changed' } & GoalBarTurnEndNotification)
  | { readonly kind: 'timeout'; readonly turnEndSeq: number | null }
  | { readonly kind: 'session_unavailable' }
  | { readonly kind: 'aborted' }
  | { readonly kind: 'service_disposed' }

export type GoalBarDriverActionReceipt =
  | { readonly kind: 'applied' }
  | {
      readonly kind: 'unavailable'
      readonly reason:
        | 'driver_unavailable'
        | 'session_unavailable'
        | 'evaluation_unavailable'
    }

export interface GoalBarDriverBridge {
  activateAndEvaluate(
    capture: GoalBarSessionCapture,
  ): Promise<GoalBarDriverActionReceipt>
  cancelQueued(
    capture: GoalBarSessionCapture,
  ): Promise<GoalBarDriverActionReceipt>
}

export interface GoalBarTurnEndWaitOptions {
  readonly signal: AbortSignal
  readonly timeoutMs: number
  readonly isSessionCurrent: () => boolean
}

export interface GoalBarWatchService {
  waitForTurnEnd(
    session: Session,
    afterTurnEndSeq: number | null,
    options: GoalBarTurnEndWaitOptions,
  ): Promise<GoalBarTurnEndWaitReceipt>
  dispose(): void
}

interface WatchServiceState {
  disposed: boolean
}

interface PendingWaiter {
  readonly service: WatchServiceState
  readonly session: Session
  readonly afterTurnEndSeq: number | null
  readonly isSessionCurrent: () => boolean
  readonly resolve: (receipt: GoalBarTurnEndWaitReceipt) => void
  readonly signal: AbortSignal
  readonly onAbort: () => void
  readonly timer: ReturnType<typeof setTimeout>
  settled: boolean
}

function isSequence(value: unknown): value is number {
  return typeof value === 'number'
    && Number.isSafeInteger(value)
    && value >= 0
}

function isNewer(sequence: number, cursor: number | null): boolean {
  return cursor === null || sequence > cursor
}

function isCurrent(predicate: () => boolean): boolean {
  try {
    return predicate()
  } catch {
    return false
  }
}

/** Read the latest committed turn boundary directly from the immutable log. */
export function latestCommittedTurnEndSeq(session: Session): number | null {
  const events = session.events
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event?.type === 'turn/end' && isSequence(event.seq)) return event.seq
  }
  return null
}

/**
 * Feature-local process coordinator. It keeps only pending watches and the
 * current Driver bridge; committed cursors and GoalBar business state remain
 * owned by the exact Session and the Host read model respectively.
 */
export class GoalBarCoordinator {
  private readonly waiters = new Set<PendingWaiter>()
  private driverBridge?: GoalBarDriverBridge | undefined

  openWatchService(): GoalBarWatchService {
    const service: WatchServiceState = { disposed: false }
    return {
      waitForTurnEnd: (session, afterTurnEndSeq, options) => (
        this.waitForTurnEnd(service, session, afterTurnEndSeq, options)
      ),
      dispose: () => {
        if (service.disposed) return
        service.disposed = true
        for (const waiter of [...this.waiters]) {
          if (waiter.service === service) {
            this.settle(waiter, { kind: 'service_disposed' })
          }
        }
      },
    }
  }

  publishTurnEnd(
    session: Session,
    event: SessionEvent<'turn/end'>,
  ): void {
    if (!isSequence(event.seq)) return
    const notification: GoalBarTurnEndNotification = {
      sessionId: String(session.id),
      turnEndSeq: event.seq,
    }
    for (const waiter of [...this.waiters]) {
      if (waiter.session !== session
        || !isNewer(event.seq, waiter.afterTurnEndSeq)) continue
      this.settle(
        waiter,
        isCurrent(waiter.isSessionCurrent)
          ? { kind: 'changed', ...notification }
          : { kind: 'session_unavailable' },
      )
    }
  }

  invalidateSession(session: Session): void {
    for (const waiter of [...this.waiters]) {
      if (waiter.session === session) {
        this.settle(waiter, { kind: 'session_unavailable' })
      }
    }
  }

  registerDriverBridge(bridge: GoalBarDriverBridge): () => void {
    this.driverBridge = bridge
    let registered = true
    return () => {
      if (!registered) return
      registered = false
      if (this.driverBridge === bridge) this.driverBridge = undefined
    }
  }

  activateAndEvaluate(
    capture: GoalBarSessionCapture,
  ): Promise<GoalBarDriverActionReceipt> {
    return this.invokeDriver('activateAndEvaluate', capture)
  }

  cancelQueued(
    capture: GoalBarSessionCapture,
  ): Promise<GoalBarDriverActionReceipt> {
    return this.invokeDriver('cancelQueued', capture)
  }

  private waitForTurnEnd(
    service: WatchServiceState,
    session: Session,
    afterTurnEndSeq: number | null,
    options: GoalBarTurnEndWaitOptions,
  ): Promise<GoalBarTurnEndWaitReceipt> {
    if (service.disposed) {
      return Promise.resolve({ kind: 'service_disposed' })
    }
    if (options.signal.aborted) return Promise.resolve({ kind: 'aborted' })
    if (!isCurrent(options.isSessionCurrent)) {
      return Promise.resolve({ kind: 'session_unavailable' })
    }

    const immediate = latestCommittedTurnEndSeq(session)
    if (immediate !== null && isNewer(immediate, afterTurnEndSeq)) {
      return Promise.resolve({
        kind: 'changed',
        sessionId: String(session.id),
        turnEndSeq: immediate,
      })
    }

    return new Promise(resolve => {
      const timeoutMs = Number.isSafeInteger(options.timeoutMs)
        && options.timeoutMs >= 0
        ? options.timeoutMs
        : 0
      let waiter: PendingWaiter
      const onAbort = (): void => {
        this.settle(waiter, { kind: 'aborted' })
      }
      const timer = setTimeout(() => {
        this.settle(
          waiter,
          isCurrent(options.isSessionCurrent)
            ? { kind: 'timeout', turnEndSeq: afterTurnEndSeq }
            : { kind: 'session_unavailable' },
        )
      }, timeoutMs)
      waiter = {
        service,
        session,
        afterTurnEndSeq,
        isSessionCurrent: options.isSessionCurrent,
        resolve,
        signal: options.signal,
        onAbort,
        timer,
        settled: false,
      }
      this.waiters.add(waiter)
      options.signal.addEventListener('abort', onAbort, { once: true })

      // Close the check/subscribe race without storing a cursor in the Host.
      if (service.disposed) {
        this.settle(waiter, { kind: 'service_disposed' })
        return
      }
      if (options.signal.aborted) {
        this.settle(waiter, { kind: 'aborted' })
        return
      }
      if (!isCurrent(options.isSessionCurrent)) {
        this.settle(waiter, { kind: 'session_unavailable' })
        return
      }
      const rechecked = latestCommittedTurnEndSeq(session)
      if (rechecked !== null && isNewer(rechecked, afterTurnEndSeq)) {
        this.settle(waiter, {
          kind: 'changed',
          sessionId: String(session.id),
          turnEndSeq: rechecked,
        })
      }
    })
  }

  private settle(
    waiter: PendingWaiter,
    receipt: GoalBarTurnEndWaitReceipt,
  ): void {
    if (waiter.settled) return
    waiter.settled = true
    this.waiters.delete(waiter)
    clearTimeout(waiter.timer)
    waiter.signal.removeEventListener('abort', waiter.onAbort)
    waiter.resolve(receipt)
  }

  private async invokeDriver(
    operation: keyof GoalBarDriverBridge,
    capture: GoalBarSessionCapture,
  ): Promise<GoalBarDriverActionReceipt> {
    if (capture.agent.session !== capture.session) {
      return { kind: 'unavailable', reason: 'session_unavailable' }
    }
    const bridge = this.driverBridge
    if (bridge === undefined) {
      return { kind: 'unavailable', reason: 'driver_unavailable' }
    }
    try {
      return await bridge[operation](capture)
    } catch {
      return { kind: 'unavailable', reason: 'driver_unavailable' }
    }
  }
}

export const goalBarCoordinator = new GoalBarCoordinator()

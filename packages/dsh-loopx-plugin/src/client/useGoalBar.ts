import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  GoalBarActionRejectionCode,
  GoalBarClientFaultCode,
  GoalBarReadFaultCode,
  GoalBarSnapshotV1,
} from '../goalbar/protocol.ts'
import type { GoalBarRpc } from './rpc.ts'
import type { GoalBarWatchAnchorV1 } from './rpc.ts'

export type GoalBarAction = 'start' | 'pause'

export type GoalBarUiErrorCode =
  | GoalBarReadFaultCode
  | GoalBarClientFaultCode
  | GoalBarActionRejectionCode
  | 'operation_result_unknown'
  | 'driver_sync_failed'
  | 'post_read_failed'

export type GoalBarConnectionResetSubscriber = (
  listener: () => void,
) => () => void

export interface UseGoalBarOptions {
  /** Exact DSH Session identity supplied by the slot's inject(sessionId) face. */
  readonly rpcSessionId: string
  readonly rpc: GoalBarRpc
  readonly subscribeConnectionReset?: GoalBarConnectionResetSubscriber | undefined
}

export interface UseGoalBarResult {
  readonly snapshot: GoalBarSnapshotV1 | null
  readonly errorCode: GoalBarUiErrorCode | null
  readonly syncing: boolean
  readonly pendingAction: boolean
  readonly action: GoalBarAction | null
  readonly actionDisabled: boolean
  readonly refresh: () => void
  readonly requestAction: (action: GoalBarAction) => void
}

interface GoalBarLocalState {
  readonly snapshot: GoalBarSnapshotV1 | null
  readonly errorCode: GoalBarUiErrorCode | null
  readonly syncing: boolean
  readonly pendingAction: boolean
}

const INITIAL_STATE: GoalBarLocalState = {
  snapshot: null,
  errorCode: null,
  syncing: true,
  pendingAction: false,
}

interface SessionGeneration {
  readonly value: number
  readonly controller: AbortController
}

/**
 * Own the read/watch/action lifecycle for exactly one mounted component.
 * There is intentionally no shared client cache: every instance has its own
 * generation, cursor, AbortController, and same-frame action fence.
 */
export function useGoalBar({
  rpcSessionId,
  rpc,
  subscribeConnectionReset,
}: UseGoalBarOptions): UseGoalBarResult {
  const [state, setReactState] = useState<GoalBarLocalState>(INITIAL_STATE)
  const stateRef = useRef<GoalBarLocalState>(INITIAL_STATE)
  const activeSessionRef = useRef(rpcSessionId)
  const generationRef = useRef(0)
  const controllerRef = useRef<AbortController | null>(null)
  const anchorRef = useRef<GoalBarWatchAnchorV1 | null>(null)
  const actionGuardRef = useRef(false)

  const commit = useCallback((
    update: GoalBarLocalState | ((current: GoalBarLocalState) => GoalBarLocalState),
  ) => {
    const next = typeof update === 'function' ? update(stateRef.current) : update
    stateRef.current = next
    setReactState(next)
  }, [])

  const replaceGeneration = useCallback((): SessionGeneration => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    const value = generationRef.current + 1
    generationRef.current = value
    controllerRef.current = controller
    return { value, controller }
  }, [])

  const isCurrent = useCallback((generation: SessionGeneration): boolean => (
    !generation.controller.signal.aborted
    && generationRef.current === generation.value
    && controllerRef.current === generation.controller
    && activeSessionRef.current === rpcSessionId
  ), [rpcSessionId])

  const applySyncFault = useCallback((code: GoalBarUiErrorCode) => {
    commit(current => ({
      snapshot: current.snapshot?.sessionId === rpcSessionId
        ? current.snapshot
        : null,
      errorCode: code,
      syncing: false,
      pendingAction: false,
    }))
  }, [commit, rpcSessionId])

  const runReadWatchCycle = useCallback(async (
    generation: SessionGeneration,
    initialAnchor: GoalBarWatchAnchorV1 | null,
    readFirst: boolean,
  ): Promise<void> => {
    let anchor = initialAnchor
    let shouldRead = readFirst

    while (isCurrent(generation)) {
      if (shouldRead) {
        const read = await rpc.read(rpcSessionId, generation.controller.signal)
        if (!isCurrent(generation)) return

        if (!read.ok) {
          applySyncFault(read.code)
          return
        }

        const result = read.response.result
        const snapshot = result.kind === 'present' ? result.snapshot : null
        anchor = {
          afterSessionEventSeq: result.baseSessionEventSeq,
          sourceRevision: result.sourceRevision,
          expected: snapshot === null
            ? null
            : { goalId: snapshot.goalId, loopxAgentId: snapshot.loopxAgentId },
          agentStatus: snapshot?.agentStatus ?? null,
        }
        anchorRef.current = anchor

        if (result.kind === 'present') {
          actionGuardRef.current = false
          commit({
            snapshot: result.snapshot,
            errorCode: null,
            syncing: false,
            pendingAction: false,
          })
        } else if (result.kind === 'hidden') {
          actionGuardRef.current = false
          commit({
            snapshot: null,
            errorCode: null,
            syncing: false,
            pendingAction: false,
          })
        } else {
          applySyncFault(result.code)
          return
        }
        shouldRead = false
        if (!isCurrent(generation)) return
      }

      if (anchor === null) return

      const watch = await rpc.watch(
        rpcSessionId,
        anchor,
        generation.controller.signal,
      )
      if (!isCurrent(generation)) return
      if (!watch.ok) {
        applySyncFault(watch.code)
        return
      }

      const result = watch.response.result
      if (result.kind === 'fault') {
        applySyncFault(result.code)
        return
      }
      if (result.kind === 'timeout') {
        // A timeout is a normal lease boundary: renew immediately, without read.
        anchor = { ...anchor, afterSessionEventSeq: result.sessionEventSeq }
        anchorRef.current = anchor
        continue
      }
      if (result.kind === 'runtime_changed') {
        anchor = {
          ...anchor,
          afterSessionEventSeq: result.sessionEventSeq,
          agentStatus: result.agentStatus,
        }
        anchorRef.current = anchor
        commit(current => {
          const snapshot = current.snapshot
          return snapshot?.sessionId === rpcSessionId
            ? {
                ...current,
                snapshot: { ...snapshot, agentStatus: result.agentStatus },
              }
            : current
        })
        continue
      }

      anchor = { ...anchor, afterSessionEventSeq: result.sessionEventSeq }
      anchorRef.current = anchor
      shouldRead = true
      commit(current => ({ ...current, syncing: true }))
    }
  }, [applySyncFault, commit, isCurrent, rpc, rpcSessionId])

  const refresh = useCallback(() => {
    if (activeSessionRef.current !== rpcSessionId) return
    actionGuardRef.current = false
    const generation = replaceGeneration()
    commit(current => ({
      snapshot: current.snapshot?.sessionId === rpcSessionId
        ? current.snapshot
        : null,
      errorCode: current.errorCode,
      syncing: true,
      pendingAction: false,
    }))
    void runReadWatchCycle(generation, anchorRef.current, true)
  }, [commit, replaceGeneration, rpcSessionId, runReadWatchCycle])

  const requestAction = useCallback((requestedAction: GoalBarAction) => {
    const current = stateRef.current
    const snapshot = current.snapshot
    if (activeSessionRef.current !== rpcSessionId
      || snapshot === null
      || snapshot.sessionId !== rpcSessionId
      || current.errorCode !== null
      || current.syncing
      || current.pendingAction
      || actionGuardRef.current) return

    const availableAction: GoalBarAction = snapshot.goalActivation === 'active'
      ? 'pause'
      : 'start'
    if (requestedAction !== availableAction
      || (requestedAction === 'start' && snapshot.agentStatus === 'running')) return

    // This ref closes the pre-render/same-frame duplicate-click window.
    actionGuardRef.current = true
    const generation = replaceGeneration()
    commit({
      snapshot,
      errorCode: null,
      syncing: false,
      pendingAction: true,
    })

    void (async () => {
      const expected = {
        goalId: snapshot.goalId,
        loopxAgentId: snapshot.loopxAgentId,
      }
      const action = await rpc[requestedAction](
        rpcSessionId,
        expected,
        generation.controller.signal,
      )
      if (!isCurrent(generation)) return

      if (!action.ok) {
        applySyncFault(action.code)
        return
      }

      const result = action.response.result
      if (result.kind === 'succeeded') {
        const anchor = {
          afterSessionEventSeq: result.baseSessionEventSeq,
          sourceRevision: result.sourceRevision,
          expected: {
            goalId: result.snapshot.goalId,
            loopxAgentId: result.snapshot.loopxAgentId,
          },
          agentStatus: result.snapshot.agentStatus,
        } satisfies GoalBarWatchAnchorV1
        anchorRef.current = anchor
        commit({
          snapshot: result.snapshot,
          errorCode: null,
          syncing: false,
          pendingAction: false,
        })
        actionGuardRef.current = false
        void runReadWatchCycle(
          generation,
          anchor,
          false,
        )
        return
      }

      if (result.kind === 'applied_with_warning'
        && result.code === 'driver_sync_failed') {
        anchorRef.current = {
          afterSessionEventSeq: result.baseSessionEventSeq,
          sourceRevision: result.sourceRevision,
          expected: {
            goalId: result.snapshot.goalId,
            loopxAgentId: result.snapshot.loopxAgentId,
          },
          agentStatus: result.snapshot.agentStatus,
        }
        commit({
          snapshot: result.snapshot,
          errorCode: result.code,
          syncing: false,
          pendingAction: false,
        })
        return
      }

      commit({
        snapshot,
        errorCode: result.code,
        syncing: false,
        pendingAction: false,
      })
      // Rejections and uncertain outcomes intentionally retain the guard.
      // Only explicit Refresh (or a Session generation replacement) unlocks it.
    })()
  }, [
    applySyncFault,
    commit,
    isCurrent,
    replaceGeneration,
    rpc,
    rpcSessionId,
    runReadWatchCycle,
  ])

  useEffect(() => {
    activeSessionRef.current = rpcSessionId
    anchorRef.current = null
    actionGuardRef.current = false
    commit(INITIAL_STATE)
    const generation = replaceGeneration()
    void runReadWatchCycle(generation, null, true)

    return () => {
      generationRef.current += 1
      controllerRef.current?.abort()
      controllerRef.current = null
    }
  }, [commit, replaceGeneration, rpcSessionId, rpc, runReadWatchCycle])

  useEffect(() => subscribeConnectionReset?.(refresh), [
    refresh,
    subscribeConnectionReset,
  ])

  // Hide the previous Session synchronously during a prop switch, before the
  // effect gets a chance to clear component-local state.
  const snapshot = state.snapshot?.sessionId === rpcSessionId
    ? state.snapshot
    : null
  const action: GoalBarAction | null = snapshot === null
    ? null
    : snapshot.goalActivation === 'active'
      ? 'pause'
      : 'start'
  const actionDisabled = action === null
    || state.errorCode !== null
    || state.syncing
    || state.pendingAction
    || (action === 'start' && snapshot?.agentStatus === 'running')

  return {
    snapshot,
    errorCode: snapshot === null ? null : state.errorCode,
    syncing: state.syncing,
    pendingAction: state.pendingAction,
    action,
    actionDisabled,
    refresh,
    requestAction,
  }
}

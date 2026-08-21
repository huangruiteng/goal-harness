import { describe, expect, it } from 'vitest'
import {
  GOALBAR_ACTION_REJECTION_CODES,
  GOALBAR_ENDPOINTS,
  GOALBAR_READ_FAULT_CODES,
  GOALBAR_REQUEST_VERSION,
  GOALBAR_RESPONSE_VERSION,
  decodeGoalBarRequestV1,
  decodeGoalBarResponseV1,
  decodeGoalBarSnapshotV1,
} from '../src/goalbar/protocol.ts'
import type {
  GoalBarRequestV1,
  GoalBarSnapshotV1,
} from '../src/goalbar/protocol.ts'

const sessionId = 'dsh-session-1'
const goalId = 'goal-one'
const loopxAgentId = 'codex-main-control'
const hostilePath = ['', 'sensitive-host', 'project'].join('/')

const snapshot: GoalBarSnapshotV1 = {
  sessionId,
  goalId,
  loopxAgentId,
  goalActivation: 'active',
  agentStatus: 'idle',
  progress: { processed: 2, remaining: 3, total: 5 },
}

function response(
  request: GoalBarRequestV1,
  result: unknown,
): Record<string, unknown> {
  return {
    v: GOALBAR_RESPONSE_VERSION,
    op: request.op,
    sessionId: request.sessionId,
    result,
  }
}

describe('GoalBar request V1', () => {
  it('decodes each endpoint only when endpoint and op agree', () => {
    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.read, {
      v: GOALBAR_REQUEST_VERSION,
      op: 'read',
      sessionId,
    })).toEqual({ v: GOALBAR_REQUEST_VERSION, op: 'read', sessionId })

    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.watch, {
      v: GOALBAR_REQUEST_VERSION,
      op: 'watch',
      sessionId,
      afterTurnEndSeq: null,
    })).toEqual({
      v: GOALBAR_REQUEST_VERSION,
      op: 'watch',
      sessionId,
      afterTurnEndSeq: null,
    })

    for (const op of ['start', 'pause'] as const) {
      expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS[op], {
        v: GOALBAR_REQUEST_VERSION,
        op,
        sessionId,
        expected: { goalId, loopxAgentId },
      })).toEqual({
        v: GOALBAR_REQUEST_VERSION,
        op,
        sessionId,
        expected: { goalId, loopxAgentId },
      })
    }

    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.read, {
      v: GOALBAR_REQUEST_VERSION,
      op: 'watch',
      sessionId,
      afterTurnEndSeq: null,
    })).toBeUndefined()
  })

  it('rejects additive keys, unsafe cursors, and non-public identities', () => {
    const read = { v: GOALBAR_REQUEST_VERSION, op: 'read', sessionId }
    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.read, {
      ...read,
      cwd: hostilePath,
    })).toBeUndefined()

    for (const afterTurnEndSeq of [true, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
      expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.watch, {
        v: GOALBAR_REQUEST_VERSION,
        op: 'watch',
        sessionId,
        afterTurnEndSeq,
      })).toBeUndefined()
    }

    for (const invalidSession of ['', ' session', 'a/b', 'x'.repeat(129)]) {
      expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.read, {
        ...read,
        sessionId: invalidSession,
      })).toBeUndefined()
    }

    const action = {
      v: GOALBAR_REQUEST_VERSION,
      op: 'start',
      sessionId,
      expected: { goalId, loopxAgentId },
    }
    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.start, {
      ...action,
      expected: { ...action.expected, activation: 'stopped' },
    })).toBeUndefined()
    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.start, {
      ...action,
      expected: { goalId: ' goal-with-leading-space', loopxAgentId },
    })).toBeUndefined()
    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.start, {
      ...action,
      expected: { goalId, loopxAgentId: 'Agent With Spaces' },
    })).toBeUndefined()

    expect(decodeGoalBarRequestV1(GOALBAR_ENDPOINTS.start, {
      ...action,
      expected: { goalId: '目标 / phase:one', loopxAgentId },
    })).toEqual({
      ...action,
      expected: { goalId: '目标 / phase:one', loopxAgentId },
    })
  })
})

describe('GoalBar snapshot V1', () => {
  it('returns a closed, allowlisted snapshot', () => {
    expect(decodeGoalBarSnapshotV1(snapshot, {
      sessionId,
      binding: { goalId, loopxAgentId },
    })).toEqual(snapshot)
  })

  it('rejects hostile counters, inconsistent totals, and unknown keys', () => {
    for (const processed of [true, -1, 0.5, Number.MAX_SAFE_INTEGER + 1]) {
      expect(decodeGoalBarSnapshotV1({
        ...snapshot,
        progress: { ...snapshot.progress, processed },
      })).toBeUndefined()
    }
    expect(decodeGoalBarSnapshotV1({
      ...snapshot,
      progress: { processed: 2, remaining: 2, total: 5 },
    })).toBeUndefined()
    expect(decodeGoalBarSnapshotV1({
      ...snapshot,
      progress: {
        processed: Number.MAX_SAFE_INTEGER,
        remaining: 1,
        total: Number.MAX_SAFE_INTEGER,
      },
    })).toBeUndefined()
    expect(decodeGoalBarSnapshotV1({
      ...snapshot,
      rawPayload: { path: hostilePath, text: 'RAW_TODO_TEXT_SENTINEL' },
    })).toBeUndefined()
    expect(decodeGoalBarSnapshotV1({
      ...snapshot,
      progress: { ...snapshot.progress, note: 'secret todo' },
    })).toBeUndefined()
  })
})

describe('GoalBar response V1', () => {
  const readRequest = {
    v: GOALBAR_REQUEST_VERSION,
    op: 'read',
    sessionId,
  } as const
  const watchRequest = {
    v: GOALBAR_REQUEST_VERSION,
    op: 'watch',
    sessionId,
    afterTurnEndSeq: 7,
  } as const
  const actionRequest = {
    v: GOALBAR_REQUEST_VERSION,
    op: 'pause',
    sessionId,
    expected: { goalId, loopxAgentId },
  } as const

  it('decodes all closed read branches and fixed fault codes', () => {
    expect(decodeGoalBarResponseV1(readRequest, response(readRequest, {
      kind: 'hidden',
      reason: 'binding_missing',
      baseTurnEndSeq: null,
    }))?.result).toEqual({
      kind: 'hidden',
      reason: 'binding_missing',
      baseTurnEndSeq: null,
    })
    expect(decodeGoalBarResponseV1(readRequest, response(readRequest, {
      kind: 'present', snapshot, baseTurnEndSeq: 12,
    }))?.result).toEqual({ kind: 'present', snapshot, baseTurnEndSeq: 12 })

    for (const code of GOALBAR_READ_FAULT_CODES) {
      expect(decodeGoalBarResponseV1(readRequest, response(readRequest, {
        kind: 'fault', code, baseTurnEndSeq: 12,
      }))?.result).toEqual({ kind: 'fault', code, baseTurnEndSeq: 12 })
    }
    expect(decodeGoalBarResponseV1(readRequest, response(readRequest, {
      kind: 'fault',
      code: 'raw_exception',
      baseTurnEndSeq: 12,
      message: `${hostilePath}: RAW_ERROR_SENTINEL`,
    }))).toBeUndefined()
  })

  it('requires exact response echoes and closes every response layer', () => {
    const present = response(readRequest, {
      kind: 'present', snapshot, baseTurnEndSeq: 0,
    })
    expect(decodeGoalBarResponseV1(readRequest, {
      ...present,
      sessionId: 'another-session',
    })).toBeUndefined()
    expect(decodeGoalBarResponseV1(readRequest, {
      ...present,
      op: 'watch',
    })).toBeUndefined()
    expect(decodeGoalBarResponseV1(readRequest, {
      ...present,
      debug: 'secret',
    })).toBeUndefined()
    expect(decodeGoalBarResponseV1(readRequest, response(readRequest, {
      kind: 'present', snapshot, baseTurnEndSeq: 0, stdout: 'secret',
    }))).toBeUndefined()
  })

  it('requires changed cursors to advance and timeout cursors to echo', () => {
    expect(decodeGoalBarResponseV1(watchRequest, response(watchRequest, {
      kind: 'changed', turnEndSeq: 8,
    }))?.result).toEqual({ kind: 'changed', turnEndSeq: 8 })
    expect(decodeGoalBarResponseV1(watchRequest, response(watchRequest, {
      kind: 'changed', turnEndSeq: 7,
    }))).toBeUndefined()
    expect(decodeGoalBarResponseV1(watchRequest, response(watchRequest, {
      kind: 'timeout', turnEndSeq: 6,
    }))).toBeUndefined()
    expect(decodeGoalBarResponseV1(watchRequest, response(watchRequest, {
      kind: 'timeout', turnEndSeq: 7,
    }))?.result).toEqual({ kind: 'timeout', turnEndSeq: 7 })
    expect(decodeGoalBarResponseV1(watchRequest, response(watchRequest, {
      kind: 'changed', turnEndSeq: true,
    }))).toBeUndefined()
  })

  it('validates action snapshots against the requested exact pair', () => {
    expect(decodeGoalBarResponseV1(actionRequest, response(actionRequest, {
      kind: 'succeeded', snapshot, baseTurnEndSeq: 12,
    }))?.result).toEqual({ kind: 'succeeded', snapshot, baseTurnEndSeq: 12 })

    expect(decodeGoalBarResponseV1(actionRequest, response(actionRequest, {
      kind: 'succeeded',
      snapshot: { ...snapshot, goalId: 'new-binding' },
      baseTurnEndSeq: 12,
    }))).toBeUndefined()

    for (const code of GOALBAR_ACTION_REJECTION_CODES) {
      expect(decodeGoalBarResponseV1(actionRequest, response(actionRequest, {
        kind: 'rejected', code,
      }))?.result).toEqual({ kind: 'rejected', code })
    }
    expect(decodeGoalBarResponseV1(actionRequest, response(actionRequest, {
      kind: 'unknown', code: 'operation_result_unknown', snapshot,
    }))).toBeUndefined()
    expect(decodeGoalBarResponseV1(actionRequest, response(actionRequest, {
      kind: 'applied_with_warning',
      code: 'driver_sync_failed',
      snapshot,
      baseTurnEndSeq: 13,
    }))?.result).toEqual({
      kind: 'applied_with_warning',
      code: 'driver_sync_failed',
      snapshot,
      baseTurnEndSeq: 13,
    })
    expect(decodeGoalBarResponseV1(actionRequest, response(actionRequest, {
      kind: 'applied_with_warning', code: 'post_read_failed',
    }))?.result).toEqual({
      kind: 'applied_with_warning', code: 'post_read_failed',
    })
  })
})

export const GOALBAR_REQUEST_VERSION = 'loopx_goalbar_request_v1' as const
export const GOALBAR_RESPONSE_VERSION = 'loopx_goalbar_response_v1' as const

export const GOALBAR_ENDPOINTS = Object.freeze({
  read: 'goalbar/read',
  watch: 'goalbar/watch',
  start: 'goalbar/start',
  pause: 'goalbar/pause',
} as const)

export const GOALBAR_READ_FAULT_CODES = Object.freeze([
  'session_unavailable',
  'cli_unavailable',
  'binding_read_failed',
  'activation_read_failed',
  'todo_read_failed',
  'protocol_mismatch',
] as const)

export const GOALBAR_ACTION_REJECTION_CODES = Object.freeze([
  'binding_mismatch',
  'binding_validation_failed',
  'not_actionable',
  'action_in_flight',
] as const)

export const GOALBAR_CLIENT_FAULT_CODES = Object.freeze([
  'transport_error',
  'protocol_error',
] as const)

export type GoalBarOpV1 = keyof typeof GOALBAR_ENDPOINTS
export type GoalBarEndpointV1 = (typeof GOALBAR_ENDPOINTS)[GoalBarOpV1]
export type GoalBarReadFaultCode = (typeof GOALBAR_READ_FAULT_CODES)[number]
export type GoalBarActionRejectionCode =
  (typeof GOALBAR_ACTION_REJECTION_CODES)[number]
export type GoalBarClientFaultCode = (typeof GOALBAR_CLIENT_FAULT_CODES)[number]
export type GoalBarActivationV1 = 'active' | 'stopped'
export type GoalBarAgentStatusV1 = 'idle' | 'running'

export interface GoalBarProgressV1 {
  readonly processed: number
  readonly remaining: number
  readonly total: number
}

export interface GoalBarSnapshotV1 {
  readonly sessionId: string
  readonly goalId: string
  readonly loopxAgentId: string
  readonly goalActivation: GoalBarActivationV1
  readonly agentStatus: GoalBarAgentStatusV1
  readonly progress: GoalBarProgressV1
}

export interface GoalBarExpectedBindingV1 {
  readonly goalId: string
  readonly loopxAgentId: string
}

export type GoalBarRequestV1 =
  | {
      readonly v: typeof GOALBAR_REQUEST_VERSION
      readonly op: 'read'
      readonly sessionId: string
    }
  | {
      readonly v: typeof GOALBAR_REQUEST_VERSION
      readonly op: 'watch'
      readonly sessionId: string
      readonly afterTurnEndSeq: number | null
    }
  | {
      readonly v: typeof GOALBAR_REQUEST_VERSION
      readonly op: 'start'
      readonly sessionId: string
      readonly expected: GoalBarExpectedBindingV1
    }
  | {
      readonly v: typeof GOALBAR_REQUEST_VERSION
      readonly op: 'pause'
      readonly sessionId: string
      readonly expected: GoalBarExpectedBindingV1
    }

export type GoalBarReadResultV1 =
  | {
      readonly kind: 'hidden'
      readonly reason: 'binding_missing' | 'binding_ambiguous'
      readonly baseTurnEndSeq: number | null
    }
  | {
      readonly kind: 'present'
      readonly snapshot: GoalBarSnapshotV1
      readonly baseTurnEndSeq: number | null
    }
  | {
      readonly kind: 'fault'
      readonly code: GoalBarReadFaultCode
      readonly baseTurnEndSeq: number | null
    }

export type GoalBarWatchResultV1 =
  | { readonly kind: 'changed'; readonly turnEndSeq: number }
  | { readonly kind: 'timeout'; readonly turnEndSeq: number | null }
  | { readonly kind: 'fault'; readonly code: 'session_unavailable' }

export type GoalBarActionResultV1 =
  | {
      readonly kind: 'succeeded'
      readonly snapshot: GoalBarSnapshotV1
      readonly baseTurnEndSeq: number | null
    }
  | {
      readonly kind: 'rejected'
      readonly code: GoalBarActionRejectionCode
    }
  | { readonly kind: 'unknown'; readonly code: 'operation_result_unknown' }
  | {
      readonly kind: 'applied_with_warning'
      readonly code: 'driver_sync_failed'
      readonly snapshot: GoalBarSnapshotV1
      readonly baseTurnEndSeq: number | null
    }
  | {
      readonly kind: 'applied_with_warning'
      readonly code: 'post_read_failed'
    }

export type GoalBarResponseV1 =
  | {
      readonly v: typeof GOALBAR_RESPONSE_VERSION
      readonly op: 'read'
      readonly sessionId: string
      readonly result: GoalBarReadResultV1
    }
  | {
      readonly v: typeof GOALBAR_RESPONSE_VERSION
      readonly op: 'watch'
      readonly sessionId: string
      readonly result: GoalBarWatchResultV1
    }
  | {
      readonly v: typeof GOALBAR_RESPONSE_VERSION
      readonly op: 'start'
      readonly sessionId: string
      readonly result: GoalBarActionResultV1
    }
  | {
      readonly v: typeof GOALBAR_RESPONSE_VERSION
      readonly op: 'pause'
      readonly sessionId: string
      readonly result: GoalBarActionResultV1
    }

export type GoalBarResponseFor<T extends GoalBarRequestV1> =
  T extends { readonly op: 'read' }
    ? Extract<GoalBarResponseV1, { readonly op: 'read' }>
    : T extends { readonly op: 'watch' }
      ? Extract<GoalBarResponseV1, { readonly op: 'watch' }>
      : T extends { readonly op: infer TOp extends 'start' | 'pause' }
        ? Extract<GoalBarResponseV1, { readonly op: TOp }>
        : never

const LOOPX_AGENT_ID_PATTERN = /^[a-z][a-z0-9_.:@-]{0,79}$/u
const GOAL_ID_MAX_LENGTH = 512

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function exactRecord(
  value: unknown,
  expectedKeys: readonly string[],
): Record<string, unknown> | undefined {
  const candidate = record(value)
  if (candidate === undefined) return undefined
  const keys = Reflect.ownKeys(candidate)
  if (keys.some(key => typeof key !== 'string') || keys.length !== expectedKeys.length) {
    return undefined
  }
  const allowed = new Set(expectedKeys)
  return keys.every(key => typeof key === 'string' && allowed.has(key))
    ? candidate
    : undefined
}

function isOneOf<T extends string>(
  value: unknown,
  choices: readonly T[],
): value is T {
  return typeof value === 'string' && choices.includes(value as T)
}

function isSequence(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function isCursor(value: unknown): value is number | null {
  return value === null || isSequence(value)
}

export function isGoalBarSessionId(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && [...value].length <= 128
    && value.trim() === value
    && !/[\s\u0000-\u001f/\\'"]/u.test(value)
}

export function isGoalBarGoalId(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && [...value].length <= GOAL_ID_MAX_LENGTH
    && value.trim() === value
    && !/[\u0000-\u001f\u007f]/u.test(value)
}

export function isGoalBarAgentId(value: unknown): value is string {
  return typeof value === 'string' && LOOPX_AGENT_ID_PATTERN.test(value)
}

export function endpointForGoalBarOp(op: GoalBarOpV1): GoalBarEndpointV1 {
  return GOALBAR_ENDPOINTS[op]
}

export function decodeGoalBarRequestV1(
  endpoint: string,
  value: unknown,
): GoalBarRequestV1 | undefined {
  const op = (Object.entries(GOALBAR_ENDPOINTS) as Array<
    [GoalBarOpV1, GoalBarEndpointV1]
  >).find(([, candidate]) => candidate === endpoint)?.[0]
  if (op === undefined) return undefined

  if (op === 'read') {
    const input = exactRecord(value, ['v', 'op', 'sessionId'])
    return input?.v === GOALBAR_REQUEST_VERSION
      && input.op === op
      && isGoalBarSessionId(input.sessionId)
      ? { v: GOALBAR_REQUEST_VERSION, op, sessionId: input.sessionId }
      : undefined
  }

  if (op === 'watch') {
    const input = exactRecord(value, ['v', 'op', 'sessionId', 'afterTurnEndSeq'])
    return input?.v === GOALBAR_REQUEST_VERSION
      && input.op === op
      && isGoalBarSessionId(input.sessionId)
      && isCursor(input.afterTurnEndSeq)
      ? {
          v: GOALBAR_REQUEST_VERSION,
          op,
          sessionId: input.sessionId,
          afterTurnEndSeq: input.afterTurnEndSeq,
        }
      : undefined
  }

  const input = exactRecord(value, ['v', 'op', 'sessionId', 'expected'])
  const expected = exactRecord(input?.expected, ['goalId', 'loopxAgentId'])
  return input?.v === GOALBAR_REQUEST_VERSION
    && input.op === op
    && isGoalBarSessionId(input.sessionId)
    && isGoalBarGoalId(expected?.goalId)
    && isGoalBarAgentId(expected.loopxAgentId)
    ? {
        v: GOALBAR_REQUEST_VERSION,
        op,
        sessionId: input.sessionId,
        expected: {
          goalId: expected.goalId,
          loopxAgentId: expected.loopxAgentId,
        },
      }
    : undefined
}

export function decodeGoalBarSnapshotV1(
  value: unknown,
  expected: {
    readonly sessionId?: string | undefined
    readonly binding?: GoalBarExpectedBindingV1 | undefined
  } = {},
): GoalBarSnapshotV1 | undefined {
  const input = exactRecord(value, [
    'sessionId',
    'goalId',
    'loopxAgentId',
    'goalActivation',
    'agentStatus',
    'progress',
  ])
  const progress = exactRecord(input?.progress, ['processed', 'remaining', 'total'])
  if (!isGoalBarSessionId(input?.sessionId)
    || !isGoalBarGoalId(input.goalId)
    || !isGoalBarAgentId(input.loopxAgentId)
    || !isOneOf(input.goalActivation, ['active', 'stopped'] as const)
    || !isOneOf(input.agentStatus, ['idle', 'running'] as const)
    || !isSequence(progress?.processed)
    || !isSequence(progress.remaining)
    || !isSequence(progress.total)
    || !Number.isSafeInteger(progress.processed + progress.remaining)
    || progress.processed + progress.remaining !== progress.total
    || (expected.sessionId !== undefined && input.sessionId !== expected.sessionId)
    || (expected.binding !== undefined
      && (input.goalId !== expected.binding.goalId
        || input.loopxAgentId !== expected.binding.loopxAgentId))) {
    return undefined
  }
  return {
    sessionId: input.sessionId,
    goalId: input.goalId,
    loopxAgentId: input.loopxAgentId,
    goalActivation: input.goalActivation,
    agentStatus: input.agentStatus,
    progress: {
      processed: progress.processed,
      remaining: progress.remaining,
      total: progress.total,
    },
  }
}

function decodeReadResult(
  value: unknown,
  sessionId: string,
): GoalBarReadResultV1 | undefined {
  const candidate = record(value)
  if (candidate?.kind === 'hidden') {
    const input = exactRecord(value, ['kind', 'reason', 'baseTurnEndSeq'])
    return input !== undefined
      && isOneOf(input.reason, ['binding_missing', 'binding_ambiguous'] as const)
      && isCursor(input.baseTurnEndSeq)
      ? {
          kind: 'hidden',
          reason: input.reason,
          baseTurnEndSeq: input.baseTurnEndSeq,
        }
      : undefined
  }
  if (candidate?.kind === 'present') {
    const input = exactRecord(value, ['kind', 'snapshot', 'baseTurnEndSeq'])
    const snapshot = decodeGoalBarSnapshotV1(input?.snapshot, { sessionId })
    return input !== undefined && snapshot !== undefined && isCursor(input.baseTurnEndSeq)
      ? { kind: 'present', snapshot, baseTurnEndSeq: input.baseTurnEndSeq }
      : undefined
  }
  if (candidate?.kind === 'fault') {
    const input = exactRecord(value, ['kind', 'code', 'baseTurnEndSeq'])
    return input !== undefined
      && isOneOf(input.code, GOALBAR_READ_FAULT_CODES)
      && isCursor(input.baseTurnEndSeq)
      ? { kind: 'fault', code: input.code, baseTurnEndSeq: input.baseTurnEndSeq }
      : undefined
  }
  return undefined
}

function decodeWatchResult(
  value: unknown,
  afterTurnEndSeq: number | null,
): GoalBarWatchResultV1 | undefined {
  const candidate = record(value)
  if (candidate?.kind === 'changed') {
    const input = exactRecord(value, ['kind', 'turnEndSeq'])
    return input !== undefined
      && isSequence(input.turnEndSeq)
      && (afterTurnEndSeq === null || input.turnEndSeq > afterTurnEndSeq)
      ? { kind: 'changed', turnEndSeq: input.turnEndSeq }
      : undefined
  }
  if (candidate?.kind === 'timeout') {
    const input = exactRecord(value, ['kind', 'turnEndSeq'])
    return input !== undefined && input.turnEndSeq === afterTurnEndSeq
      ? { kind: 'timeout', turnEndSeq: afterTurnEndSeq }
      : undefined
  }
  if (candidate?.kind === 'fault') {
    const input = exactRecord(value, ['kind', 'code'])
    return input?.code === 'session_unavailable'
      ? { kind: 'fault', code: 'session_unavailable' }
      : undefined
  }
  return undefined
}

function decodeActionResult(
  value: unknown,
  sessionId: string,
  binding: GoalBarExpectedBindingV1,
): GoalBarActionResultV1 | undefined {
  const candidate = record(value)
  if (candidate?.kind === 'succeeded') {
    const input = exactRecord(value, ['kind', 'snapshot', 'baseTurnEndSeq'])
    const snapshot = decodeGoalBarSnapshotV1(input?.snapshot, { sessionId, binding })
    return input !== undefined && snapshot !== undefined && isCursor(input.baseTurnEndSeq)
      ? { kind: 'succeeded', snapshot, baseTurnEndSeq: input.baseTurnEndSeq }
      : undefined
  }
  if (candidate?.kind === 'rejected') {
    const input = exactRecord(value, ['kind', 'code'])
    return input !== undefined && isOneOf(input.code, GOALBAR_ACTION_REJECTION_CODES)
      ? { kind: 'rejected', code: input.code }
      : undefined
  }
  if (candidate?.kind === 'unknown') {
    const input = exactRecord(value, ['kind', 'code'])
    return input?.code === 'operation_result_unknown'
      ? { kind: 'unknown', code: 'operation_result_unknown' }
      : undefined
  }
  if (candidate?.kind === 'applied_with_warning') {
    if (candidate.code === 'post_read_failed') {
      const input = exactRecord(value, ['kind', 'code'])
      return input?.code === 'post_read_failed'
        ? { kind: 'applied_with_warning', code: 'post_read_failed' }
        : undefined
    }
    const input = exactRecord(value, ['kind', 'code', 'snapshot', 'baseTurnEndSeq'])
    const snapshot = decodeGoalBarSnapshotV1(input?.snapshot, { sessionId, binding })
    return input?.code === 'driver_sync_failed'
      && snapshot !== undefined
      && isCursor(input.baseTurnEndSeq)
      ? {
          kind: 'applied_with_warning',
          code: 'driver_sync_failed',
          snapshot,
          baseTurnEndSeq: input.baseTurnEndSeq,
        }
      : undefined
  }
  return undefined
}

export function decodeGoalBarResponseV1<T extends GoalBarRequestV1>(
  request: T,
  value: unknown,
): GoalBarResponseFor<T> | undefined {
  const input = exactRecord(value, ['v', 'op', 'sessionId', 'result'])
  if (input?.v !== GOALBAR_RESPONSE_VERSION
    || input.op !== request.op
    || input.sessionId !== request.sessionId) return undefined

  let result: GoalBarReadResultV1 | GoalBarWatchResultV1 | GoalBarActionResultV1 | undefined
  if (request.op === 'read') {
    result = decodeReadResult(input.result, request.sessionId)
  } else if (request.op === 'watch') {
    result = decodeWatchResult(input.result, request.afterTurnEndSeq)
  } else {
    result = decodeActionResult(input.result, request.sessionId, request.expected)
  }
  return result === undefined
    ? undefined
    : {
        v: GOALBAR_RESPONSE_VERSION,
        op: request.op,
        sessionId: request.sessionId,
        result,
      } as GoalBarResponseFor<T>
}

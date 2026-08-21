import {
  LoopXCliError,
  runFile,
  runJsonCommand,
} from '../cli.ts'
import type {
  FileRunner,
  LoopXCommand,
} from '../cli.ts'
import {
  isGoalBarAgentId,
  isGoalBarGoalId,
  isGoalBarSessionId,
} from './protocol.ts'
import type {
  GoalBarActivationV1,
  GoalBarAgentStatusV1,
  GoalBarProgressV1,
  GoalBarReadFaultCode,
  GoalBarSnapshotV1,
} from './protocol.ts'

export const GOALBAR_HOST_SURFACE = 'deepseek-harness-native' as const
export const GOALBAR_PROJECT_REGISTRY = '.loopx/registry.json' as const

const BINDING_SCHEMA = 'loopx_thread_agent_binding_resolution_v0'
const ACTIVATION_TRANSITION_SCHEMA = 'loopx_goal_activation_transition_v1'
const ACTIVATION_READBACK_SCHEMA = 'loopx_goal_activation_readback_v1'
const TODO_PROJECTION_SCHEMA = 'agent_lane_todo_list_projection_v0'
const TODO_PROJECTION_VIEW = 'explicit_limit_cold_path'
const READ_ATTEMPTS = 3

export interface GoalBarCliReadOptions {
  readonly command: LoopXCommand
  readonly cwd: string
  readonly runner?: FileRunner | undefined
  readonly signal?: AbortSignal | undefined
  readonly env?: NodeJS.ProcessEnv | undefined
  readonly retryDelaysMs?: readonly number[] | undefined
}

export interface GoalBarReadModelOptions extends GoalBarCliReadOptions {
  readonly sessionId: string
  readonly agentStatus: GoalBarAgentStatusV1
}

export type DecodedBindingResolutionV0 =
  | { readonly kind: 'missing' }
  | {
      readonly kind: 'bound'
      readonly goalId: string
      readonly loopxAgentId: string
    }
  | { readonly kind: 'ambiguous'; readonly uniquePairCount: number }
  | { readonly kind: 'unavailable' }

export type GoalBarBindingReadResult =
  | DecodedBindingResolutionV0
  | { readonly kind: 'fault'; readonly code: GoalBarReadFaultCode }

export type GoalBarActivationReadResult =
  | { readonly kind: 'value'; readonly goalActivation: GoalBarActivationV1 }
  | { readonly kind: 'fault'; readonly code: GoalBarReadFaultCode }

export type GoalBarProgressReadResult =
  | { readonly kind: 'value'; readonly progress: GoalBarProgressV1 }
  | { readonly kind: 'fault'; readonly code: GoalBarReadFaultCode }

export type GoalBarReadModelResult =
  | { readonly kind: 'hidden'; readonly reason: 'binding_missing' }
  | {
      readonly kind: 'hidden'
      readonly reason: 'binding_ambiguous'
      readonly uniquePairCount: number
    }
  | { readonly kind: 'present'; readonly snapshot: GoalBarSnapshotV1 }
  | { readonly kind: 'fault'; readonly code: GoalBarReadFaultCode }

interface JsonReadResult {
  readonly exitCode: number
  readonly payload: Record<string, unknown>
}

interface BindingPair {
  readonly goalId: string
  readonly loopxAgentId: string
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function safeCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function parseBindingPairs(value: unknown): BindingPair[] | undefined {
  if (!Array.isArray(value)) return undefined
  const pairs = new Map<string, BindingPair>()
  for (const item of value) {
    const candidate = record(item)
    if (!isGoalBarGoalId(candidate?.goal_id)
      || !isGoalBarAgentId(candidate.agent_id)) return undefined
    const pair = {
      goalId: candidate.goal_id,
      loopxAgentId: candidate.agent_id,
    }
    pairs.set(`${pair.goalId}\u0000${pair.loopxAgentId}`, pair)
  }
  return [...pairs.values()]
}

/**
 * Validate the authoritative resolver relation while retaining process status.
 * Duplicate records for one exact pair are collapsed before the 0/1/>1 test.
 */
export function decodeThreadAgentBindingResolutionV0(
  value: unknown,
  expectedSessionId: string,
  exitCode: number,
): DecodedBindingResolutionV0 | undefined {
  const input = record(value)
  const pairs = parseBindingPairs(input?.matches)
  if (!isGoalBarSessionId(expectedSessionId)
    || !safeCount(exitCode)
    || input?.schema_version !== BINDING_SCHEMA
    || pairs === undefined) return undefined

  if (input.status === 'missing') {
    return exitCode === 0
      && input.ok === true
      && input.host_surface === GOALBAR_HOST_SURFACE
      && input.thread_id === expectedSessionId
      && input.goal_id === null
      && input.agent_id === null
      && pairs.length === 0
      ? { kind: 'missing' }
      : undefined
  }

  if (input.status === 'bound') {
    const pair = pairs.length === 1 ? pairs[0] : undefined
    return exitCode === 0
      && input.ok === true
      && input.host_surface === GOALBAR_HOST_SURFACE
      && input.thread_id === expectedSessionId
      && pair !== undefined
      && input.goal_id === pair.goalId
      && input.agent_id === pair.loopxAgentId
      ? {
          kind: 'bound',
          goalId: pair.goalId,
          loopxAgentId: pair.loopxAgentId,
        }
      : undefined
  }

  if (input.status === 'ambiguous') {
    return exitCode !== 0
      && input.ok === false
      && input.host_surface === GOALBAR_HOST_SURFACE
      && input.thread_id === expectedSessionId
      && input.goal_id === null
      && input.agent_id === null
      && input.error_kind === 'thread_agent_binding_ambiguous'
      && pairs.length > 1
      ? { kind: 'ambiguous', uniquePairCount: pairs.length }
      : undefined
  }

  if (input.status === 'unavailable') {
    const errorKind = input.error_kind
    const exactEcho = errorKind === 'thread_agent_binding_resolution_failed'
      && input.host_surface === GOALBAR_HOST_SURFACE
      && input.thread_id === expectedSessionId
    const redactedInvalidRequest = errorKind === 'thread_agent_binding_invalid_request'
      && input.host_surface === null
      && input.thread_id === null
    return exitCode !== 0
      && input.ok === false
      && input.goal_id === null
      && input.agent_id === null
      && pairs.length === 0
      && (exactEcho || redactedInvalidRequest)
      ? { kind: 'unavailable' }
      : undefined
  }

  return undefined
}

export function decodeGoalActivationPreviewV1(
  value: unknown,
  expectedGoalId: string,
  exitCode: number,
): GoalBarActivationV1 | undefined {
  const input = record(value)
  const readback = record(input?.readback)
  if (!isGoalBarGoalId(expectedGoalId)
    || exitCode !== 0
    || input?.schema_version !== ACTIVATION_TRANSITION_SCHEMA
    || input.goal_id !== expectedGoalId
    || input.ok !== true
    || input.dry_run !== true
    || input.execute !== false
    || input.written !== false
    || input.partial_write !== false
    || input.after_state !== 'stopped'
    || readback?.schema_version !== ACTIVATION_READBACK_SCHEMA) return undefined

  if (input.before_state === 'active') {
    return input.changed === true
      && readback.status === 'not_executed'
      && readback.verified === false
      ? 'active'
      : undefined
  }
  if (input.before_state === 'stopped') {
    return input.changed === false
      && readback.status === 'not_required'
      && readback.verified === true
      ? 'stopped'
      : undefined
  }
  return undefined
}

export function decodeAgentLaneTodoProgressV0(
  value: unknown,
  expectedGoalId: string,
  expectedAgentId: string,
  exitCode: number,
): GoalBarProgressV1 | undefined {
  const input = record(value)
  const projection = record(input?.todo_list_projection)
  const agentTodos = record(input?.agent_todos)
  const items = agentTodos?.items
  const returnedItems = input?.todos
  const processed = agentTodos?.done_count
  const remaining = agentTodos?.open_count
  const total = agentTodos?.total_count
  const returnedCount = input?.returned_todo_count

  if (!isGoalBarGoalId(expectedGoalId)
    || !isGoalBarAgentId(expectedAgentId)
    || exitCode !== 0
    || input?.ok !== true
    || input.read_only !== true
    || input.command !== 'list'
    || input.goal_id !== expectedGoalId
    || input.agent_id_filter !== expectedAgentId
    || input.role !== 'agent'
    || input.explicit_limit !== 1
    || projection?.schema_version !== TODO_PROJECTION_SCHEMA
    || projection.view !== TODO_PROJECTION_VIEW
    || projection.item_limit_per_role !== 1
    || projection.counts_cover_full_match !== true
    || !safeCount(processed)
    || !safeCount(remaining)
    || !safeCount(total)
    || !Number.isSafeInteger(processed + remaining)
    || processed + remaining !== total
    || !safeCount(input.todo_count)
    || !safeCount(returnedCount)
    || !safeCount(projection.matched_todo_count)
    || !safeCount(projection.returned_todo_count)
    || total !== projection.matched_todo_count
    || input.todo_count !== returnedCount
    || returnedCount !== projection.returned_todo_count
    || !Array.isArray(items)
    || !Array.isArray(returnedItems)
    || items.length !== returnedCount
    || returnedItems.length !== returnedCount
    || returnedCount > 1) return undefined

  return { processed, remaining, total }
}

async function executeJsonRead(
  options: GoalBarCliReadOptions,
  args: readonly string[],
): Promise<JsonReadResult> {
  const runner = options.runner ?? runFile
  let exitCode: number | undefined
  const recordingRunner: FileRunner = async (file, fileArgs, runOptions) => {
    const result = await runner(file, fileArgs, runOptions)
    exitCode = result.exitCode
    return result
  }
  const payload = await runJsonCommand(options.command, args, {
    runner: recordingRunner,
    cwd: options.cwd,
    env: options.env,
    signal: options.signal,
    attempts: READ_ATTEMPTS,
    retryDelaysMs: options.retryDelaysMs,
  })
  if (exitCode === undefined) {
    throw new LoopXCliError(
      'transport',
      'LoopX command result was unavailable',
      true,
    )
  }
  return { exitCode, payload }
}

function fixedFault(
  error: unknown,
  stageCode: 'binding_read_failed' | 'activation_read_failed' | 'todo_read_failed',
): { readonly kind: 'fault'; readonly code: GoalBarReadFaultCode } {
  return {
    kind: 'fault',
    code: error instanceof LoopXCliError && error.kind === 'missing'
      ? 'cli_unavailable'
      : stageCode,
  }
}

export async function readGoalBarBinding(
  options: GoalBarCliReadOptions,
  sessionId: string,
): Promise<GoalBarBindingReadResult> {
  if (!isGoalBarSessionId(sessionId)) {
    return { kind: 'fault', code: 'protocol_mismatch' }
  }
  try {
    const result = await executeJsonRead(options, [
      '--registry', GOALBAR_PROJECT_REGISTRY,
      '--format', 'json',
      'resolve-agent-thread',
      '--host-surface', GOALBAR_HOST_SURFACE,
      '--thread-id', sessionId,
    ])
    const decoded = decodeThreadAgentBindingResolutionV0(
      result.payload,
      sessionId,
      result.exitCode,
    )
    return decoded === undefined || decoded.kind === 'unavailable'
      ? { kind: 'fault', code: 'binding_read_failed' }
      : decoded
  } catch (error: unknown) {
    return fixedFault(error, 'binding_read_failed')
  }
}

export async function readGoalBarActivation(
  options: GoalBarCliReadOptions,
  goalId: string,
): Promise<GoalBarActivationReadResult> {
  if (!isGoalBarGoalId(goalId)) {
    return { kind: 'fault', code: 'protocol_mismatch' }
  }
  try {
    const result = await executeJsonRead(options, [
      '--registry', GOALBAR_PROJECT_REGISTRY,
      '--format', 'json',
      'goal-lifecycle',
      '--goal-id', goalId,
      '--operation', 'stop',
    ])
    const goalActivation = decodeGoalActivationPreviewV1(
      result.payload,
      goalId,
      result.exitCode,
    )
    return goalActivation === undefined
      ? { kind: 'fault', code: 'activation_read_failed' }
      : { kind: 'value', goalActivation }
  } catch (error: unknown) {
    return fixedFault(error, 'activation_read_failed')
  }
}

export async function readGoalBarProgress(
  options: GoalBarCliReadOptions,
  goalId: string,
  loopxAgentId: string,
): Promise<GoalBarProgressReadResult> {
  if (!isGoalBarGoalId(goalId) || !isGoalBarAgentId(loopxAgentId)) {
    return { kind: 'fault', code: 'protocol_mismatch' }
  }
  try {
    const result = await executeJsonRead(options, [
      '--registry', GOALBAR_PROJECT_REGISTRY,
      '--format', 'json',
      'todo', 'list',
      '--goal-id', goalId,
      '--role', 'agent',
      '--agent-id', loopxAgentId,
      '--limit', '1',
    ])
    const progress = decodeAgentLaneTodoProgressV0(
      result.payload,
      goalId,
      loopxAgentId,
      result.exitCode,
    )
    return progress === undefined
      ? { kind: 'fault', code: 'todo_read_failed' }
      : { kind: 'value', progress }
  } catch (error: unknown) {
    return fixedFault(error, 'todo_read_failed')
  }
}

function preferredReadFault(
  activation: GoalBarActivationReadResult,
  progress: GoalBarProgressReadResult,
): { readonly kind: 'fault'; readonly code: GoalBarReadFaultCode } | undefined {
  const faults = [activation, progress].filter(
    (result): result is Extract<typeof result, { readonly kind: 'fault' }> => (
      result.kind === 'fault'
    ),
  )
  if (faults.length === 0) return undefined
  return faults.find(fault => fault.code === 'cli_unavailable')
    ?? faults.find(fault => fault.code === 'protocol_mismatch')
    ?? faults[0]
}

export async function readGoalBarModel(
  options: GoalBarReadModelOptions,
): Promise<GoalBarReadModelResult> {
  if (!isGoalBarSessionId(options.sessionId)
    || (options.agentStatus !== 'idle' && options.agentStatus !== 'running')) {
    return { kind: 'fault', code: 'protocol_mismatch' }
  }

  const binding = await readGoalBarBinding(options, options.sessionId)
  if (binding.kind === 'fault') return binding
  if (binding.kind === 'missing') {
    return { kind: 'hidden', reason: 'binding_missing' }
  }
  if (binding.kind === 'ambiguous') {
    return {
      kind: 'hidden',
      reason: 'binding_ambiguous',
      uniquePairCount: binding.uniquePairCount,
    }
  }
  if (binding.kind === 'unavailable') {
    return { kind: 'fault', code: 'binding_read_failed' }
  }

  const [activation, progress] = await Promise.all([
    readGoalBarActivation(options, binding.goalId),
    readGoalBarProgress(options, binding.goalId, binding.loopxAgentId),
  ])
  const fault = preferredReadFault(activation, progress)
  if (fault !== undefined) return fault
  if (activation.kind !== 'value' || progress.kind !== 'value') {
    return { kind: 'fault', code: 'protocol_mismatch' }
  }
  return {
    kind: 'present',
    snapshot: {
      sessionId: options.sessionId,
      goalId: binding.goalId,
      loopxAgentId: binding.loopxAgentId,
      goalActivation: activation.goalActivation,
      agentStatus: options.agentStatus,
      progress: progress.progress,
    },
  }
}

import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import {
  registerGoalBarConnectionRpc,
} from './goalbar/connection-rpc.ts'
import { goalBarCoordinator } from './goalbar/events.ts'
import { createGoalBarService } from './goalbar/service.ts'

export const name = 'dsh-loopx-plugin'
export const inject = ['agents', 'connection']

/** Package-root Host plugin: one GoalBar service, never a second Driver. */
export function apply(ctx: Context): void {
  ctx.effect(() => {
    const service = createGoalBarService({
      getAgent: sessionId => ctx.agents.get(sessionId as Agent['id']),
      coordinator: goalBarCoordinator,
      warn: message => { ctx.logger.warn(message) },
    })
    const disposeRpc = registerGoalBarConnectionRpc(ctx.connection, service)
    return async () => {
      await service.dispose()
      await disposeRpc()
    }
  }, 'dsh-loopx GoalBar Host service')
}

export {
  LoopXCliError,
  resolveLoopXCommand,
  runFile,
  runJsonCommand,
  runJsonMutationCommand,
} from './cli.ts'
export type {
  FileResult,
  FileRunner,
  FileRunOptions,
  JsonCommandOptions,
  JsonMutationCommandOptions,
  LoopXCliErrorKind,
  LoopXCommand,
} from './cli.ts'
export {
  createGoalBarConnectionHandler,
  GOALBAR_RPC_CHANNEL,
  registerGoalBarConnectionRpc,
} from './goalbar/connection-rpc.ts'
export {
  createGoalBarService,
  decodeGoalBarLifecycleExecutionV1,
  GoalBarService,
} from './goalbar/service.ts'
export type {
  GoalBarCoordinatorPort,
  GoalBarServiceHandle,
  GoalBarServiceOptions,
} from './goalbar/service.ts'
export { LoopXContinuationDriver } from './driver.ts'
export type { DriverClock, LoopXDriverOptions } from './driver.ts'
export { initializeLoopX, LoopXInitError } from './init-command.ts'
export type {
  LoopXInitOptions,
  LoopXInitStage,
  LoopXInitSummary,
} from './init-command.ts'

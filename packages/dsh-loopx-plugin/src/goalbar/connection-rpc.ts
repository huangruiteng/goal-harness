import type {
  ConnectionRpcHandler,
  HostConnectionHandle,
} from '@deepseek-ai/dsh-client-connection'
import {
  decodeGoalBarRequestV1,
} from './protocol.ts'
import type {
  GoalBarRequestV1,
  GoalBarResponseV1,
} from './protocol.ts'
import {
  fixedGoalBarFailureResponseV1,
} from './service.ts'
import type { GoalBarServiceHandle } from './service.ts'

export const GOALBAR_RPC_CHANNEL = '/loopx' as const

type ConnectionRpcResult = Awaited<ReturnType<ConnectionRpcHandler>>

function badRequestCarrier(): ConnectionRpcResult {
  return {
    ok: false,
    error: {
      code: 'bad-request',
      message: 'invalid LoopX GoalBar request',
      details: { issues: [] },
    },
  }
}

function successCarrier(value: GoalBarResponseV1): ConnectionRpcResult {
  return { ok: true, value }
}

/**
 * Close the generic Connection carrier around the GoalBar V2 business union.
 * No exception value or request payload is ever rendered into the carrier.
 */
export function createGoalBarConnectionHandler(
  service: GoalBarServiceHandle,
): ConnectionRpcHandler {
  return async (endpoint, payload, signal) => {
    let request: GoalBarRequestV1 | undefined
    try {
      request = decodeGoalBarRequestV1(endpoint, payload)
      if (request === undefined) return badRequestCarrier()
      try {
        return successCarrier(await service.handle(request, signal))
      } catch {
        return successCarrier(fixedGoalBarFailureResponseV1(request))
      }
    } catch {
      return request === undefined
        ? badRequestCarrier()
        : successCarrier(fixedGoalBarFailureResponseV1(request))
    }
  }
}

export function registerGoalBarConnectionRpc(
  connection: HostConnectionHandle,
  service: GoalBarServiceHandle,
): () => Promise<void> {
  return connection.rpc.handle(
    GOALBAR_RPC_CHANNEL,
    createGoalBarConnectionHandler(service),
    { authority: 'loopback' },
  )
}

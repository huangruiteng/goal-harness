// @vitest-environment jsdom

import { act } from 'react-dom/test-utils'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

vi.mock('../src/client/goalbar.module.css', () => ({
  default: new Proxy({}, {
    get: (_target, property) => String(property),
  }),
  ensurePluginStyle: vi.fn(),
}))

import {
  GOALBAR_RESPONSE_VERSION,
  type GoalBarActionResultV1,
  type GoalBarReadResultV1,
  type GoalBarSnapshotV1,
} from '../src/goalbar/protocol.ts'
import { LoopXGoalBar, type LoopXGoalBarProps } from '../src/client/LoopXGoalBar.tsx'
import { apply, inject } from '../src/client/index.tsx'
import {
  GOALBAR_LOCALES,
  type GoalBarLocaleKey,
  type GoalBarTranslate,
} from '../src/client/locale.ts'
import {
  createGoalBarRpc,
  type GoalBarPauseResponseV1,
  type GoalBarReadResponseV1,
  type GoalBarRpc,
  type GoalBarRpcOutcome,
  type GoalBarStartResponseV1,
  type GoalBarWatchResponseV1,
} from '../src/client/rpc.ts'

const roots: Array<{ root: Root; container: HTMLDivElement; mounted: boolean }> = []

beforeAll(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
    .IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  for (const mounted of roots) {
    if (mounted.mounted) act(() => mounted.root.unmount())
    mounted.container.remove()
  }
  roots.length = 0
  document.head.querySelectorAll('style[data-plugin]').forEach(style => style.remove())
  vi.restoreAllMocks()
})

function t(key: GoalBarLocaleKey, params?: Record<string, unknown>): string {
  return GOALBAR_LOCALES.en[key].replace(/\{([^}]+)\}/gu, (_match, name: string) => (
    String(params?.[name] ?? `{${name}}`)
  ))
}

const englishT = t as GoalBarTranslate

function snapshot(
  overrides: Partial<GoalBarSnapshotV1> = {},
): GoalBarSnapshotV1 {
  return {
    sessionId: 'session-one',
    goalId: 'goal-one',
    loopxAgentId: 'codex-main-control',
    goalActivation: 'active',
    agentStatus: 'idle',
    progress: { processed: 2, remaining: 3, total: 5 },
    ...overrides,
  }
}

function readOutcome(
  sessionId: string,
  result: GoalBarReadResultV1,
): GoalBarRpcOutcome<GoalBarReadResponseV1> {
  return {
    ok: true,
    response: {
      v: GOALBAR_RESPONSE_VERSION,
      op: 'read',
      sessionId,
      result,
    },
  }
}

function watchOutcome(
  sessionId: string,
  result: GoalBarWatchResponseV1['result'],
): GoalBarRpcOutcome<GoalBarWatchResponseV1> {
  return {
    ok: true,
    response: {
      v: GOALBAR_RESPONSE_VERSION,
      op: 'watch',
      sessionId,
      result,
    },
  }
}

function actionOutcome<T extends 'start' | 'pause'>(
  op: T,
  sessionId: string,
  result: GoalBarActionResultV1,
): GoalBarRpcOutcome<T extends 'start' ? GoalBarStartResponseV1 : GoalBarPauseResponseV1> {
  return {
    ok: true,
    response: {
      v: GOALBAR_RESPONSE_VERSION,
      op,
      sessionId,
      result,
    },
  } as GoalBarRpcOutcome<T extends 'start'
    ? GoalBarStartResponseV1
    : GoalBarPauseResponseV1>
}

function abortOutcome<T>(signal: AbortSignal): Promise<GoalBarRpcOutcome<T>> {
  return new Promise(resolve => {
    signal.addEventListener('abort', () => {
      resolve({ ok: false, code: 'transport_error' })
    }, { once: true })
  })
}

function fakeRpc(overrides: Partial<GoalBarRpc> = {}): GoalBarRpc {
  return {
    read: overrides.read ?? ((sessionId) => Promise.resolve(readOutcome(sessionId, {
      kind: 'hidden',
      reason: 'binding_missing',
      baseTurnEndSeq: null,
    }))),
    watch: overrides.watch ?? ((_sessionId, _cursor, signal) => abortOutcome(signal)),
    start: overrides.start ?? ((_sessionId, _expected, signal) => abortOutcome(signal)),
    pause: overrides.pause ?? ((_sessionId, _expected, signal) => abortOutcome(signal)),
  }
}

function mount(props: Omit<LoopXGoalBarProps, 't'> & { readonly t?: GoalBarTranslate }) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const mounted = { root, container, mounted: true }
  roots.push(mounted)

  const render = (next: typeof props) => {
    act(() => root.render(<LoopXGoalBar {...next} t={next.t ?? englishT} />))
  }
  render(props)
  return {
    container,
    rerender: render,
    unmount() {
      if (!mounted.mounted) return
      act(() => root.unmount())
      mounted.mounted = false
    },
  }
}

async function flush(rounds = 4): Promise<void> {
  await act(async () => {
    for (let index = 0; index < rounds; index += 1) await Promise.resolve()
  })
}

function button(container: Element, label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')]
    .find(candidate => candidate.textContent === label)
  if (!(found instanceof HTMLButtonElement)) throw new Error(`missing button ${label}`)
  return found
}

describe('LoopXGoalBar presentation', () => {
  it.each([
    ['active', 'idle', 'Active', 'Pause', false],
    ['active', 'running', 'Running', 'Pause', false],
    ['stopped', 'idle', 'Paused', 'Start', false],
    ['stopped', 'running', 'Paused', 'Start', true],
  ] as const)(
    'maps %s + %s to fixed status and action text',
    async (goalActivation, agentStatus, status, action, disabled) => {
      const goalId = 'goal-with-a-very-long-visual-identity-123456789'
      const rpc = fakeRpc({
        read: sessionId => Promise.resolve(readOutcome(sessionId, {
          kind: 'present',
          snapshot: snapshot({ sessionId, goalId, goalActivation, agentStatus }),
          baseTurnEndSeq: 7,
        })),
      })
      const view = mount({ rpcSessionId: 'session-one', rpc })
      await flush()

      const region = view.container.querySelector('[aria-label="LoopX Goal status"]')
      expect(region?.textContent).toContain(status)
      expect(button(view.container, action).disabled).toBe(disabled)
      expect(view.container.querySelector('[title]')?.getAttribute('title')).toBe(goalId)
      expect(view.container.querySelector('progress')?.getAttribute('aria-label'))
        .toBe('Agent-lane todos: 2 of 5 processed')
    },
  )

  it('renders empty progress as 0 / 0 with the exact accessible label', async () => {
    const rpc = fakeRpc({
      read: sessionId => Promise.resolve(readOutcome(sessionId, {
        kind: 'present',
        snapshot: snapshot({
          sessionId,
          progress: { processed: 0, remaining: 0, total: 0 },
        }),
        baseTurnEndSeq: 0,
      })),
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush()

    expect(view.container.textContent).toContain('0 / 0')
    expect(view.container.querySelector('progress')?.getAttribute('aria-label'))
      .toBe('No agent-lane todos')
  })

  it.each(['binding_missing', 'binding_ambiguous'] as const)(
    'renders no row for %s',
    async reason => {
      const rpc = fakeRpc({
        read: sessionId => Promise.resolve(readOutcome(sessionId, {
          kind: 'hidden',
          reason,
          baseTurnEndSeq: 1,
        })),
      })
      const view = mount({ rpcSessionId: 'session-one', rpc })
      await flush()
      expect(view.container.innerHTML).toBe('')
    },
  )
})

describe('GoalBar read/watch generations', () => {
  it.each([
    ['business', readOutcome('session-one', {
      kind: 'fault', code: 'activation_read_failed', baseTurnEndSeq: 2,
    })],
    ['transport', { ok: false, code: 'transport_error' } as const],
    ['protocol', { ok: false, code: 'protocol_error' } as const],
  ])('hides an initial %s fault and stops before watch', async (_kind, outcome) => {
    let watches = 0
    const rpc = fakeRpc({
      read: () => Promise.resolve(outcome),
      watch: (_sessionId, _cursor, signal) => {
        watches += 1
        return abortOutcome(signal)
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush()
    expect(view.container.innerHTML).toBe('')
    expect(watches).toBe(0)
  })

  it('renews a timeout without a read and reads only after changed', async () => {
    let reads = 0
    const cursors: Array<number | null> = []
    const rpc = fakeRpc({
      read: sessionId => {
        reads += 1
        return Promise.resolve(readOutcome(sessionId, {
          kind: 'present',
          snapshot: snapshot({
            sessionId,
            progress: reads === 1
              ? { processed: 2, remaining: 3, total: 5 }
              : { processed: 3, remaining: 2, total: 5 },
          }),
          baseTurnEndSeq: reads === 1 ? 4 : 5,
        }))
      },
      watch: (sessionId, cursor, signal) => {
        cursors.push(cursor)
        if (cursors.length === 1) {
          return Promise.resolve(watchOutcome(sessionId, {
            kind: 'timeout', turnEndSeq: 4,
          }))
        }
        if (cursors.length === 2) {
          return Promise.resolve(watchOutcome(sessionId, {
            kind: 'changed', turnEndSeq: 5,
          }))
        }
        return abortOutcome(signal)
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush(8)

    expect(reads).toBe(2)
    expect(cursors).toEqual([4, 4, 5])
    expect(view.container.textContent).toContain('3 / 5')
  })

  it('stops on a fault, keeps last-good stale, and resumes only on Refresh', async () => {
    let reads = 0
    let watches = 0
    const rpc = fakeRpc({
      read: sessionId => {
        reads += 1
        if (reads === 2) {
          return Promise.resolve(readOutcome(sessionId, {
            kind: 'fault', code: 'todo_read_failed', baseTurnEndSeq: 3,
          }))
        }
        return Promise.resolve(readOutcome(sessionId, {
          kind: 'present',
          snapshot: snapshot({
            sessionId,
            progress: reads === 1
              ? { processed: 2, remaining: 3, total: 5 }
              : { processed: 4, remaining: 1, total: 5 },
          }),
          baseTurnEndSeq: reads === 1 ? 2 : 3,
        }))
      },
      watch: (sessionId, _cursor, signal) => {
        watches += 1
        return watches === 1
          ? Promise.resolve(watchOutcome(sessionId, { kind: 'changed', turnEndSeq: 3 }))
          : abortOutcome(signal)
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush(8)

    expect(reads).toBe(2)
    expect(watches).toBe(1)
    expect(view.container.textContent).toContain('2 / 5')
    expect(view.container.textContent).toContain('Todo progress could not be read.')
    expect(button(view.container, 'Pause').disabled).toBe(true)

    act(() => button(view.container, 'Refresh').click())
    await flush(6)
    expect(reads).toBe(3)
    expect(watches).toBe(2)
    expect(view.container.textContent).toContain('4 / 5')
    expect(view.container.textContent).not.toContain('Todo progress could not be read.')
    expect(button(view.container, 'Pause').disabled).toBe(false)
  })

  it('stops a watch fault and keeps the last-good row disabled', async () => {
    let watches = 0
    const rpc = fakeRpc({
      read: sessionId => Promise.resolve(readOutcome(sessionId, {
        kind: 'present', snapshot: snapshot({ sessionId }), baseTurnEndSeq: 2,
      })),
      watch: sessionId => {
        watches += 1
        return Promise.resolve(watchOutcome(sessionId, {
          kind: 'fault', code: 'session_unavailable',
        }))
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush(6)

    expect(watches).toBe(1)
    expect(view.container.textContent).toContain('The session is unavailable.')
    expect(button(view.container, 'Pause').disabled).toBe(true)
    expect(button(view.container, 'Refresh')).toBeInstanceOf(HTMLButtonElement)
  })

  it('aborts and fences old completions on Session switch and unmount', async () => {
    let resolveOld!: (value: GoalBarRpcOutcome<GoalBarReadResponseV1>) => void
    let oldSignal: AbortSignal | undefined
    let currentWatchSignal: AbortSignal | undefined
    const oldRead = new Promise<GoalBarRpcOutcome<GoalBarReadResponseV1>>(resolve => {
      resolveOld = resolve
    })
    const rpc = fakeRpc({
      read: (sessionId, signal) => {
        if (sessionId === 'session-old') {
          oldSignal = signal
          return oldRead
        }
        return Promise.resolve(readOutcome(sessionId, {
          kind: 'present',
          snapshot: snapshot({ sessionId, goalId: 'goal-new' }),
          baseTurnEndSeq: 9,
        }))
      },
      watch: (_sessionId, _cursor, signal) => {
        currentWatchSignal = signal
        return abortOutcome(signal)
      },
    })
    const view = mount({ rpcSessionId: 'session-old', rpc })
    await flush()
    view.rerender({ rpcSessionId: 'session-new', rpc })
    await flush()

    expect(oldSignal?.aborted).toBe(true)
    expect(view.container.textContent).toContain('goal-new')
    resolveOld(readOutcome('session-old', {
      kind: 'present',
      snapshot: snapshot({ sessionId: 'session-old', goalId: 'goal-old' }),
      baseTurnEndSeq: 8,
    }))
    await flush()
    expect(view.container.textContent).not.toContain('goal-old')

    view.unmount()
    expect(currentWatchSignal?.aborted).toBe(true)
  })

  it('keeps multiple instances for one Session fully independent', async () => {
    const watchSignals: AbortSignal[] = []
    const rpc = fakeRpc({
      read: sessionId => Promise.resolve(readOutcome(sessionId, {
        kind: 'present', snapshot: snapshot({ sessionId }), baseTurnEndSeq: 1,
      })),
      watch: (_sessionId, _cursor, signal) => {
        watchSignals.push(signal)
        return abortOutcome(signal)
      },
    })
    const first = mount({ rpcSessionId: 'session-one', rpc })
    const second = mount({ rpcSessionId: 'session-one', rpc })
    await flush()

    expect(watchSignals).toHaveLength(2)
    expect(watchSignals[0]).not.toBe(watchSignals[1])
    first.unmount()
    expect(watchSignals[0]?.aborted).toBe(true)
    expect(watchSignals[1]?.aborted).toBe(false)
    second.unmount()
    expect(watchSignals[1]?.aborted).toBe(true)
  })

  it('treats a Connection reset as a fresh, aborting read generation', async () => {
    let reads = 0
    let reset: (() => void) | undefined
    const watchSignals: AbortSignal[] = []
    const rpc = fakeRpc({
      read: sessionId => {
        reads += 1
        return Promise.resolve(readOutcome(sessionId, {
          kind: 'present',
          snapshot: snapshot({
            sessionId,
            progress: reads === 1
              ? { processed: 1, remaining: 4, total: 5 }
              : { processed: 2, remaining: 3, total: 5 },
          }),
          baseTurnEndSeq: reads,
        }))
      },
      watch: (_sessionId, _cursor, signal) => {
        watchSignals.push(signal)
        return abortOutcome(signal)
      },
    })
    const view = mount({
      rpcSessionId: 'session-one',
      rpc,
      subscribeConnectionReset: listener => {
        reset = listener
        return () => {
          reset = undefined
        }
      },
    })
    await flush()
    expect(view.container.textContent).toContain('1 / 5')

    act(() => reset?.())
    await flush()
    expect(watchSignals[0]?.aborted).toBe(true)
    expect(reads).toBe(2)
    expect(view.container.textContent).toContain('2 / 5')
  })
})

describe('GoalBar actions', () => {
  it('guards same-frame duplicates, stays non-optimistic, and adopts the fresh result', async () => {
    let pauseCalls = 0
    let resolvePause!: (value: GoalBarRpcOutcome<GoalBarPauseResponseV1>) => void
    const pause = new Promise<GoalBarRpcOutcome<GoalBarPauseResponseV1>>(resolve => {
      resolvePause = resolve
    })
    const rpc = fakeRpc({
      read: sessionId => Promise.resolve(readOutcome(sessionId, {
        kind: 'present', snapshot: snapshot({ sessionId }), baseTurnEndSeq: 4,
      })),
      pause: () => {
        pauseCalls += 1
        return pause
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush()

    const pauseButton = button(view.container, 'Pause')
    act(() => {
      pauseButton.click()
      pauseButton.click()
    })
    expect(pauseCalls).toBe(1)
    expect(view.container.textContent).toContain('Active')
    expect(button(view.container, 'Pause').disabled).toBe(true)

    resolvePause(actionOutcome('pause', 'session-one', {
      kind: 'succeeded',
      snapshot: snapshot({ goalActivation: 'stopped', agentStatus: 'idle' }),
      baseTurnEndSeq: 5,
    }))
    await flush()
    expect(view.container.textContent).toContain('Paused')
    expect(button(view.container, 'Start').disabled).toBe(false)
  })

  it.each([
    [
      { kind: 'unknown', code: 'operation_result_unknown' } as const,
      'The action result is uncertain.',
    ],
    [
      { kind: 'rejected', code: 'binding_mismatch' } as const,
      'The LoopX binding changed.',
    ],
  ])('locks %s until an explicit successful Refresh', async (result, message) => {
    let reads = 0
    let pauses = 0
    const rpc = fakeRpc({
      read: sessionId => {
        reads += 1
        return Promise.resolve(readOutcome(sessionId, {
          kind: 'present', snapshot: snapshot({ sessionId }), baseTurnEndSeq: reads,
        }))
      },
      pause: sessionId => {
        pauses += 1
        return Promise.resolve(actionOutcome('pause', sessionId, result))
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush()
    act(() => button(view.container, 'Pause').click())
    await flush()

    expect(view.container.textContent).toContain(message)
    expect(button(view.container, 'Pause').disabled).toBe(true)
    act(() => button(view.container, 'Pause').click())
    expect(pauses).toBe(1)

    act(() => button(view.container, 'Refresh').click())
    await flush()
    expect(reads).toBe(2)
    expect(view.container.textContent).not.toContain(message)
    expect(button(view.container, 'Pause').disabled).toBe(false)
  })

  it.each([
    [
      {
        kind: 'applied_with_warning',
        code: 'driver_sync_failed',
        snapshot: snapshot({ goalActivation: 'stopped', agentStatus: 'idle' }),
        baseTurnEndSeq: 2,
      } as const,
      'Paused',
      'LoopX changed, but the session did not sync.',
    ],
    [
      { kind: 'applied_with_warning', code: 'post_read_failed' } as const,
      'Active',
      'LoopX changed, but the latest status is unavailable.',
    ],
  ])('locks action warning %s and adopts only a supplied fresh snapshot', async (
    result,
    expectedStatus,
    message,
  ) => {
    let pauses = 0
    const rpc = fakeRpc({
      read: sessionId => Promise.resolve(readOutcome(sessionId, {
        kind: 'present', snapshot: snapshot({ sessionId }), baseTurnEndSeq: 1,
      })),
      pause: sessionId => {
        pauses += 1
        return Promise.resolve(actionOutcome('pause', sessionId, result))
      },
    })
    const view = mount({ rpcSessionId: 'session-one', rpc })
    await flush()
    act(() => button(view.container, 'Pause').click())
    await flush()

    expect(view.container.textContent).toContain(expectedStatus)
    expect(view.container.textContent).toContain(message)
    const action = button(view.container, expectedStatus === 'Paused' ? 'Start' : 'Pause')
    expect(action.disabled).toBe(true)
    act(() => action.click())
    expect(pauses).toBe(1)
    expect(button(view.container, 'Refresh')).toBeInstanceOf(HTMLButtonElement)
  })
})

describe('GoalBar Connection and registration boundaries', () => {
  it('discards arbitrary carrier and exception messages and strictly decodes success', async () => {
    const secret = 'SECRET carrier path and stack'
    const log = vi.spyOn(console, 'log').mockImplementation(() => undefined)
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const error = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    const signal = new AbortController().signal
    const failed = createGoalBarRpc({
      call: () => Promise.resolve({
        ok: false,
        error: { code: 'internal', message: secret, details: {} },
      }),
    })
    expect(await failed.read('session-one', signal)).toEqual({
      ok: false, code: 'transport_error',
    })

    const malformed = createGoalBarRpc({
      call: () => Promise.resolve({ ok: true, value: {
        v: GOALBAR_RESPONSE_VERSION,
        op: 'read',
        sessionId: 'session-one',
        result: {
          kind: 'hidden', reason: 'binding_missing', baseTurnEndSeq: 1,
          message: secret,
        },
      } }),
    })
    expect(await malformed.read('session-one', signal)).toEqual({
      ok: false, code: 'protocol_error',
    })

    const thrown = createGoalBarRpc({ call: () => Promise.reject(new Error(secret)) })
    expect(await thrown.read('session-one', signal)).toEqual({
      ok: false, code: 'transport_error',
    })
    expect(log).not.toHaveBeenCalled()
    expect(warn).not.toHaveBeenCalled()
    expect(error).not.toHaveBeenCalled()
  })

  it('uses the exact channel, endpoint, payload, and AbortSignal', async () => {
    const call = vi.fn((_channel: string, _endpoint: string, payload: unknown) => Promise.resolve({
      ok: true as const,
      value: {
        v: GOALBAR_RESPONSE_VERSION,
        op: 'read',
        sessionId: (payload as { sessionId: string }).sessionId,
        result: { kind: 'hidden', reason: 'binding_missing', baseTurnEndSeq: null },
      },
    }))
    const rpc = createGoalBarRpc({ call })
    const controller = new AbortController()
    await rpc.read('session-one', controller.signal)
    expect(call).toHaveBeenCalledWith(
      '/loopx',
      'goalbar/read',
      {
        v: 'loopx_goalbar_request_v1',
        op: 'read',
        sessionId: 'session-one',
      },
      controller.signal,
    )
  })

  it('registers only the injected Session identity and removes exact-owned CSS', async () => {
    const css = await import('../src/client/goalbar.module.css')
    const ensure = vi.mocked(css.ensurePluginStyle)
    const effects = new Map<string, () => void>()
    let registration: {
      options: {
        id: string
        order: number
        inject: (sessionId: string) => Record<string, unknown>
      }
      component: unknown
    } | undefined
    const registerLocale = vi.fn(() => () => undefined)
    const ctx = {
      connection: { rpc: { call: vi.fn() } },
      locale: { register: registerLocale },
      slots: {
        inject: vi.fn((_key: string, install: () => () => void) => install()),
        register: vi.fn((options: typeof registration extends { options: infer O } ? O : never, component: unknown) => {
          registration = { options, component }
          return () => undefined
        }),
      },
      on: vi.fn(() => () => true),
      effect: vi.fn((execute: () => () => void, label: string) => {
        effects.set(label, execute())
        return () => Promise.resolve()
      }),
    }

    expect(inject).toEqual(['connection', 'locale', 'slots'])
    apply(ctx as never)
    expect(ensure).toHaveBeenCalledOnce()
    expect(registerLocale).toHaveBeenCalledWith('loopx.goalbar', GOALBAR_LOCALES)
    expect(ctx.slots.inject).toHaveBeenCalledWith(
      'conversation.input.dock',
      expect.any(Function),
    )
    expect(registration?.options.id).toBe('loopx-goal')
    expect(registration?.options.order).toBe(15)
    expect(registration?.component).toBe(LoopXGoalBar)
    const injected = registration?.options.inject('session-injected')
    expect(injected?.rpcSessionId).toBe('session-injected')
    expect(injected).not.toHaveProperty('sessionId')
    expect(injected).not.toHaveProperty('goal')
    expect(injected).not.toHaveProperty('remote')

    const owned = document.createElement('style')
    owned.dataset.plugin = 'dsh-loopx-plugin'
    const lookalike = document.createElement('style')
    lookalike.dataset.plugin = 'dsh-loopx-plugin-extra'
    document.head.append(owned, lookalike)
    effects.get('dsh-loopx-plugin CSS ownership')?.()
    expect(owned.isConnected).toBe(false)
    expect(lookalike.isConnected).toBe(true)
  })

  it('claims the CSS disposer before a later apply step can fail', () => {
    const owned = document.createElement('style')
    owned.dataset.plugin = 'dsh-loopx-plugin'
    document.head.appendChild(owned)
    let cssDispose: (() => void) | undefined
    const order: string[] = []
    const ctx = {
      connection: { rpc: { call: vi.fn() } },
      locale: {
        register: () => {
          order.push('locale')
          throw new Error('locale registration failed')
        },
      },
      slots: { inject: vi.fn(), register: vi.fn() },
      effect: (execute: () => () => void, label: string) => {
        order.push(label)
        const dispose = execute()
        if (label === 'dsh-loopx-plugin CSS ownership') cssDispose = dispose
        return () => Promise.resolve()
      },
    }

    expect(() => apply(ctx as never)).toThrow('locale registration failed')
    expect(order).toEqual([
      'dsh-loopx-plugin CSS ownership',
      'dsh-loopx-plugin GoalBar locale',
      'locale',
    ])
    expect(cssDispose).toBeTypeOf('function')
    cssDispose?.()
    expect(owned.isConnected).toBe(false)
  })
})

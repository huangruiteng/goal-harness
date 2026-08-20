import { describe, expect, it } from 'vitest'
import {
  LoopXCliError,
  resolveLoopXCommand,
  runJsonCommand,
} from '../src/cli.ts'
import type { FileRunner, LoopXCommand } from '../src/cli.ts'

const command: LoopXCommand = {
  file: 'loopx',
  prefix: [],
  skillCommand: 'loopx',
  version: 'loopx 0.5.0',
}

describe('runJsonCommand', () => {
  it('keeps a configured LoopX executable as one quoted shell word', async () => {
    const configured = '/opt/Loop X/loopx'
    const resolved = await resolveLoopXCommand({
      env: { ...process.env, LOOPX_BIN: configured },
      runner: async (file, args) => {
        expect(file).toBe(configured)
        expect(args).toEqual(['--version'])
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      },
    })

    expect(resolved.skillCommand).toBe('"$LOOPX_BIN"')
  })

  it('renders the configured Python fallback as one shell-safe skill command', async () => {
    const python = "/opt/Loop X/python'3"
    const resolved = await resolveLoopXCommand({
      env: { ...process.env, PYTHON_BIN: python },
      runner: async (file, args) => {
        if (file === 'loopx') return { exitCode: 127, stdout: '', stderr: '' }
        expect(file).toBe(python)
        expect(args).toEqual(['-m', 'loopx.cli', '--version'])
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      },
    })

    expect(resolved.skillCommand).toBe(`'/opt/Loop X/python'"'"'3' -m loopx.cli`)
  })

  it('retries transport-safe fixed argv without changing the request', async () => {
    const calls: string[][] = []
    const runner: FileRunner = async (_file, args) => {
      calls.push([...args])
      if (calls.length < 3) {
        throw new LoopXCliError('timeout', 'timed out', true)
      }
      return { exitCode: 0, stdout: '{"ok":true,"value":7}', stderr: '' }
    }

    const payload = await runJsonCommand(command, ['quota', 'should-run'], {
      runner,
      attempts: 3,
      retryDelaysMs: [0, 0],
    })

    expect(payload).toEqual({ ok: true, value: 7 })
    expect(calls).toEqual([
      ['quota', 'should-run'],
      ['quota', 'should-run'],
      ['quota', 'should-run'],
    ])
  })

  it('returns a typed nonzero authority response without retrying', async () => {
    let calls = 0
    const runner: FileRunner = async () => {
      calls += 1
      return {
        exitCode: 1,
        stdout: '{"ok":false,"error_kind":"authority_denied"}',
        stderr: 'private diagnostic must not be parsed',
      }
    }

    const payload = await runJsonCommand(command, ['quota', 'should-run'], {
      runner,
      attempts: 3,
    })

    expect(payload.error_kind).toBe('authority_denied')
    expect(calls).toBe(1)
  })

  it('does not retry an incompatible typed schema', async () => {
    let calls = 0
    const runner: FileRunner = async () => {
      calls += 1
      return { exitCode: 0, stdout: '{"schema_version":"old"}', stderr: '' }
    }

    await expect(runJsonCommand(command, ['inspect'], {
      runner,
      attempts: 3,
      validate: payload => payload.schema_version === 'current',
    })).rejects.toMatchObject({ kind: 'invalid_schema', retryable: false })
    expect(calls).toBe(1)
  })
})

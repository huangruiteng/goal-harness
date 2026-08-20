import { describe, expect, it } from 'vitest'
import { LoopXCliError } from '../src/cli.ts'
import type { FileRunner } from '../src/cli.ts'
import { initializeLoopX } from '../src/init-command.ts'

const hostSurface = 'deepseek-harness-native'

function workflowPayload(operation: 'inspect' | 'install', installRequired = false): string {
  return JSON.stringify({
    ok: true,
    schema_version: 'loopx_workflow_skill_install_v0',
    operation,
    host_surface: hostSurface,
    ...(operation === 'inspect' ? { install_required: installRequired } : {}),
  })
}

describe('/loopx-init implementation', () => {
  it('keeps a compatible CLI and installs plus verifies the DSH skills', async () => {
    const calls: string[][] = []
    let inspectCount = 0
    const runner: FileRunner = async (_file, args) => {
      calls.push([...args])
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      if (args.includes('workflow-skills')) {
        if (args.includes('--install')) {
          return { exitCode: 0, stdout: workflowPayload('install'), stderr: '' }
        }
        inspectCount += 1
        return {
          exitCode: 0,
          stdout: workflowPayload('inspect', inspectCount === 1),
          stderr: '',
        }
      }
      throw new Error(`unexpected argv: ${args.join(' ')}`)
    }

    const result = await initializeLoopX({
      runner,
      skillsDir: '/fixture/.agents/skills',
    })

    expect(result).toEqual({
      cliVersion: 'loopx 0.5.0',
      cliInstalled: false,
      skillsInstalled: true,
      hostSurface,
    })
    expect(calls.some(args => args.slice(0, 5).join(' ') === (
      '-m pip install --upgrade loopx'
    ))).toBe(false)
    expect(calls.filter(args => args.includes('--install'))).toHaveLength(1)
    expect(calls.at(-1)).toContain(hostSurface)
  })

  it('uses the DSH Agents home when no explicit skills directory is provided', async () => {
    const calls: string[][] = []
    const runner: FileRunner = async (_file, args) => {
      calls.push([...args])
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      const operation = args.includes('--install') ? 'install' : 'inspect'
      return {
        exitCode: 0,
        stdout: workflowPayload(operation, false),
        stderr: '',
      }
    }

    await initializeLoopX({
      runner,
      env: { ...process.env, DSH_AGENTS_HOME: '/fixture/agents-home' },
    })

    const workflowCalls = calls.filter(args => args.includes('workflow-skills'))
    for (const args of workflowCalls) {
      expect(args[args.indexOf('--skills-dir') + 1]).toBe('/fixture/agents-home/skills')
    }
  })

  it('installs the CLI once when neither console nor module is available', async () => {
    let installed = false
    let pipCalls = 0
    const runner: FileRunner = async (_file, args) => {
      if (args.slice(0, 4).join(' ') === '-m pip install --upgrade') {
        pipCalls += 1
        installed = true
        return { exitCode: 0, stdout: 'installed', stderr: '' }
      }
      if (args.at(-1) === '--version') {
        if (!installed) throw new LoopXCliError('missing', 'missing', false)
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      if (args.includes('workflow-skills')) {
        const operation = args.includes('--install') ? 'install' : 'inspect'
        return {
          exitCode: 0,
          stdout: workflowPayload(operation, false),
          stderr: '',
        }
      }
      throw new Error(`unexpected argv: ${args.join(' ')}`)
    }

    const result = await initializeLoopX({ runner, skillsDir: '/fixture/skills' })

    expect(result.cliInstalled).toBe(true)
    expect(pipCalls).toBe(1)
  })

  it('repairs an incompatible existing CLI before mutating skills', async () => {
    let upgraded = false
    let pipCalls = 0
    const runner: FileRunner = async (_file, args) => {
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.4.0\n', stderr: '' }
      }
      if (args.slice(0, 4).join(' ') === '-m pip install --upgrade') {
        pipCalls += 1
        upgraded = true
        return { exitCode: 0, stdout: 'upgraded', stderr: '' }
      }
      if (args.includes('workflow-skills')) {
        if (!upgraded) {
          return {
            exitCode: 0,
            stdout: '{"ok":true,"schema_version":"old_workflow_schema"}',
            stderr: '',
          }
        }
        const operation = args.includes('--install') ? 'install' : 'inspect'
        return {
          exitCode: 0,
          stdout: workflowPayload(operation, false),
          stderr: '',
        }
      }
      throw new Error(`unexpected argv: ${args.join(' ')}`)
    }

    const result = await initializeLoopX({ runner, skillsDir: '/fixture/skills' })
    expect(result.cliInstalled).toBe(true)
    expect(pipCalls).toBe(1)
  })

  it('never retries a failed skill installation mutation', async () => {
    let installCalls = 0
    const runner: FileRunner = async (_file, args) => {
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      if (args.includes('--install')) {
        installCalls += 1
        return {
          exitCode: 1,
          stdout: JSON.stringify({
            ok: false,
            schema_version: 'loopx_workflow_skill_install_v0',
            operation: 'install',
            host_surface: hostSurface,
          }),
          stderr: '/private/path/that/must/not/be-surfaced',
        }
      }
      return {
        exitCode: 0,
        stdout: workflowPayload('inspect', true),
        stderr: '',
      }
    }

    await expect(initializeLoopX({ runner, skillsDir: '/fixture/skills' }))
      .rejects.toMatchObject({ stage: 'install_skills', causeKind: 'typed_failure' })
    expect(installCalls).toBe(1)
  })

  it('fails closed when post-install readback still requests installation', async () => {
    let inspectCalls = 0
    const runner: FileRunner = async (_file, args) => {
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      if (args.includes('--install')) {
        return { exitCode: 0, stdout: workflowPayload('install'), stderr: '' }
      }
      inspectCalls += 1
      return {
        exitCode: 0,
        stdout: workflowPayload('inspect', inspectCalls > 1),
        stderr: '',
      }
    }

    await expect(initializeLoopX({ runner, skillsDir: '/fixture/skills' }))
      .rejects.toMatchObject({ stage: 'readback', causeKind: 'readback_mismatch' })
  })

  it('propagates cancellation without running an install fallback', async () => {
    let pipCalls = 0
    const runner: FileRunner = async (_file, args) => {
      if (args.slice(0, 4).join(' ') === '-m pip install --upgrade') pipCalls += 1
      throw new LoopXCliError('aborted', 'cancelled', false)
    }

    await expect(initializeLoopX({ runner, skillsDir: '/fixture/skills' }))
      .rejects.toMatchObject({ kind: 'aborted' })
    expect(pipCalls).toBe(0)
  })

  it('preserves cancellation during the skill-install mutation', async () => {
    let installCalls = 0
    const runner: FileRunner = async (_file, args) => {
      if (args.at(-1) === '--version') {
        return { exitCode: 0, stdout: 'loopx 0.5.0\n', stderr: '' }
      }
      if (args.includes('--install')) {
        installCalls += 1
        throw new LoopXCliError('aborted', 'cancelled', false)
      }
      return {
        exitCode: 0,
        stdout: workflowPayload('inspect', false),
        stderr: '',
      }
    }

    await expect(initializeLoopX({ runner, skillsDir: '/fixture/skills' }))
      .rejects.toMatchObject({ kind: 'aborted' })
    expect(installCalls).toBe(1)
  })
})

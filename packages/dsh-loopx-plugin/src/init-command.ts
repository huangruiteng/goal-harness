import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { CommandResult } from '@deepseek-ai/dsh-commands'
import {
  LoopXCliError,
  resolveLoopXCommand,
  runFile,
  runJsonCommand,
} from './cli.ts'
import type { FileRunner, LoopXCommand } from './cli.ts'

export const name = 'dsh-loopx-init-command'
export const inject = ['commands']

const HOST_SURFACE = 'deepseek-harness-native'
const WORKFLOW_SCHEMA = 'loopx_workflow_skill_install_v0'

export type LoopXInitStage = 'probe' | 'install_cli' | 'install_skills' | 'readback'

export class LoopXInitError extends Error {
  constructor(
    readonly stage: LoopXInitStage,
    message: string,
    readonly causeKind?: string | undefined,
  ) {
    super(message)
    this.name = 'LoopXInitError'
  }
}

export interface LoopXInitOptions {
  readonly runner?: FileRunner | undefined
  readonly signal?: AbortSignal | undefined
  readonly env?: NodeJS.ProcessEnv | undefined
  readonly skillsDir?: string | undefined
  readonly pythonBin?: string | undefined
}

export interface LoopXInitSummary {
  readonly cliVersion: string
  readonly cliInstalled: boolean
  readonly skillsInstalled: true
  readonly hostSurface: typeof HOST_SURFACE
}

function workflowArgs(
  command: LoopXCommand,
  skillsDir: string,
  mode: 'inspect' | 'install',
): string[] {
  return [
    '--format',
    'json',
    'workflow-skills',
    ...(mode === 'install' ? ['--install'] : []),
    '--skills-dir',
    skillsDir,
    '--host-surface',
    HOST_SURFACE,
    '--cli-bin',
    command.skillCommand,
  ]
}

function workflowPayload(payload: Record<string, unknown>): boolean {
  return payload.schema_version === WORKFLOW_SCHEMA
}

async function compatible(
  command: LoopXCommand,
  skillsDir: string,
  options: LoopXInitOptions,
): Promise<boolean> {
  try {
    const payload = await runJsonCommand(
      command,
      workflowArgs(command, skillsDir, 'inspect'),
      {
        runner: options.runner,
        signal: options.signal,
        env: options.env,
        attempts: 1,
        validate: workflowPayload,
      },
    )
    return payload.ok === true
      && payload.operation === 'inspect'
      && payload.host_surface === HOST_SURFACE
      && typeof payload.install_required === 'boolean'
  } catch (error: unknown) {
    if (error instanceof LoopXCliError && error.kind === 'aborted') throw error
    return false
  }
}

async function installCli(options: LoopXInitOptions): Promise<void> {
  const runner = options.runner ?? runFile
  const python = options.pythonBin
    ?? options.env?.PYTHON_BIN
    ?? process.env.PYTHON_BIN
    ?? 'python3'
  let result
  try {
    result = await runner(
      python,
      ['-m', 'pip', 'install', '--upgrade', 'loopx'],
      {
        env: options.env,
        signal: options.signal,
        timeoutMs: 120_000,
        maxOutputBytes: 1024 * 1024,
      },
    )
  } catch (error: unknown) {
    if (error instanceof LoopXCliError && error.kind === 'aborted') throw error
    const kind = error instanceof LoopXCliError ? error.kind : 'transport'
    throw new LoopXInitError('install_cli', 'LoopX CLI installation failed', kind)
  }
  if (result.exitCode !== 0) {
    throw new LoopXInitError('install_cli', 'LoopX CLI installation failed', 'exit')
  }
}

/** Install/upgrade LoopX once when needed, then install and verify DSH skills. */
export async function initializeLoopX(options: LoopXInitOptions = {}): Promise<LoopXInitSummary> {
  const configuredAgentsHome = options.env?.DSH_AGENTS_HOME
    ?? process.env.DSH_AGENTS_HOME
  const agentsHome = configuredAgentsHome?.trim()
    ? configuredAgentsHome
    : join(homedir(), '.agents')
  const skillsDir = resolve(options.skillsDir ?? join(agentsHome, 'skills'))
  let command: LoopXCommand | undefined
  try {
    command = await resolveLoopXCommand(options)
  } catch (error: unknown) {
    if (error instanceof LoopXCliError && error.kind === 'aborted') throw error
  }

  let cliInstalled = false
  if (command === undefined || !(await compatible(command, skillsDir, options))) {
    await installCli(options)
    cliInstalled = true
    try {
      command = await resolveLoopXCommand(options)
    } catch (error: unknown) {
      if (error instanceof LoopXCliError && error.kind === 'aborted') throw error
      const kind = error instanceof LoopXCliError ? error.kind : 'transport'
      throw new LoopXInitError(
        'probe',
        'LoopX was installed but no compatible CLI could be resolved',
        kind,
      )
    }
    if (!(await compatible(command, skillsDir, options))) {
      throw new LoopXInitError(
        'probe',
        'The installed LoopX CLI does not support the DSH-native skill contract',
        'incompatible',
      )
    }
  }

  let installed: Record<string, unknown>
  try {
    installed = await runJsonCommand(
      command,
      workflowArgs(command, skillsDir, 'install'),
      {
        runner: options.runner,
        signal: options.signal,
        env: options.env,
        attempts: 1,
        timeoutMs: 60_000,
        validate: workflowPayload,
      },
    )
  } catch (error: unknown) {
    if (error instanceof LoopXCliError && error.kind === 'aborted') throw error
    const kind = error instanceof LoopXCliError ? error.kind : 'transport'
    throw new LoopXInitError('install_skills', 'LoopX skill installation failed', kind)
  }
  if (installed.ok !== true || installed.operation !== 'install'
    || installed.host_surface !== HOST_SURFACE) {
    throw new LoopXInitError(
      'install_skills',
      'LoopX did not confirm the DSH-native skill installation',
      'typed_failure',
    )
  }

  let readback: Record<string, unknown>
  try {
    readback = await runJsonCommand(
      command,
      workflowArgs(command, skillsDir, 'inspect'),
      {
        runner: options.runner,
        signal: options.signal,
        env: options.env,
        attempts: 1,
        validate: workflowPayload,
      },
    )
  } catch (error: unknown) {
    if (error instanceof LoopXCliError && error.kind === 'aborted') throw error
    const kind = error instanceof LoopXCliError ? error.kind : 'transport'
    throw new LoopXInitError('readback', 'LoopX skill readback failed', kind)
  }
  if (readback.ok !== true || readback.operation !== 'inspect'
    || readback.host_surface !== HOST_SURFACE
    || readback.install_required !== false) {
    throw new LoopXInitError(
      'readback',
      'LoopX skills were not verified after installation',
      'readback_mismatch',
    )
  }

  return {
    cliVersion: command.version,
    cliInstalled,
    skillsInstalled: true,
    hostSurface: HOST_SURFACE,
  }
}

function commandFailure(error: unknown): CommandResult {
  if (error instanceof LoopXCliError && error.kind === 'aborted') {
    return { kind: 'error', text: 'LOOPX_INIT_CANCELLED: initialization was cancelled.' }
  }
  if (error instanceof LoopXInitError) {
    const recovery = error.stage === 'install_cli'
      ? 'Run `python3 -m pip install --upgrade loopx` manually for diagnostics, then retry `/loopx-init`.'
      : error.stage === 'probe'
        ? 'Verify `loopx --version`, then retry `/loopx-init`.'
        : 'Run `loopx workflow-skills --help` for diagnostics, then retry `/loopx-init`.'
    return {
      kind: 'error',
      text: [
        `LOOPX_INIT_FAILED: stage=${error.stage}; kind=${error.causeKind ?? 'unknown'}.`,
        `${error.message}.`,
        recovery,
      ].join(' '),
    }
  }
  return {
    kind: 'error',
    text: 'LOOPX_INIT_FAILED: unexpected initialization failure.',
  }
}

export function apply(ctx: Context): void {
  ctx.commands.register({
    name: 'loopx-init',
    description: 'install or upgrade LoopX and install the DSH LoopX skills',
    recordInput: false,
    async handler(invocation): Promise<CommandResult> {
      if (invocation.rawInput.trim().length > 0) {
        return { kind: 'error', text: 'Usage: /loopx-init' }
      }
      try {
        const result = await initializeLoopX({ signal: invocation.signal })
        return {
          kind: 'success',
          text: [
            `LoopX ready (${result.cliVersion}).`,
            result.cliInstalled ? 'CLI installed or upgraded.' : 'CLI already compatible.',
            'DSH LoopX skills installed and verified.',
            'Use the `loopx` skill with your task; restart DSH if this session does not refresh skills.',
          ].join(' '),
        }
      } catch (error: unknown) {
        return commandFailure(error)
      }
    },
  })
}

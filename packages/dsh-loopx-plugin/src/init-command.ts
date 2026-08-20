import { randomUUID } from 'node:crypto'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type { Agent } from '@deepseek-ai/dsh-agent'
import type { CommandResult } from '@deepseek-ai/dsh-commands'
import type { UserMessage } from '@deepseek-ai/dsh-session'
import {
  LoopXCliError,
  resolveLoopXCommand,
  runFile,
  runJsonCommand,
} from './cli.ts'
import type { FileRunner, LoopXCliErrorKind, LoopXCommand } from './cli.ts'

export const name = 'dsh-loopx-init-command'
export const inject = ['commands']

const HOST_SURFACE = 'deepseek-harness-native'
const WORKFLOW_SCHEMA = 'loopx_workflow_skill_install_v0'
const INIT_SOURCE_ID = 'dsh-loopx-plugin/init-command'
const MAX_FOLLOWUP_TEXT_CHARS = 800
const PACKAGED_SKILL_IDS = Object.freeze([
  'loopx-project',
  'loopx-pr-program',
  'loopx-pr-review',
  'loopx-doc-registry',
  'loopx-self-repair',
])

type PackagedSkillStatus = 'created' | 'updated' | 'unchanged'
type EntrySkillStatus = PackagedSkillStatus | 'upgraded_legacy_managed'

export type LoopXInitStage = 'probe' | 'install_cli' | 'install_skills' | 'readback'
export type LoopXInitCauseKind = LoopXCliErrorKind | 'incompatible' | 'readback_mismatch'

export class LoopXInitError extends Error {
  constructor(
    readonly stage: LoopXInitStage,
    message: string,
    readonly causeKind?: LoopXInitCauseKind | undefined,
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
  readonly skillsChanged: boolean
  readonly hostSurface: typeof HOST_SURFACE
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined
}

function packagedSkillStatus(value: unknown): value is PackagedSkillStatus {
  return value === 'created' || value === 'updated' || value === 'unchanged'
}

function entrySkillStatus(value: unknown): value is EntrySkillStatus {
  return packagedSkillStatus(value) || value === 'upgraded_legacy_managed'
}

function installedSkillsChanged(payload: Record<string, unknown>): boolean | undefined {
  const installed = record(payload.installed)
  const entry = record(payload.entry)
  if (installed === undefined || entry === undefined) return undefined
  const statuses = Object.values(installed)
  if (statuses.length === 0 || !statuses.every(packagedSkillStatus)) return undefined
  if (!PACKAGED_SKILL_IDS.every(skillId => packagedSkillStatus(installed[skillId]))) {
    return undefined
  }
  if (!entrySkillStatus(entry.status)) return undefined
  return statuses.some(status => status !== 'unchanged')
    || entry.status !== 'unchanged'
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
  const skillsChanged = installedSkillsChanged(installed)
  if (skillsChanged === undefined) {
    throw new LoopXInitError(
      'install_skills',
      'LoopX returned incomplete DSH-native skill mutation status',
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
    skillsChanged,
    hostSurface: HOST_SURFACE,
  }
}

function recoveryForStage(stage: LoopXInitStage): string {
  return stage === 'install_cli'
    ? 'Run `python3 -m pip install --upgrade loopx` manually for diagnostics, then retry `/loopx-init`.'
    : stage === 'probe'
      ? 'Verify `loopx --version`, then retry `/loopx-init`.'
      : 'Run `loopx workflow-skills --help` for diagnostics, then retry `/loopx-init`.'
}

function commandFailure(error: unknown): CommandResult {
  if (error instanceof LoopXCliError && error.kind === 'aborted') {
    return { kind: 'error', text: 'LOOPX_INIT_CANCELLED: initialization was cancelled.' }
  }
  if (error instanceof LoopXInitError) {
    return {
      kind: 'error',
      text: [
        `LOOPX_INIT_FAILED: stage=${error.stage}; kind=${error.causeKind ?? 'unknown'}.`,
        `${error.message}.`,
        recoveryForStage(error.stage),
      ].join(' '),
    }
  }
  return {
    kind: 'error',
    text: 'LOOPX_INIT_FAILED: unexpected initialization failure.',
  }
}

function successResult(result: LoopXInitSummary): CommandResult {
  return {
    kind: 'success',
    text: [
      `LoopX ready (${result.cliVersion}).`,
      result.cliInstalled ? 'CLI installed or upgraded.' : 'CLI already compatible.',
      result.skillsChanged
        ? 'DSH LoopX skills installed or updated and verified.'
        : 'DSH LoopX skills already current and verified.',
      result.skillsChanged
        ? 'Restart DSH once to reload the changed skills, then use the `loopx` skill with your task.'
        : 'No DSH restart is required; use the `loopx` skill with your task.',
    ].join(' '),
  }
}

function safeVersion(version: string): string {
  return /^loopx [A-Za-z0-9][A-Za-z0-9._+!-]{0,63}$/u.test(version)
    ? version
    : 'loopx (compatible version verified)'
}

function followupMessage(text: string): UserMessage {
  const bounded = text.length <= MAX_FOLLOWUP_TEXT_CHARS
    ? text
    : `${text.slice(0, MAX_FOLLOWUP_TEXT_CHARS - 1)}…`
  const content: UserMessage['content'] = Object.freeze([
    Object.freeze({ type: 'text' as const, text: bounded }),
  ]) as UserMessage['content']
  return Object.freeze({
    id: randomUUID() as UserMessage['id'],
    role: 'user' as const,
    content,
    source: Object.freeze({ kind: 'plugin' as const, plugin: INIT_SOURCE_ID }),
  })
}

function startFollowup(): UserMessage {
  return followupMessage([
    'LoopX initialization has started.',
    'Briefly welcome the user to LoopX and say that the LoopX CLI and DSH workflow skills are being checked or installed.',
    'Do not call tools, run commands, claim initialization is complete, or add diagnostics.',
  ].join(' '))
}

function successFollowup(result: LoopXInitSummary): UserMessage {
  return followupMessage([
    'LoopX initialization finished successfully.',
    `Report these authoritative facts briefly: version ${safeVersion(result.cliVersion)};`,
    result.cliInstalled ? 'the CLI was installed or upgraded;' : 'the CLI was already compatible;',
    result.skillsChanged
      ? 'DSH workflow skills were installed or updated and verified; restart DSH once to reload the changed skills.'
      : 'DSH workflow skills were already current and verified; no DSH restart is required.',
    'Do not call tools, run commands, reinstall anything, or add diagnostics.',
  ].join(' '))
}

function failureFollowup(error: unknown): UserMessage {
  if (error instanceof LoopXInitError) {
    return followupMessage([
      'LoopX initialization failed.',
      `Report briefly that the safe failure stage is ${error.stage} and the cause kind is ${error.causeKind ?? 'unknown'}.`,
      recoveryForStage(error.stage),
      'Do not claim LoopX is ready or that DSH should restart. Do not call tools, run commands, reinstall, or add diagnostics.',
    ].join(' '))
  }
  return followupMessage([
    'LoopX initialization failed unexpectedly.',
    'Briefly tell the user to read the authoritative native command result and retry `/loopx-init`.',
    'Do not claim LoopX is ready or that DSH should restart. Do not call tools, run commands, reinstall, or add diagnostics.',
  ].join(' '))
}

function queueFollowup(
  agent: Agent,
  message: UserMessage,
  phase: 'start' | 'complete',
  warn: (message: string) => void,
): void {
  try {
    agent.followup(message)
  } catch {
    try {
      warn(`dsh-loopx-init-command: could not queue ${phase} followup`)
    } catch {
      // Diagnostics must never become part of the initialization outcome.
    }
  }
}

function cancelled(error: unknown, signal: AbortSignal): boolean {
  return signal.aborted || (error instanceof LoopXCliError && error.kind === 'aborted')
}

export function apply(ctx: Context, options: LoopXInitOptions = {}): void {
  ctx.commands.register({
    name: 'loopx-init',
    description: 'install or upgrade LoopX and install the DSH LoopX skills',
    recordInput: false,
    async handler(invocation): Promise<CommandResult> {
      if (invocation.rawInput.trim().length > 0) {
        return { kind: 'error', text: 'Usage: /loopx-init' }
      }
      const warn = (message: string): void => { ctx.logger.warn(message) }
      queueFollowup(invocation.agent, startFollowup(), 'start', warn)
      try {
        const result = await initializeLoopX({ ...options, signal: invocation.signal })
        const commandResult = successResult(result)
        if (!invocation.signal.aborted) {
          queueFollowup(invocation.agent, successFollowup(result), 'complete', warn)
        }
        return commandResult
      } catch (error: unknown) {
        const commandResult = commandFailure(error)
        if (!cancelled(error, invocation.signal)) {
          queueFollowup(invocation.agent, failureFollowup(error), 'complete', warn)
        }
        return commandResult
      }
    },
  })
}

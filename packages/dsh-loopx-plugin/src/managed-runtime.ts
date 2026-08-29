import { stat } from 'node:fs/promises'
import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { resolveLoopXCommand, runFile } from './cli.ts'
import type { FileRunner, LoopXCommand } from './cli.ts'

export const MANAGED_LAUNCHER_NAME = 'loopx_cli.py'
export const MANAGED_SITE_PACKAGES_NAME = 'site-packages'

const PYTHON_CANDIDATES = Object.freeze([
  'python3',
  'python3.14',
  'python3.13',
  'python3.12',
  'python3.11',
])

export interface LoopXRuntimeOptions {
  readonly runner?: FileRunner | undefined
  readonly signal?: AbortSignal | undefined
  readonly env?: NodeJS.ProcessEnv | undefined
  readonly runtimeDir?: string | undefined
  readonly pythonBin?: string | undefined
}

export function configuredPluginPython(
  options: LoopXRuntimeOptions,
): string | undefined {
  return options.pythonBin
    ?? options.env?.PYTHON_BIN
    ?? process.env.PYTHON_BIN
}

export function pluginPythonCandidates(
  options: LoopXRuntimeOptions,
): readonly string[] {
  const explicit = configuredPluginPython(options)
  return explicit === undefined ? PYTHON_CANDIDATES : [explicit]
}

export function pluginAgentsHome(options: LoopXRuntimeOptions): string {
  const configured = options.env?.DSH_AGENTS_HOME
    ?? process.env.DSH_AGENTS_HOME
  return configured?.trim() ? configured : join(homedir(), '.agents')
}

export function pluginRuntimeDir(options: LoopXRuntimeOptions): string {
  return resolve(
    options.runtimeDir
      ?? join(pluginAgentsHome(options), 'runtime', 'dsh-loopx-plugin'),
  )
}

/** Resolve the exact CLI surface shared by bootstrap, Driver, and GoalBar. */
export async function resolvePluginLoopXCommand(
  options: LoopXRuntimeOptions = {},
): Promise<LoopXCommand> {
  const launcherPath = join(pluginRuntimeDir(options), MANAGED_LAUNCHER_NAME)
  const env = options.pythonBin === undefined
    ? options.env
    : { ...(options.env ?? process.env), PYTHON_BIN: options.pythonBin }
  const hasManagedLauncher = await stat(launcherPath).then(
    value => value.isFile(),
    () => false,
  )
  return resolveLoopXCommand({
    ...options,
    runner: options.runner ?? runFile,
    env,
    managedLauncher: hasManagedLauncher
      ? { path: launcherPath, pythonBins: pluginPythonCandidates(options) }
      : undefined,
  })
}

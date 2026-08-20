#!/usr/bin/env node

import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtemp, readFile, realpath, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dshBin = process.env.DSH_BIN || join(packageRoot, 'node_modules', '.bin', 'dsh')
const rows = [
  ['loopx-init-command', 'dsh-loopx-plugin/init-command'],
  ['loopx-driver', 'dsh-loopx-plugin/driver'],
]
function specs(argv) {
  argv = argv.filter(value => value !== '--')
  const result = []
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index]
    const value = argv[index + 1]
    if ((flag !== '--package-path' && flag !== '--tarball') || !value) {
      throw new Error('use --package-path PATH and/or --tarball PATH')
    }
    result.push({ kind: flag === '--tarball' ? 'tarball' : 'path', value: resolve(value) })
  }
  if (!result.length) throw new Error('one package input is required')
  return result
}

function run(file, args, env) {
  const result = spawnSync(file, args, {
    cwd: packageRoot,
    env,
    encoding: 'utf8',
    maxBuffer: 8 * 1024 * 1024,
    shell: false,
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`${file} ${args.join(' ')} failed\n${result.stdout}\n${result.stderr}`)
  }
  return result.stdout
}

function assertConfig(dump) {
  const packageNames = dump
    .split(/\r?\n/u)
    .map(line => line.match(/^\s*name:\s+(\S+)\s*$/u)?.[1])
    .filter(name => name?.startsWith('dsh-loopx-plugin/'))
  assert.deepEqual(packageNames, rows.map(([, module]) => module))
  let previous = -1
  for (const [id, module] of rows) {
    const position = dump.indexOf(`id: ${id}`)
    assert(position > previous, `missing or unordered ${id}`)
    assert(dump.includes(`name: ${module}`), `missing ${module}`)
    previous = position
  }
}

function assertTarball(path) {
  const entries = run('tar', ['-tf', path], process.env).trim().split('\n')
  for (const required of [
    'package/package.json',
    'package/LICENSE',
    'package/cordis.patch.yml',
    'package/lib/init-command.js',
    'package/lib/driver.js',
    'package/lib/types/init-command.d.ts',
    'package/lib/types/driver.d.ts',
  ]) assert(entries.includes(required), `tarball missing ${required}`)
  for (const obsolete of ['service', 'command', 'tools', 'coordinator', 'receipts']) {
    assert(!entries.includes(`package/lib/${obsolete}.js`), `tarball contains ${obsolete}`)
  }
}

async function exerciseInstalled(installed) {
  const requireFromPlugin = createRequire(join(installed, 'package.json'))
  const [initModule, driverModule] = await Promise.all([
    import(pathToFileURL(requireFromPlugin.resolve('dsh-loopx-plugin/init-command')).href),
    import(pathToFileURL(requireFromPlugin.resolve('dsh-loopx-plugin/driver')).href),
  ])
  const commands = new Map()
  initModule.apply({ commands: { register: definition => commands.set(definition.name, definition) } })
  assert.deepEqual([...commands.keys()], ['loopx-init'])
  const command = commands.get('loopx-init')
  assert.equal(command.recordInput, false)
  const followups = []
  const agent = { followup: message => followups.push(message) }
  const usage = await command.handler({
    agent,
    rawInput: ' unexpected',
    signal: new AbortController().signal,
  })
  assert.deepEqual(usage, { kind: 'error', text: 'Usage: /loopx-init' })
  assert.equal(followups.length, 0)

  const cancelledSignal = new AbortController()
  cancelledSignal.abort()
  const cancelled = await command.handler({
    agent,
    rawInput: '',
    signal: cancelledSignal.signal,
  })
  assert.deepEqual(cancelled, {
    kind: 'error',
    text: 'LOOPX_INIT_CANCELLED: initialization was cancelled.',
  })
  assert.equal(followups.length, 1)
  assert.equal(followups[0].role, 'user')
  assert.deepEqual(followups[0].source, {
    kind: 'plugin',
    plugin: 'dsh-loopx-plugin/init-command',
  })
  assert.notDeepEqual(followups[0].source, {
    kind: 'plugin',
    plugin: 'dsh-loopx-plugin/driver',
  })
  assert.equal(typeof driverModule.LoopXContinuationDriver, 'function')
  assert.equal(driverModule.inject.join(','), 'agents')
}

async function main() {
  const inputs = specs(process.argv.slice(2))
  for (const [index, spec] of inputs.entries()) {
    if (spec.kind === 'tarball') assertTarball(spec.value)
    const home = await mkdtemp(join(tmpdir(), `dsh-loopx-${index + 1}-`))
    const env = { ...process.env, DSH_HOME: home }
    try {
      const install = [spec.value]
      run(dshBin, [
        'plugin', '--profile', 'web', 'add', ...install,
        spec.kind === 'tarball' ? '--prefer-offline' : '--offline', '--ignore-scripts',
      ], env)
      const dump = run(dshBin, ['--profile', 'web', '--dump-config'], env)
      assertConfig(dump)
      const installed = await realpath(join(home, 'profiles', 'web', 'node_modules', 'dsh-loopx-plugin'))
      const manifest = JSON.parse(await readFile(join(installed, 'package.json'), 'utf8'))
      assert.equal(manifest.name, 'dsh-loopx-plugin')
      await exerciseInstalled(installed)
      run(dshBin, ['plugin', '--profile', 'web', 'remove', 'dsh-loopx-plugin'], env)
      const removed = run(dshBin, ['--profile', 'web', '--dump-config'], env)
      for (const [id] of rows) assert(!removed.includes(`id: ${id}`), `remove retained ${id}`)
    } finally {
      await rm(home, { recursive: true, force: true })
    }
  }
  process.stdout.write(`dsh-loopx profile smoke passed (${inputs.map(item => item.kind).join(', ')})\n`)
}

await main()

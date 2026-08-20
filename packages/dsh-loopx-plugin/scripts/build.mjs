#!/usr/bin/env node

import { spawnSync } from 'node:child_process'
import { rmSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)
const typescriptRoot = dirname(require.resolve('typescript/package.json'))
const tsdownRoot = dirname(require.resolve('tsdown/package.json'))

function run(modulePath, args) {
  const result = spawnSync(process.execPath, [modulePath, ...args], {
    cwd: packageRoot,
    stdio: 'inherit',
    shell: false,
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}

rmSync(join(packageRoot, 'lib'), { recursive: true, force: true })
rmSync(join(packageRoot, 'build-temp'), { recursive: true, force: true })
try {
  run(join(typescriptRoot, 'bin', 'tsc'), ['-p', 'tsconfig.build.json'])
  run(join(tsdownRoot, 'dist', 'run.mjs'), [])
} finally {
  rmSync(join(packageRoot, 'build-temp'), { recursive: true, force: true })
}

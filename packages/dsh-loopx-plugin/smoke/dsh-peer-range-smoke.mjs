#!/usr/bin/env node

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const manifest = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'))

function versionTuple(value) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/u.exec(value)
  assert(match, `unsupported version ${value}`)
  return {
    major: Number(match[1]),
    minor: Number(match[2]),
    patch: Number(match[3]),
    prerelease: match[4] ?? null,
  }
}

function supportsPrerelease(range, version) {
  const tuple = versionTuple(version)
  if (tuple.prerelease === null) return true
  const tuplePrefix = `${tuple.major}.${tuple.minor}.${tuple.patch}-`
  return range.split('||').some(branch => branch.includes(tuplePrefix))
}

for (const [name, range] of Object.entries(manifest.peerDependencies ?? {})) {
  if (!name.startsWith('@deepseek-ai/')) continue
  const testedVersion = manifest.devDependencies?.[name]
  assert(testedVersion, `missing tested version for official peer ${name}`)
  assert(
    supportsPrerelease(range, testedVersion),
    `${name} tested version ${testedVersion} is excluded by peer range ${range}`,
  )
}

process.stdout.write('dsh-loopx peer range smoke passed\n')

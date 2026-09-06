#!/usr/bin/env bash
set -euo pipefail

demo_dir="${1:-/tmp/dsh-loopx-replan-demo}"

if [[ -e "$demo_dir" ]]; then
  echo "Refusing to overwrite existing path: $demo_dir" >&2
  exit 2
fi

mkdir -p "$demo_dir/src" "$demo_dir/test"

printf '%s\n' \
  '{' \
  '  "name": "structured-logging-demo",' \
  '  "version": "0.1.0",' \
  '  "private": true,' \
  '  "type": "module",' \
  '  "scripts": { "test": "node --test", "start": "node src/cli.js" }' \
  '}' > "$demo_dir/package.json"

printf '%s\n' \
  'const command = process.argv[2] ?? "status";' \
  '' \
  'if (command === "fail") {' \
  '  console.error("failed");' \
  '  process.exitCode = 1;' \
  '} else {' \
  '  console.log("completed");' \
  '}' > "$demo_dir/src/cli.js"

printf '%s\n' \
  '# Structured Logging Demo' \
  '' \
  'Choose Pino, Consola, or Roarr using maintenance, JSON output, TypeScript' \
  'support, dependency footprint, and migration cost. Record evidence, keep' \
  'status and fail semantics, and add behavior tests.' \
  > "$demo_dir/README.md"

printf '%s\n' 'node_modules/' '.loopx/' '.codex/goals/' > "$demo_dir/.gitignore"

git -C "$demo_dir" init -q
git -C "$demo_dir" add README.md package.json src/cli.js .gitignore
git -C "$demo_dir" -c user.name='LoopX Demo' \
  -c user.email='demo@example.invalid' commit -qm 'chore: seed demo'

echo "Fixture ready: $demo_dir"
echo "Next: cd '$demo_dir' && dsh --profile web --port 0"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PACKAGE_JSON="$SCRIPT_DIR/package.json"
OUTPUT_DIR="$SCRIPT_DIR/output"
PACKAGE_NAME="dsh-loopx-plugin"
PROFILE_NAME="web"

usage() {
  cat <<'EOF'
Usage: ./install.sh [--help]

Build and install the DSH LoopX host plugin into the DSH web profile. This
installs only `/loopx-init` and the same-session Driver. LoopX itself is not a
prerequisite; run `/loopx-init` inside DSH afterward to install or upgrade the
LoopX CLI and its DSH skills.

Environment:
  DSH_BIN=/path/to/dsh  Override the package-local DSH CLI.
EOF
}

case "${1:-}" in
  -h|--help)
    [[ "$#" -eq 1 ]] || { echo 'install: --help does not accept arguments' >&2; exit 2; }
    usage
    exit 0
    ;;
  '') ;;
  *)
    echo "install: unsupported argument: $1" >&2
    usage >&2
    exit 2
    ;;
esac
[[ "$#" -le 1 ]] || { echo 'install: positional arguments are not supported' >&2; exit 2; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "install: required command not found on PATH: $1" >&2
    exit 2
  }
}

need node
need pnpm

node -e '
  const [major, minor] = process.versions.node.split(".").map(Number)
  if (!((major === 22 && minor >= 19) || major >= 24)) process.exit(1)
' || {
  echo "install: Node.js 22.19+ (excluding Node.js 23) is required" >&2
  exit 2
}
pnpm_version="$(pnpm --version)"
pnpm_major="${pnpm_version%%.*}"
[[ "$pnpm_major" =~ ^[0-9]+$ ]] && ((pnpm_major >= 9)) || {
  echo "install: pnpm 9 or newer is required" >&2
  exit 2
}

PACKAGE_VERSION="$(
  node -e '
    const fs = require("node:fs")
    const manifest = JSON.parse(fs.readFileSync(process.argv[1], "utf8"))
    if (manifest.name !== "dsh-loopx-plugin") throw new TypeError("unexpected package name")
    if (typeof manifest.version !== "string" || !manifest.version) throw new TypeError("missing version")
    process.stdout.write(manifest.version)
  ' "$PACKAGE_JSON"
)"
[[ "$PACKAGE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]] || {
  echo "install: invalid package version: $PACKAGE_VERSION" >&2
  exit 2
}

echo "install: preparing $PACKAGE_NAME@$PACKAGE_VERSION"
CI=true pnpm --dir "$SCRIPT_DIR" install --frozen-lockfile --ignore-scripts

if [[ -n "${DSH_BIN:-}" ]]; then
  dsh_bin="$(command -v "$DSH_BIN" 2>/dev/null || true)"
  [[ -n "$dsh_bin" ]] || { echo "install: DSH_BIN is not executable: $DSH_BIN" >&2; exit 2; }
else
  dsh_bin="$SCRIPT_DIR/node_modules/.bin/dsh"
fi
[[ -x "$dsh_bin" ]] || { echo "install: DSH CLI is unavailable: $dsh_bin" >&2; exit 2; }
"$dsh_bin" --version >/dev/null

mkdir -p "$OUTPUT_DIR"
tarball="$OUTPUT_DIR/$PACKAGE_NAME-$PACKAGE_VERSION.tgz"
pnpm --dir "$SCRIPT_DIR" pack --out "$tarball"
[[ -s "$tarball" ]] || { echo "install: expected tarball was not created" >&2; exit 1; }

"$dsh_bin" plugin --profile "$PROFILE_NAME" add "$tarball" --ignore-scripts
profile_dump="$("$dsh_bin" --profile "$PROFILE_NAME" --dump-config)" || {
  echo "install: DSH profile $PROFILE_NAME could not be read back" >&2
  exit 1
}

printf '%s' "$profile_dump" | node -e '
  const fs = require("node:fs")
  const dump = fs.readFileSync(0, "utf8")
  const rows = [
    ["loopx-init-command", "dsh-loopx-plugin/init-command"],
    ["loopx-driver", "dsh-loopx-plugin/driver"],
  ]
  const packageNames = dump
    .split(/\r?\n/u)
    .map(line => line.match(/^\s*name:\s+(\S+)\s*$/u)?.[1])
    .filter(name => name?.startsWith("dsh-loopx-plugin/"))
  const expectedNames = rows.map(([, name]) => name)
  if (JSON.stringify(packageNames) !== JSON.stringify(expectedNames)) {
    throw new Error(`unexpected package rows: ${packageNames.join(",")}`)
  }
  let previous = -1
  for (const [id, name] of rows) {
    const position = dump.indexOf(`id: ${id}`)
    if (position <= previous) throw new Error(`missing or unordered row ${id}`)
    if (!dump.includes(`name: ${name}`)) throw new Error(`missing module ${name}`)
    previous = position
  }
' || {
  echo 'install: DSH profile readback did not match the two-face plugin contract' >&2
  exit 1
}

echo "install: installed and verified $PACKAGE_NAME@$PACKAGE_VERSION"
echo "install: next, run /loopx-init inside DSH"
echo "install: artifact retained at $tarball"

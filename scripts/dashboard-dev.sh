#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DASHBOARD_DIR="${REPO_ROOT}/apps/presentation/dashboard"
STATUS_PID=""
CHAT_PID=""
PYTHON_BIN=""
CODEX_BIN="codex"
CLAUDE_BIN="claude"

node_is_supported() {
  "$1" -e '
const [major, minor] = process.versions.node.split(".").map(Number);
const supported = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22;
process.exit(supported ? 0 : 1);
' 2>/dev/null
}

select_node_runtime() {
  if command -v node >/dev/null 2>&1 \
    && command -v npm >/dev/null 2>&1 \
    && node_is_supported "$(command -v node)"; then
    return 0
  fi

  local nvm_root="${NVM_DIR:-${HOME}/.nvm}"
  local node_candidate
  local npm_candidate
  for node_candidate in "${nvm_root}"/versions/node/*/bin/node; do
    [ -x "${node_candidate}" ] || continue
    npm_candidate="$(dirname "${node_candidate}")/npm"
    if [ -x "${npm_candidate}" ] && node_is_supported "${node_candidate}"; then
      export PATH="$(dirname "${node_candidate}"):${PATH}"
      echo "Using compatible Node.js from $(dirname "${node_candidate}")"
      return 0
    fi
  done

  echo "LoopX dashboard requires Node.js 20.19+ or 22.12+. Node.js 22 is recommended." >&2
  echo "Install Node.js 22, then retry: loopx dashboard" >&2
  return 1
}

if ! select_node_runtime; then
  exit 1
fi

if [ ! -x "${DASHBOARD_DIR}/node_modules/.bin/vite" ]; then
  echo "Installing LoopX dashboard dependencies (first run only)..."
  cd "${DASHBOARD_DIR}"
  if ! npm ci; then
    echo "LoopX dashboard dependency installation failed." >&2
    exit 1
  fi
fi

wait_for_service() {
  local service_name="$1"
  local service_url="$2"
  "${PYTHON_BIN}" - "${service_name}" "${service_url}" <<'PY'
import sys
import time
import urllib.error
import urllib.request

name, url = sys.argv[1:]
deadline = time.monotonic() + 15
last_error = "service did not respond"
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                raise SystemExit(0)
            last_error = f"HTTP {response.status}"
    except (OSError, urllib.error.URLError) as exc:
        last_error = str(exc)
    time.sleep(0.1)
print(f"LoopX {name} service failed to start: {last_error}", file=sys.stderr)
raise SystemExit(1)
PY
}

cleanup() {
  if [ -n "${STATUS_PID}" ]; then
    kill "${STATUS_PID}" 2>/dev/null || true
  fi
  if [ -n "${CHAT_PID}" ]; then
    kill "${CHAT_PID}" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "${candidate}" >/dev/null 2>&1 \
    && "${candidate}" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [ -z "${PYTHON_BIN}" ]; then
  echo "LoopX requires Python 3.11 or newer to start status and Chat services." >&2
  echo "Starting the Vite UI only; use the bundled example until Python is upgraded." >&2
  cd "${DASHBOARD_DIR}"
  exec npm run dev:web
fi

resolve_agent_binary() {
  local binary_name="$1"
  local discovered=""
  if command -v "${binary_name}" >/dev/null 2>&1; then
    command -v "${binary_name}"
    return 0
  fi
  for discovered in \
    "${HOME}/.npm-global/bin/${binary_name}" \
    "${HOME}/.local/bin/${binary_name}" \
    "${HOME}"/.nvm/versions/node/*/bin/"${binary_name}"; do
    if [ -x "${discovered}" ]; then
      printf '%s\n' "${discovered}"
      return 0
    fi
  done
  printf '%s\n' "${binary_name}"
}

CODEX_BIN="$(resolve_agent_binary codex)"
CLAUDE_BIN="$(resolve_agent_binary claude)"
echo "LoopX Agent executables: Codex=${CODEX_BIN}; Claude Code=${CLAUDE_BIN}"

cd "${REPO_ROOT}"
"${PYTHON_BIN}" -m loopx.cli serve-status \
  --global-registry \
  --host 127.0.0.1 \
  --port 8766 \
  --limit 80 &
STATUS_PID=$!

"${PYTHON_BIN}" -m loopx.cli chat \
  --global-registry \
  --host 127.0.0.1 \
  --port 8767 \
  --codex-bin "${CODEX_BIN}" \
  --claude-bin "${CLAUDE_BIN}" \
  --no-open &
CHAT_PID=$!

if ! wait_for_service "status" "http://127.0.0.1:8766/healthz"; then
  exit 1
fi
if ! wait_for_service "Chat" "http://127.0.0.1:8767/api/chat/capabilities"; then
  exit 1
fi

echo "LoopX dashboard services:"
echo "  UI:     http://127.0.0.1:5173/"
echo "  Status: http://127.0.0.1:8766/status.json"
echo "  Chat:   http://127.0.0.1:8767/api/chat/capabilities"

cd "${DASHBOARD_DIR}"
npm run dev:web

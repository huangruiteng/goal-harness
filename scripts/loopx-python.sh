#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

python_version_ok() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null
}

resolve_candidate() {
  local candidate="$1"
  if [[ "${candidate}" == */* ]]; then
    [ -x "${candidate}" ] && printf '%s\n' "${candidate}"
    return
  fi
  command -v "${candidate}" 2>/dev/null || true
}

select_loopx_python() {
  local candidate=""
  local resolved=""
  local configured_python=""
  local authoritative=0

  if [ -n "${LOOPX_PYTHON:-}" ]; then
    configured_python="${LOOPX_PYTHON}"
    authoritative=1
  elif [ -f "${REPO_ROOT}/.loopx-python" ]; then
    IFS= read -r configured_python <"${REPO_ROOT}/.loopx-python"
  fi

  if [ -n "${configured_python}" ]; then
    resolved="$(resolve_candidate "${configured_python}")"
    if [ -n "${resolved}" ] && python_version_ok "${resolved}"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
    if [ "${authoritative}" -eq 1 ]; then
      echo "LOOPX_PYTHON is set but does not resolve to a Python 3.11+ interpreter: ${configured_python}" >&2
      return 1
    fi
    echo "Ignoring non-functional Python recorded in .loopx-python: ${configured_python}" >&2
  fi

  for candidate in \
    "${REPO_ROOT}/.venv/bin/python" \
    python3.13 \
    python3.12 \
    python3.11 \
    python3; do
    resolved="$(resolve_candidate "${candidate}")"
    if [ -n "${resolved}" ] && python_version_ok "${resolved}"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done

  for candidate in \
    "${HOME:-}/.local/bin/python3.13" \
    "${HOME:-}/.local/bin/python3.12" \
    "${HOME:-}/.local/bin/python3.11" \
    /opt/homebrew/bin/python3.13 \
    /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.13 \
    /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11; do
    resolved="$(resolve_candidate "${candidate}")"
    if [ -n "${resolved}" ] && python_version_ok "${resolved}"; then
      printf '%s\n' "${resolved}"
      return 0
    fi
  done

  return 1
}

if [ "${1:-}" = "--exec" ]; then
  shift
  if [ "$#" -eq 0 ]; then
    echo "usage: loopx-python.sh --exec <python-arguments...>" >&2
    exit 2
  fi
  if ! PYTHON_BIN="$(select_loopx_python)"; then
    echo "LoopX requires Python 3.11 or newer." >&2
    exit 2
  fi
  exec "${PYTHON_BIN}" "$@"
fi

select_loopx_python

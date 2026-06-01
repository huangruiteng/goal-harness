#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

bin_dir="${GOAL_HARNESS_BIN_DIR:-$HOME/.local/bin}"
shell_profile="${GOAL_HARNESS_SHELL_PROFILE:-}"

if [[ -z "$shell_profile" ]]; then
  case "${SHELL:-}" in
    */zsh) shell_profile="$HOME/.zshrc" ;;
    */bash) shell_profile="$HOME/.bashrc" ;;
    *) shell_profile="$HOME/.profile" ;;
  esac
fi

mkdir -p "$bin_dir"
chmod +x "$repo_root/scripts/goal-harness"
ln -sfn "$repo_root/scripts/goal-harness" "$bin_dir/goal-harness"

if [[ -n "$shell_profile" ]]; then
  touch "$shell_profile"
  if ! grep -F "$bin_dir" "$shell_profile" >/dev/null 2>&1 \
    && ! grep -F '$HOME/.local/bin' "$shell_profile" >/dev/null 2>&1; then
    {
      printf '\n# Goal Harness local CLI\n'
      if [[ "$bin_dir" == "$HOME/.local/bin" ]]; then
        printf 'export PATH="$HOME/.local/bin:$PATH"\n'
      else
        printf 'export PATH="%s:$PATH"\n' "$bin_dir"
      fi
    } >>"$shell_profile"
  fi
fi

export PATH="$bin_dir:$PATH"
"$bin_dir/goal-harness" --help >/dev/null

cat <<EOF
goal-harness installed locally
- executable: $bin_dir/goal-harness
- profile: $shell_profile

Current shell can use it with:
  export PATH="$bin_dir:\$PATH"
  goal-harness --help
EOF

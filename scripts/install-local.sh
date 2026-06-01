#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

bin_dir="${GOAL_HARNESS_BIN_DIR:-$HOME/.local/bin}"
shell_profile="${GOAL_HARNESS_SHELL_PROFILE:-}"
codex_home="${CODEX_HOME:-$HOME/.codex}"
skills_dir="${GOAL_HARNESS_SKILLS_DIR:-$codex_home/skills}"
skill_source="$repo_root/skills/goal-harness-project"
skill_target="$skills_dir/goal-harness-project"
install_skill="${GOAL_HARNESS_INSTALL_SKILL:-1}"

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
"$bin_dir/goal-harness" doctor >/dev/null

skill_line="- skill: skipped"
if [[ "$install_skill" != "0" && -d "$skill_source" ]]; then
  mkdir -p "$skills_dir"
  if [[ -L "$skill_target" || ! -e "$skill_target" ]]; then
    ln -sfn "$skill_source" "$skill_target"
  elif [[ -d "$skill_target" ]]; then
    mkdir -p "$skill_target"
    cp "$skill_source/SKILL.md" "$skill_target/SKILL.md"
  else
    rm -f "$skill_target"
    ln -sfn "$skill_source" "$skill_target"
  fi
  skill_line="- skill: $skill_target"
fi

cat <<EOF
goal-harness installed locally
- executable: $bin_dir/goal-harness
- profile: $shell_profile
$skill_line

Current shell can use it with:
  export PATH="$bin_dir:\$PATH"
  goal-harness doctor
EOF

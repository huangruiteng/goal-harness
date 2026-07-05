from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any


SIDE_AGENT_WORKSPACE_GUARD_SCHEMA_VERSION = "side_agent_workspace_guard_v0"


def _is_same_or_child_path(path: Path, root: Path) -> bool:
    try:
        current = path.expanduser().resolve()
        target = root.expanduser().resolve()
    except OSError:
        return False
    return current == target or target in current.parents


def _git_command_output(path: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(path), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _git_worktree_root(path: Path) -> Path | None:
    output = _git_command_output(path, "rev-parse", "--show-toplevel")
    if not output:
        return None
    try:
        return Path(output).expanduser().resolve()
    except OSError:
        return None


def _git_common_dir(path: Path) -> Path | None:
    root = _git_worktree_root(path)
    if root is None:
        return None
    output = _git_command_output(root, "rev-parse", "--git-common-dir")
    if not output:
        return None
    common = Path(output).expanduser()
    if not common.is_absolute():
        common = root / common
    try:
        return common.resolve()
    except OSError:
        return None


def build_side_agent_workspace_guard(
    goal: dict[str, Any],
    agent_identity: dict[str, Any] | None,
    *,
    current_path: Path | None = None,
) -> dict[str, Any] | None:
    if not isinstance(agent_identity, dict) or agent_identity.get("role") != "side-agent":
        return None
    workspace_guard_policy = (
        goal.get("workspace_guard_policy")
        if isinstance(goal.get("workspace_guard_policy"), dict)
        else {}
    )
    if workspace_guard_policy.get("side_agent_independent_worktree_required") is False:
        return None
    repo_value = goal.get("repo") or goal.get("project") or goal.get("root")
    if not repo_value:
        return None
    repo_path = Path(str(repo_value)).expanduser()
    if not repo_path.is_absolute():
        return None
    current_path = current_path or Path.cwd()
    current_workspace = ""
    if _is_same_or_child_path(current_path, repo_path):
        current_workspace = "primary_checkout"
    else:
        primary_root = _git_worktree_root(repo_path) or repo_path
        current_root = _git_worktree_root(current_path)
        primary_common = _git_common_dir(primary_root)
        current_common = _git_common_dir(current_path) if current_root else None
        if current_root is None:
            current_workspace = "not_git_worktree"
        elif primary_common is None or current_common is None or current_common != primary_common:
            current_workspace = "foreign_git_worktree"
        elif current_root == primary_root:
            current_workspace = "primary_checkout"
    if not current_workspace:
        return None
    return {
        "schema_version": SIDE_AGENT_WORKSPACE_GUARD_SCHEMA_VERSION,
        "source": "quota.should-run",
        "action": "move_to_independent_worktree",
        "current_workspace": current_workspace,
        "required_workspace": "independent_git_worktree",
        "blocks_delivery": True,
        "agent_id": agent_identity.get("agent_id"),
        "primary_agent": agent_identity.get("primary_agent"),
        "reason": (
            "side-agent quota guard is not running from an independent worktree for "
            "the registered project; normal delivery must move before repository edits"
        ),
        "required_action": (
            "create or switch to an independent git worktree/branch for this side-agent "
            "lane, then rerun quota should-run with the same --agent-id before editing files"
        ),
    }

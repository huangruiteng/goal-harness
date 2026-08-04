#!/usr/bin/env python3
"""Smoke-test that the Claude adapter install does not mutate things it doesn't own.

Review P1:
  1. `provision_mcp_python` must NOT fall back to `pip install
     --break-system-packages mcp` against the active interpreter by default; that
     is gated behind `allow_system_pip=True`.
  2. `install_mcp` must NOT remove a legacy `goal-harness` MCP entry by default;
     that is gated behind `migrate_goal_harness=True`. It still replaces our own
     `loopx` entry.

Loads install.py as a module and records subprocess calls (no real venv/pip/claude
runs, no filesystem side effects outside a temp dir).
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "loopx" / "claude_goal_mode" / "scripts" / "install.py"
CONNECTOR = REPO_ROOT / "loopx" / "claude_goal_mode" / "scripts" / "connect.py"


def load_install():
    spec = importlib.util.spec_from_file_location("loopx_claude_installpy", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_connect():
    spec = importlib.util.spec_from_file_location("loopx_claude_connectpy", CONNECTOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def flat(cmd):
    return " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)


def recorder(get_goal_harness_rc=0):
    calls = []
    working_dirs = []

    def run(cmd, *a, **k):
        calls.append(flat(cmd))
        working_dirs.append(k.get("cwd"))
        rc = 0
        f = flat(cmd)
        if "-m venv" in f:                          # force the dedicated venv to "fail"
            rc = 1
        if "mcp get goal-harness" in f:             # simulate a legacy entry existing
            rc = get_goal_harness_rc
        return SimpleNamespace(returncode=rc, stdout="", stderr="")

    return calls, working_dirs, run


def test_no_break_system_packages_by_default():
    inst = load_install()
    with tempfile.TemporaryDirectory(prefix="loopx-prov-") as d:
        inst.MCP_VENV = Path(d) / "mcp-venv"
        inst._has_mcp = lambda py: False            # nothing importable -> reach the fallback
        inst._python_cmd = lambda: "python3"
        # default: allow_system_pip=False
        calls, _, run = recorder()
        inst.subprocess = SimpleNamespace(run=run)
        inst.provision_mcp_python(dry=False, allow_system_pip=False)
        assert not any("--break-system-packages" in c for c in calls), \
            f"must NOT touch system Python by default:\n{calls}"
        # opt-in: allow_system_pip=True DOES use it
        calls, _, run = recorder()
        inst.subprocess = SimpleNamespace(run=run)
        inst.provision_mcp_python(dry=False, allow_system_pip=True)
        assert any("--break-system-packages" in c for c in calls), \
            f"--allow-system-pip should use break-system-packages:\n{calls}"


def test_does_not_remove_goal_harness_by_default():
    inst = load_install()
    inst.shutil = SimpleNamespace(which=lambda x: "/usr/bin/claude")
    # default: migrate_goal_harness=False
    calls, _, run = recorder(get_goal_harness_rc=0)  # legacy goal-harness "exists"
    inst.subprocess = SimpleNamespace(run=run)
    inst.install_mcp(dry=False, py="python3", scope="user", migrate_goal_harness=False)
    removed_gh = [c for c in calls if "mcp remove" in c and "goal-harness" in c]
    assert not removed_gh, f"must NOT remove goal-harness by default:\n{calls}"
    assert any("mcp remove" in c and "loopx" in c for c in calls), \
        f"should still replace our own loopx entry:\n{calls}"
    # opt-in: migrate_goal_harness=True removes it
    calls, _, run = recorder(get_goal_harness_rc=0)
    inst.subprocess = SimpleNamespace(run=run)
    inst.install_mcp(dry=False, py="python3", scope="user", migrate_goal_harness=True)
    assert any("mcp remove" in c and "goal-harness" in c for c in calls), \
        f"--migrate-goal-harness should remove goal-harness:\n{calls}"


def test_project_scope_uses_project_working_directory():
    inst = load_install()
    inst.shutil = SimpleNamespace(which=lambda x: "/usr/bin/claude")
    calls, working_dirs, run = recorder(get_goal_harness_rc=1)
    inst.subprocess = SimpleNamespace(run=run)
    with tempfile.TemporaryDirectory(prefix="loopx-project-") as d:
        dir_project = Path(d) / "target"
        dir_project.mkdir()
        inst.install_mcp(
            dry=False,
            py="python3",
            scope="project",
            project_dir=dir_project,
        )
        calls_mcp = [
            (call, cwd)
            for call, cwd in zip(calls, working_dirs)
            if "/usr/bin/claude mcp" in call
        ]
        assert len(calls_mcp) == 3, f"expected remove/get/add calls:\n{calls_mcp}"
        assert all(cwd == str(dir_project) for _, cwd in calls_mcp), \
            f"project MCP calls must use the target project cwd:\n{calls_mcp}"


def test_connect_runs_installer_from_project_working_directory():
    conn = load_connect()
    calls = []

    def run(cmd, *a, **k):
        calls.append((flat(cmd), k.get("cwd")))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    conn.subprocess = SimpleNamespace(run=run)
    argv_original = conn.sys.argv
    with tempfile.TemporaryDirectory(prefix="loopx-connect-") as d:
        dir_project = Path(d) / "target"
        dir_project.mkdir()
        conn.sys.argv = [
            "connect.py",
            "--project",
            str(dir_project),
            "--goal-id",
            "goal-fixture",
            "--dry-run",
        ]
        try:
            conn.main()
        finally:
            conn.sys.argv = argv_original
        assert len(calls) == 1, f"expected one installer call:\n{calls}"
        assert Path(calls[0][1]).resolve() == dir_project.resolve(), \
            f"connector must run installer from the target project cwd:\n{calls}"


def main() -> int:
    test_no_break_system_packages_by_default()
    test_does_not_remove_goal_harness_by_default()
    test_project_scope_uses_project_working_directory()
    test_connect_runs_installer_from_project_working_directory()
    print("claude-install-no-system-mutation-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

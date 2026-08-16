from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from loopx.cli import build_parser, main
from loopx.cli_commands import support_control


def test_dashboard_command_is_registered() -> None:
    try:
        args = build_parser().parse_args(["dashboard"])
    except SystemExit:
        pytest.fail("`loopx dashboard` must be a registered top-level command")

    assert args.command == "dashboard"


def test_dashboard_command_runs_the_dashboard_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def fake_launch_dashboard() -> int:
        calls.append(True)
        return 23

    monkeypatch.setattr(
        support_control,
        "launch_dashboard",
        fake_launch_dashboard,
        raising=False,
    )

    assert main(["dashboard"]) == 23
    assert calls == [True]


def test_serve_status_still_returns_success_when_server_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(support_control, "serve_status", lambda **_kwargs: None)

    assert main(["serve-status"]) == 0


def test_dashboard_launcher_installs_missing_frontend_dependencies(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    dashboard_dir = release_root / "apps" / "presentation" / "dashboard"
    fake_bin = tmp_path / "bin"
    scripts_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    fake_bin.mkdir()
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "dashboard-dev.sh",
        scripts_dir / "dashboard-dev.sh",
    )

    npm_log = tmp_path / "npm.log"
    python_stub = fake_bin / "python3.13"
    python_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    node_stub = fake_bin / "node"
    node_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    npm_stub = fake_bin / "npm"
    npm_stub.write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$LOOPX_NPM_LOG"\n'
        'if [[ "$1" == "ci" ]]; then\n'
        "  mkdir -p node_modules/.bin\n"
        "  touch node_modules/.bin/vite\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for executable in (python_stub, node_stub, npm_stub):
        executable.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(scripts_dir / "dashboard-dev.sh")],
        cwd=release_root,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "LOOPX_NPM_LOG": str(npm_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert npm_log.read_text(encoding="utf-8").splitlines() == [
        "ci",
        "run dev:web",
    ]


def test_dashboard_launcher_selects_a_compatible_nvm_node(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    dashboard_dir = release_root / "apps" / "presentation" / "dashboard"
    fake_bin = tmp_path / "bin"
    nvm_bin = tmp_path / "nvm" / "versions" / "node" / "v22.22.2" / "bin"
    scripts_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    fake_bin.mkdir()
    nvm_bin.mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "dashboard-dev.sh",
        scripts_dir / "dashboard-dev.sh",
    )

    npm_log = tmp_path / "npm.log"
    (fake_bin / "python3.13").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "node").write_text(
        "#!/usr/bin/env bash\nexit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "npm").write_text(
        "#!/usr/bin/env bash\nexit 1\n",
        encoding="utf-8",
    )
    (nvm_bin / "node").write_text(
        "#!/usr/bin/env bash\nexit 0\n",
        encoding="utf-8",
    )
    (nvm_bin / "npm").write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$LOOPX_NPM_LOG"\n'
        'if [[ "$1" == "ci" ]]; then\n'
        "  mkdir -p node_modules/.bin\n"
        "  touch node_modules/.bin/vite\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for executable in (*fake_bin.iterdir(), *nvm_bin.iterdir()):
        executable.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(scripts_dir / "dashboard-dev.sh")],
        cwd=release_root,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "NVM_DIR": str(tmp_path / "nvm"),
            "LOOPX_NPM_LOG": str(npm_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Using compatible Node.js from" in completed.stdout
    assert npm_log.read_text(encoding="utf-8").splitlines() == [
        "ci",
        "run dev:web",
    ]


def test_dashboard_launcher_discovers_agent_bins_outside_restricted_path(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    dashboard_dir = release_root / "apps" / "presentation" / "dashboard"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    npm_global = home / ".npm-global" / "bin"
    nvm_bin = home / ".nvm" / "versions" / "node" / "v22.22.2" / "bin"
    scripts_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    fake_bin.mkdir()
    npm_global.mkdir(parents=True)
    nvm_bin.mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "scripts" / "dashboard-dev.sh",
        scripts_dir / "dashboard-dev.sh",
    )
    (dashboard_dir / "node_modules" / ".bin").mkdir(parents=True)
    (dashboard_dir / "node_modules" / ".bin" / "vite").touch()

    command_log = tmp_path / "commands.log"
    (fake_bin / "python3.13").write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$LOOPX_COMMAND_LOG"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "node").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (fake_bin / "npm").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (npm_global / "codex").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (nvm_bin / "claude").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for executable in (
        fake_bin / "python3.13",
        fake_bin / "node",
        fake_bin / "npm",
        npm_global / "codex",
        nvm_bin / "claude",
    ):
        executable.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(scripts_dir / "dashboard-dev.sh")],
        cwd=release_root,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "NVM_DIR": str(home / ".nvm"),
            "LOOPX_COMMAND_LOG": str(command_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert f"Codex={npm_global / 'codex'}" in completed.stdout
    assert f"Claude Code={nvm_bin / 'claude'}" in completed.stdout
    commands = command_log.read_text(encoding="utf-8")
    assert f"--codex-bin {npm_global / 'codex'}" in commands
    assert f"--claude-bin {nvm_bin / 'claude'}" in commands

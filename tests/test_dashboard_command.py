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


def test_chat_command_accepts_explicit_lark_cli_binary() -> None:
    args = build_parser().parse_args(["chat", "--lark-cli-bin", "custom-lark-cli"])

    assert args.lark_cli_bin == "custom-lark-cli"


def test_chat_command_passes_explicit_lark_cli_binary_to_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(support_control, "serve_chat", lambda **kwargs: calls.append(kwargs))

    assert main(["chat", "--lark-cli-bin", "custom-lark-cli", "--no-open"]) == 0
    assert calls[0]["lark_cli_bin"] == "custom-lark-cli"


def test_macos_launchagent_passes_discovered_lark_cli_without_login_shell() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "macos-dashboard-launchagent.sh"
    ).read_text(encoding="utf-8")

    assert "--lark-cli-bin" in script
    assert "resolve_lark_cli_command" in script
    assert "<string>-lc</string>" not in script
    assert script.count("<string>-c</string>") == 3


def test_dashboard_command_runs_the_dashboard_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_launch_dashboard(**kwargs: object) -> int:
        calls.append(kwargs)
        return 23

    monkeypatch.setattr(
        support_control,
        "launch_dashboard",
        fake_launch_dashboard,
        raising=False,
    )

    assert main(["dashboard"]) == 23
    assert len(calls) == 1


def test_launch_dashboard_in_installed_mode_serves_packaged_chat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from loopx.dashboard_launcher import launch_dashboard

    # Point release root to an empty directory without scripts/dashboard-dev.sh (simulating installed wheel site-packages)
    monkeypatch.setenv("LOOPX_RELEASE_ROOT", str(tmp_path))

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "loopx.chat_server.serve_chat",
        lambda **kwargs: calls.append(kwargs),
    )

    # Launch dashboard should invoke serve_chat using packaged web bundle
    result = launch_dashboard(open_browser=False)
    assert result == 0
    assert len(calls) == 1
    assert calls[0]["open_browser"] is False
    assert (Path(str(calls[0]["assets_dir"])) / "index.html").is_file()


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
    (nvm_bin / "lark-cli").write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--version" ]]; then printf "%s\\n" "lark-cli 1.2.3"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    for executable in (
        fake_bin / "python3.13",
        fake_bin / "node",
        fake_bin / "npm",
        npm_global / "codex",
        nvm_bin / "claude",
        nvm_bin / "lark-cli",
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
            "NVM_BIN": str(nvm_bin),
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
    assert f"--lark-cli-bin {nvm_bin / 'lark-cli'}" in commands


def test_dashboard_launcher_selects_highest_semantic_nvm_lark_cli(
    tmp_path: Path,
) -> None:
    release_root = tmp_path / "release"
    scripts_dir = release_root / "scripts"
    dashboard_dir = release_root / "apps" / "presentation" / "dashboard"
    fake_bin = tmp_path / "bin"
    home = tmp_path / "home"
    low_bin = home / ".nvm" / "versions" / "node" / "v22.9.99" / "bin"
    high_bin = home / ".nvm" / "versions" / "node" / "v22.12.10" / "bin"
    scripts_dir.mkdir(parents=True)
    dashboard_dir.mkdir(parents=True)
    fake_bin.mkdir()
    low_bin.mkdir(parents=True)
    high_bin.mkdir(parents=True)
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
    for lark_cli in (low_bin / "lark-cli", high_bin / "lark-cli"):
        lark_cli.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    for executable in (
        fake_bin / "python3.13",
        fake_bin / "node",
        fake_bin / "npm",
        low_bin / "lark-cli",
        high_bin / "lark-cli",
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
            "NVM_BIN": "",
            "LOOPX_COMMAND_LOG": str(command_log),
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert f"--lark-cli-bin {high_bin / 'lark-cli'}" in commands
    assert f"--lark-cli-bin {low_bin / 'lark-cli'}" not in commands


def test_dashboard_command_in_installed_mode_resolves_packaged_web_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOOPX_RELEASE_ROOT", str(tmp_path))
    served: list[dict[str, object]] = []

    monkeypatch.setattr(
        "loopx.chat_server.serve_chat",
        lambda **kwargs: served.append(kwargs),
    )

    exit_code = main(["dashboard", "--host", "127.0.0.1", "--port", "8791", "--no-open"])
    assert exit_code == 0
    assert len(served) == 1
    assert served[0]["host"] == "127.0.0.1"
    assert served[0]["port"] == 8791
    assert served[0]["open_browser"] is False
    assert (Path(str(served[0]["assets_dir"])) / "index.html").is_file()

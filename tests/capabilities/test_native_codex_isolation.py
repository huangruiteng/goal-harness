from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from functools import cache
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit.native_codex_isolation import (
    NativeCodexIsolationError,
    build_native_codex_isolation_envelope,
    rebase_native_codex_loopx_workspace_state,
)


@cache
def _namespace_mounts_supported() -> bool:
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    probe = subprocess.run(
        [
            unshare,
            "--user",
            "--map-root-user",
            "--mount",
            "--pid",
            "--fork",
            "sh",
            "-c",
            "mount --make-rprivate / && mount -t tmpfs tmpfs /tmp && umount /tmp",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def _native_codex_isolation_supported() -> bool:
    return _namespace_mounts_supported() and shutil.which("tini") is not None


def test_native_codex_isolation_rejects_overlapping_authority_roots(
    tmp_path: Path,
) -> None:
    controller_root = tmp_path / "controller"
    private_root = controller_root / "private"
    private_root.mkdir(parents=True)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    profile_root = private_root / "profile"
    profile_root.mkdir()

    with pytest.raises(
        NativeCodexIsolationError,
        match="native_codex_profile_root_overlaps_private_root",
    ):
        build_native_codex_isolation_envelope(
            executable="sh",
            process_args=["-c", "true"],
            work_dir=work_dir,
            private_root=private_root,
            profile_root=profile_root,
        )

    with pytest.raises(
        NativeCodexIsolationError,
        match="native_codex_workspace_source_exposes_private_root",
    ):
        build_native_codex_isolation_envelope(
            executable="sh",
            process_args=["-c", "true"],
            work_dir=work_dir,
            private_root=private_root,
            workspace_source=controller_root,
        )


def test_native_codex_loopx_state_rebase_round_trips_generated_control_state(
    tmp_path: Path,
) -> None:
    visible = tmp_path / "visible"
    alias = tmp_path / "run-work" / "host-visible"
    alias.parent.mkdir(parents=True)
    project_registry = visible / ".loopx/registry.json"
    global_registry = visible / ".loopx/runtime/registry.global.json"
    global_registry.parent.mkdir(parents=True)
    registry_payload = {
        "common_runtime_root": str(visible / ".loopx/runtime"),
        "unrelated": f"prefix-{visible}-must-not-change",
        "goals": [{"id": "goal-1", "repo": str(visible)}],
    }
    for path in (project_registry, global_registry):
        path.write_text(
            json.dumps(registry_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    runs_dir = visible / ".loopx/runtime/goals/goal-1/runs"
    runs_dir.mkdir(parents=True)
    run_json = runs_dir / "run.json"
    run_markdown = runs_dir / "run.md"
    index_path = runs_dir / "index.jsonl"
    run_json.write_text(
        json.dumps(
            {
                "state": {"path": str(visible / ".codex/goals/goal-1/state.md")},
                "unrelated": f"prefix-{visible}-must-not-change",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run_markdown.write_text(
        f"- state_file: `{visible}/.codex/goals/goal-1/state.md`\n"
        f"- unrelated: `prefix-{visible}-must-not-change`\n",
        encoding="utf-8",
    )
    index_path.write_text(
        json.dumps(
            {
                "json_path": str(run_json),
                "markdown_path": str(run_markdown),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    originals = {
        path: path.read_text(encoding="utf-8")
        for path in (
            project_registry,
            global_registry,
            run_json,
            run_markdown,
            index_path,
        )
    }

    rebased = rebase_native_codex_loopx_workspace_state(
        visible,
        source_root=visible,
        target_root=alias,
    )

    assert rebased.control_state_found is True
    assert rebased.replacement_count == 8
    assert set(rebased.rewritten_files) == set(originals)
    assert not alias.exists()
    for path in originals:
        text = path.read_text(encoding="utf-8")
        assert str(alias) in text
    for path in (project_registry, global_registry, run_json, run_markdown):
        assert f"prefix-{visible}-must-not-change" in path.read_text(encoding="utf-8")

    # The isolation envelope materializes the planned alias between the two
    # calls; the pre-launch relocation must not require it prematurely.
    alias.mkdir()
    restored = rebase_native_codex_loopx_workspace_state(
        visible,
        source_root=alias,
        target_root=visible,
    )

    assert restored.control_state_found is True
    assert restored.replacement_count == rebased.replacement_count
    for path, original in originals.items():
        assert path.read_text(encoding="utf-8") == original


def test_native_codex_loopx_state_rebase_validates_all_files_before_writing(
    tmp_path: Path,
) -> None:
    visible = tmp_path / "visible"
    alias = tmp_path / "alias"
    alias.mkdir()
    project_registry = visible / ".loopx/registry.json"
    global_registry = visible / ".loopx/runtime/registry.global.json"
    global_registry.parent.mkdir(parents=True)
    registry_text = (
        json.dumps(
            {"common_runtime_root": str(visible / ".loopx/runtime")},
            indent=2,
        )
        + "\n"
    )
    project_registry.write_text(registry_text, encoding="utf-8")
    global_registry.write_text(registry_text, encoding="utf-8")
    runs_dir = visible / ".loopx/runtime/goals/goal-1/runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "index.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(
        NativeCodexIsolationError,
        match="native_codex_loopx_state_invalid_jsonl",
    ):
        rebase_native_codex_loopx_workspace_state(
            visible,
            source_root=visible,
            target_root=alias,
        )

    assert project_registry.read_text(encoding="utf-8") == registry_text
    assert global_registry.read_text(encoding="utf-8") == registry_text


def test_native_codex_loopx_state_rebase_requires_complete_registry_pair(
    tmp_path: Path,
) -> None:
    visible = tmp_path / "visible"
    alias = tmp_path / "alias"
    alias.mkdir()
    project_registry = visible / ".loopx/registry.json"
    project_registry.parent.mkdir(parents=True)
    project_registry.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        NativeCodexIsolationError,
        match="native_codex_loopx_registry_incomplete",
    ):
        rebase_native_codex_loopx_workspace_state(
            visible,
            source_root=visible,
            target_root=alias,
        )


@pytest.mark.skipif(
    not _native_codex_isolation_supported(),
    reason="native Codex isolation prerequisites are unavailable",
)
def test_native_codex_isolation_exposes_only_workspace_profile_and_work_children(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "controller-private"
    workspace = private_root / "task-workspace"
    workspace.mkdir(parents=True)
    (private_root / "hidden-answer.txt").write_text("denied", encoding="utf-8")
    (workspace / "task-marker.txt").write_text("visible", encoding="utf-8")
    profile_root = tmp_path / "installed-profile"
    profile_root.mkdir()
    (profile_root / "profile-marker.txt").write_text("installed", encoding="utf-8")
    work_dir = tmp_path / "run-work"
    work_dir.mkdir()
    (work_dir / "runner-marker.txt").write_text("runner", encoding="utf-8")
    host_sentinel = tmp_path / "host-only-sentinel.txt"
    host_sentinel.write_text("host", encoding="utf-8")

    probe = textwrap.dedent(
        """
        set -eu
        private_root=$1
        workspace_source=$2
        workspace_alias=$3
        profile_root=$4
        work_dir=$5
        host_sentinel=$6
        test ! -e "$private_root"
        test ! -e "$workspace_source"
        test -f "$workspace_alias/task-marker.txt"
        test -f "$profile_root/profile-marker.txt"
        test -f "$work_dir/runner-marker.txt"
        test ! -e "$host_sentinel"
        test ! -e "/proc/1/root$host_sentinel"
        touch "$workspace_alias/workspace-write"
        touch "$profile_root/profile-write"
        ! touch /usr/native-codex-isolation-must-be-read-only 2>/dev/null
        printf 'isolated\n'
        """
    )
    envelope = build_native_codex_isolation_envelope(
        executable="sh",
        process_args=[
            "-ceu",
            probe,
            "sh",
            str(private_root),
            str(workspace),
            str(work_dir / "host-visible"),
            str(profile_root),
            str(work_dir),
            str(host_sentinel),
        ],
        work_dir=work_dir,
        private_root=private_root,
        workspace_source=workspace,
        profile_root=profile_root,
    )

    completed = subprocess.run(
        envelope.process_command,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "isolated\n"
    assert envelope.workspace_alias == work_dir / "host-visible"
    assert (workspace / "workspace-write").is_file()
    assert (profile_root / "profile-write").is_file()
    assert not Path("/usr/native-codex-isolation-must-be-read-only").exists()


@pytest.mark.skipif(
    not _native_codex_isolation_supported(),
    reason="native Codex isolation prerequisites are unavailable",
)
def test_native_codex_isolation_hides_runner_provider_authority_from_shell_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_root = tmp_path / "controller-private"
    private_root.mkdir()
    private_secret_file = private_root / "provider-secret.txt"
    private_secret_file.write_text("fixture-upstream-secret", encoding="utf-8")
    workspace = tmp_path / "task-workspace"
    workspace.mkdir()
    profile_root = tmp_path / "installed-profile"
    home = profile_root / "home"
    codex_home = profile_root / "codex-home"
    codex_home.mkdir(parents=True)
    home.mkdir()
    (codex_home / "config.toml").write_text(
        'env_key = "LOOPX_MODEL_PROVIDER_SENTINEL"\n',
        encoding="utf-8",
    )
    work_dir = tmp_path / "run-work"
    work_dir.mkdir()
    monkeypatch.setenv("ARK_OPENAI_API_KEY", "fixture-upstream-secret")

    probe = textwrap.dedent(
        """
        set -eu
        private_secret_file=$1
        test -z "${ARK_OPENAI_API_KEY+x}"
        for process_environment in /proc/[0-9]*/environ; do
            [ -r "$process_environment" ] || continue
            ! tr '\\0' '\\n' < "$process_environment" \
                | grep -a -F 'ARK_OPENAI_API_KEY='
        done
        test ! -e "$private_secret_file"
        ! grep -R -a -F 'ARK_OPENAI_API_KEY=' "$HOME" "$CODEX_HOME"
        test "$(cat "$CODEX_HOME/config.toml")" = \
            'env_key = "LOOPX_MODEL_PROVIDER_SENTINEL"'
        printf 'credential-boundary-isolated\n'
        """
    )
    envelope = build_native_codex_isolation_envelope(
        executable="sh",
        process_args=["-ceu", probe, "sh", str(private_secret_file)],
        work_dir=work_dir,
        private_root=private_root,
        workspace_source=workspace,
        profile_root=profile_root,
    )
    isolated_env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(home),
        "CODEX_HOME": str(codex_home),
        "LOOPX_MODEL_PROVIDER_SENTINEL": "runner-owned-gateway-no-upstream-secret",
    }

    completed = subprocess.run(
        envelope.process_command,
        env=isolated_env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "credential-boundary-isolated\n"
    for authority_root in (home, codex_home):
        for path in authority_root.rglob("*"):
            if path.is_file():
                assert b"fixture-upstream-secret" not in path.read_bytes()


@pytest.mark.skipif(
    not _native_codex_isolation_supported(),
    reason="native Codex isolation prerequisites are unavailable",
)
def test_native_codex_isolation_rejects_symlinked_work_children(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "controller-private"
    private_root.mkdir()
    work_dir = tmp_path / "run-work"
    work_dir.mkdir()
    (work_dir / "escape-link").symlink_to(private_root, target_is_directory=True)
    envelope = build_native_codex_isolation_envelope(
        executable="sh",
        process_args=["-c", "exit 99"],
        work_dir=work_dir,
        private_root=private_root,
    )

    completed = subprocess.run(
        envelope.process_command,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 64


@pytest.mark.skipif(
    not _native_codex_isolation_supported(),
    reason="native Codex isolation prerequisites are unavailable",
)
def test_native_codex_isolation_reaps_orphaned_command_processes(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "controller-private"
    private_root.mkdir()
    work_dir = tmp_path / "run-work"
    work_dir.mkdir()
    probe = textwrap.dedent(
        """
        import os
        import time

        child = os.fork()
        if child == 0:
            grandchild = os.fork()
            if grandchild == 0:
                time.sleep(0.05)
                os._exit(0)
            os._exit(0)
        os.waitpid(child, 0)
        time.sleep(0.5)

        zombies = []
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                fields = {}
                with open(f"/proc/{entry}/status", encoding="utf-8") as handle:
                    for line in handle:
                        if ":" in line:
                            key, value = line.split(":", 1)
                            fields[key] = value.strip()
                if (
                    fields.get("PPid") == "1"
                    and fields.get("State", "").startswith("Z")
                ):
                    zombies.append(entry)
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        print(len(zombies))
        """
    )
    envelope = build_native_codex_isolation_envelope(
        executable="python3",
        process_args=["-c", probe],
        work_dir=work_dir,
        private_root=private_root,
    )

    completed = subprocess.run(
        envelope.process_command,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "0\n"

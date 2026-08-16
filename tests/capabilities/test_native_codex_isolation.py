from __future__ import annotations

import shutil
import subprocess
import textwrap
from functools import cache
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit.native_codex_isolation import (
    NativeCodexIsolationError,
    build_native_codex_isolation_envelope,
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


@pytest.mark.skipif(
    not _namespace_mounts_supported(),
    reason="unprivileged user/mount namespaces are unavailable",
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
    not _namespace_mounts_supported(),
    reason="unprivileged user/mount namespaces are unavailable",
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

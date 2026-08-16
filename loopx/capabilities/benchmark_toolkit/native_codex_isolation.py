"""Linux allowlist envelope for host-side native Codex benchmark workers.

The benchmark runner still owns task provisioning, command bridging, network
policy, evaluator ordering, and scoring.  This module only builds the process
boundary that keeps a host-side ``codex app-server`` away from the ambient host
filesystem while re-exposing one task workspace and, optionally, one formally
installed LoopX profile.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class NativeCodexIsolationError(RuntimeError):
    """The requested native Codex process boundary is not safe to build."""


@dataclass(frozen=True)
class NativeCodexIsolationEnvelope:
    """Resolved process command and task-visible paths for one isolated run."""

    process_command: tuple[str, ...]
    work_dir: Path
    workspace_alias: Path | None
    profile_root: Path | None


_ISOLATION_SCRIPT = r"""
private_root=$1
workspace_source=$2
work_dir=$3
profile_root=$4
executable=$5
setpriv_bin=$6
shift 6

mount --make-rprivate /
sandbox_root="$work_dir/.sandbox-root"
mkdir -p "$sandbox_root"
mount -t tmpfs -o mode=0755,nodev,nosuid tmpfs "$sandbox_root"

# Keep only the host system runtime required to execute Codex.  Plain bind
# mounts intentionally omit any nested host mounts, and every system directory
# is remounted read-only inside this mount namespace.
for system_dir in usr bin sbin lib lib64; do
    if [ -d "/$system_dir" ]; then
        mkdir -p "$sandbox_root/$system_dir"
        mount --bind "/$system_dir" "$sandbox_root/$system_dir"
        mount -o remount,bind,ro "$sandbox_root/$system_dir"
    fi
done

mkdir -p "$sandbox_root/etc" "$sandbox_root/etc/ssl" "$sandbox_root/dev"
mkdir -p "$sandbox_root/proc" "$sandbox_root/run" "$sandbox_root/tmp"
chmod 1777 "$sandbox_root/tmp"
for etc_file in hosts nsswitch.conf passwd group resolv.conf localtime; do
    if [ -e "/etc/$etc_file" ]; then
        touch "$sandbox_root/etc/$etc_file"
        mount --bind "/etc/$etc_file" "$sandbox_root/etc/$etc_file"
        mount -o remount,bind,ro "$sandbox_root/etc/$etc_file"
    fi
done
if [ -d /etc/ssl ]; then
    mount --bind /etc/ssl "$sandbox_root/etc/ssl"
    mount -o remount,bind,ro "$sandbox_root/etc/ssl"
fi
ln -s /proc/mounts "$sandbox_root/etc/mtab"
for device in null zero full random urandom tty; do
    if [ -e "/dev/$device" ]; then
        touch "$sandbox_root/dev/$device"
        mount --bind "/dev/$device" "$sandbox_root/dev/$device"
    fi
done
ln -s /proc/self/fd "$sandbox_root/dev/fd"
ln -s /proc/self/fd/0 "$sandbox_root/dev/stdin"
ln -s /proc/self/fd/1 "$sandbox_root/dev/stdout"
ln -s /proc/self/fd/2 "$sandbox_root/dev/stderr"
mount -t proc -o nosuid,nodev,noexec proc "$sandbox_root/proc"

# Share only runner-created children of the per-run work directory.  Refuse
# symlinks and special files so a prepared work directory cannot widen the
# allowlist before pivot_root.
mkdir -p "$sandbox_root$work_dir"
for shared_path in "$work_dir"/* "$work_dir"/.[!.]* "$work_dir"/..?*; do
    [ -e "$shared_path" ] || continue
    [ "$shared_path" = "$sandbox_root" ] && continue
    [ ! -L "$shared_path" ] || exit 64
    target="$sandbox_root$shared_path"
    if [ -d "$shared_path" ]; then
        mkdir -p "$target"
    elif [ -f "$shared_path" ]; then
        mkdir -p "$(dirname "$target")"
        touch "$target"
    else
        exit 64
    fi
    mount --bind "$shared_path" "$target"
done

if [ -n "$workspace_source" ]; then
    workspace_alias="$sandbox_root$work_dir/host-visible"
    mkdir -p "$workspace_alias"
    mount --bind "$workspace_source" "$workspace_alias"
fi
if [ -n "$profile_root" ]; then
    mkdir -p "$sandbox_root$profile_root"
    mount --bind "$profile_root" "$sandbox_root$profile_root"
fi

# A test launcher or alternate Codex binary may live outside the shared system
# runtime, work directory, or formal profile.  Re-expose only the resolved file.
bind_executable=1
case "$executable" in
    /usr/*|/bin/*|/sbin/*|/lib/*|/lib64/*|"$work_dir"/*) bind_executable=0 ;;
esac
if [ -n "$profile_root" ]; then
    case "$executable" in
        "$profile_root"/*) bind_executable=0 ;;
    esac
fi
if [ "$bind_executable" = 1 ]; then
    mkdir -p "$sandbox_root$(dirname "$executable")"
    touch "$sandbox_root$executable"
    mount --bind "$executable" "$sandbox_root$executable"
    mount -o remount,bind,ro "$sandbox_root$executable"
fi

mkdir -p "$sandbox_root/.old-root"
cd "$sandbox_root"
pivot_root . .old-root
umount -l /.old-root
rmdir /.old-root
cd "$work_dir"

# The denied root and source spelling stay absent.  The caller uses only the
# case-local alias returned by NativeCodexIsolationEnvelope.
[ ! -e "$private_root" ]
[ -z "$workspace_source" ] || [ ! -e "$workspace_source" ]

# Capabilities exist only inside the fresh user namespace so Codex can install
# its nested workspace/network sandbox.  They cannot reach the host namespace.
exec "$setpriv_bin" --no-new-privs "$executable" "$@"
"""


def _resolve_executable(value: str, *, error: str) -> Path:
    resolved = shutil.which(value) if not os.path.isabs(value) else value
    if not resolved:
        raise NativeCodexIsolationError(error)
    try:
        path = Path(resolved).resolve(strict=True)
    except OSError as exc:
        raise NativeCodexIsolationError(error) from exc
    if not path.is_file() or not os.access(path, os.X_OK):
        raise NativeCodexIsolationError(error)
    return path


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def build_native_codex_isolation_envelope(
    *,
    executable: str,
    process_args: Sequence[str],
    work_dir: Path,
    private_root: Path,
    workspace_source: Path | None = None,
    profile_root: Path | None = None,
) -> NativeCodexIsolationEnvelope:
    """Build a fail-closed Linux namespace command for native Codex.

    ``private_root`` is absent after ``pivot_root``.  ``workspace_source`` is
    available only as ``work_dir / "host-visible"``.  ``profile_root`` retains
    its absolute spelling so a formally installed CLI, Codex home, and skill
    tree can use their verified paths without exposing the surrounding host.
    """

    unshare = _resolve_executable("unshare", error="native_codex_unshare_missing")
    setpriv = _resolve_executable("setpriv", error="native_codex_setpriv_missing")
    shell = _resolve_executable("sh", error="native_codex_shell_missing")
    resolved_executable = _resolve_executable(
        executable, error="native_codex_executable_missing"
    )
    if isinstance(process_args, (str, bytes)):
        raise TypeError("process_args must be a sequence of arguments")
    try:
        resolved_work_dir = work_dir.resolve(strict=True)
        resolved_private_root = private_root.resolve(strict=True)
    except OSError as exc:
        raise NativeCodexIsolationError("native_codex_isolation_root_missing") from exc
    if not resolved_work_dir.is_dir() or not resolved_private_root.is_dir():
        raise NativeCodexIsolationError("native_codex_isolation_root_not_directory")
    if _paths_overlap(resolved_work_dir, resolved_private_root):
        raise NativeCodexIsolationError("native_codex_work_dir_overlaps_private_root")
    if resolved_executable == resolved_private_root or (
        resolved_private_root in resolved_executable.parents
    ):
        raise NativeCodexIsolationError("native_codex_executable_inside_private_root")

    workspace_alias: Path | None = None
    workspace_raw = ""
    if workspace_source is not None:
        try:
            resolved_workspace = workspace_source.resolve(strict=True)
        except OSError as exc:
            raise NativeCodexIsolationError(
                "native_codex_workspace_source_missing"
            ) from exc
        if not resolved_workspace.is_dir():
            raise NativeCodexIsolationError(
                "native_codex_workspace_source_not_directory"
            )
        if _paths_overlap(resolved_workspace, resolved_work_dir):
            raise NativeCodexIsolationError(
                "native_codex_workspace_source_overlaps_work_dir"
            )
        if resolved_workspace == resolved_private_root or (
            resolved_workspace in resolved_private_root.parents
        ):
            raise NativeCodexIsolationError(
                "native_codex_workspace_source_exposes_private_root"
            )
        if resolved_executable == resolved_workspace or (
            resolved_workspace in resolved_executable.parents
        ):
            raise NativeCodexIsolationError(
                "native_codex_executable_inside_workspace_source"
            )
        workspace_raw = str(resolved_workspace)
        workspace_alias = resolved_work_dir / "host-visible"
        workspace_alias.mkdir(parents=True, exist_ok=True)

    resolved_profile: Path | None = None
    profile_raw = ""
    if profile_root is not None:
        try:
            resolved_profile = profile_root.resolve(strict=True)
        except OSError as exc:
            raise NativeCodexIsolationError(
                "native_codex_profile_root_missing"
            ) from exc
        if not resolved_profile.is_dir():
            raise NativeCodexIsolationError("native_codex_profile_root_not_directory")
        if _paths_overlap(resolved_profile, resolved_private_root):
            raise NativeCodexIsolationError(
                "native_codex_profile_root_overlaps_private_root"
            )
        if _paths_overlap(resolved_profile, resolved_work_dir):
            raise NativeCodexIsolationError(
                "native_codex_profile_root_overlaps_work_dir"
            )
        if workspace_source is not None and _paths_overlap(
            resolved_profile, Path(workspace_raw)
        ):
            raise NativeCodexIsolationError(
                "native_codex_profile_root_overlaps_workspace_source"
            )
        profile_raw = str(resolved_profile)

    command = (
        str(unshare),
        "--user",
        "--map-root-user",
        "--mount",
        "--pid",
        "--fork",
        "--mount-proc",
        str(shell),
        "-ceu",
        _ISOLATION_SCRIPT,
        "sh",
        str(resolved_private_root),
        workspace_raw,
        str(resolved_work_dir),
        profile_raw,
        str(resolved_executable),
        str(setpriv),
        *(str(value) for value in process_args),
    )
    return NativeCodexIsolationEnvelope(
        process_command=command,
        work_dir=resolved_work_dir,
        workspace_alias=workspace_alias,
        profile_root=resolved_profile,
    )


__all__ = [
    "NativeCodexIsolationEnvelope",
    "NativeCodexIsolationError",
    "build_native_codex_isolation_envelope",
]

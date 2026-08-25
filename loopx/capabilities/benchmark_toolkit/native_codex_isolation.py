"""Linux allowlist envelope for host-side native Codex benchmark workers.

The benchmark runner still owns task provisioning, command bridging, network
policy, evaluator ordering, and scoring.  This module only builds the process
boundary that keeps a host-side ``codex app-server`` away from the ambient host
filesystem while re-exposing one task workspace and, optionally, one formally
installed LoopX profile.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class NativeCodexIsolationError(RuntimeError):
    """The requested native Codex process boundary is not safe to build."""


@dataclass(frozen=True)
class NativeCodexIsolationEnvelope:
    """Resolved process command and task-visible paths for one isolated run."""

    process_command: tuple[str, ...]
    work_dir: Path
    workspace_alias: Path | None
    profile_root: Path | None


@dataclass(frozen=True)
class NativeCodexLoopXStateRebase:
    """Result of relocating LoopX-owned paths across a workspace alias."""

    control_state_found: bool
    rewritten_files: tuple[Path, ...]
    replacement_count: int


_ISOLATION_SCRIPT = r"""
private_root=$1
workspace_source=$2
work_dir=$3
profile_root=$4
executable=$5
setpriv_bin=$6
init_bin=$7
shift 7

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

# A test launcher, alternate Codex binary, or init may live outside the shared
# system runtime, work directory, or formal profile.  Re-expose only each
# resolved file.
bind_runtime_file() {
    runtime_file=$1
    bind_file=1
    case "$runtime_file" in
        /usr/*|/bin/*|/sbin/*|/lib/*|/lib64/*|"$work_dir"/*) bind_file=0 ;;
    esac
    if [ -n "$profile_root" ]; then
        case "$runtime_file" in
            "$profile_root"/*) bind_file=0 ;;
        esac
    fi
    if [ "$bind_file" = 1 ]; then
        mkdir -p "$sandbox_root$(dirname "$runtime_file")"
        touch "$sandbox_root$runtime_file"
        mount --bind "$runtime_file" "$sandbox_root$runtime_file"
        mount -o remount,bind,ro "$sandbox_root$runtime_file"
    fi
}
bind_runtime_file "$executable"
bind_runtime_file "$init_bin"

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
# Keep a real init as PID 1 so orphaned command subprocesses are reaped during
# long-running Goal workers instead of accumulating as defunct processes.
exec "$init_bin" -s -- "$setpriv_bin" --no-new-privs "$executable" "$@"
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


def _replace_path_prefix(value: Any, source: str, target: str) -> tuple[Any, int]:
    if isinstance(value, str):
        if value == source:
            return target, 1
        prefix = f"{source}{os.sep}"
        if value.startswith(prefix):
            return f"{target}{value[len(source) :]}", 1
        return value, 0
    if isinstance(value, list):
        replaced: list[Any] = []
        count = 0
        for item in value:
            next_item, item_count = _replace_path_prefix(item, source, target)
            replaced.append(next_item)
            count += item_count
        return replaced, count
    if isinstance(value, dict):
        replaced_dict: dict[Any, Any] = {}
        count = 0
        for key, item in value.items():
            next_item, item_count = _replace_path_prefix(item, source, target)
            replaced_dict[key] = next_item
            count += item_count
        return replaced_dict, count
    return value, 0


def _generated_runtime_files(storage_root: Path) -> tuple[Path, ...]:
    goals_root = storage_root / ".loopx/runtime/goals"
    if not goals_root.exists():
        return ()
    if goals_root.is_symlink() or not goals_root.is_dir():
        raise NativeCodexIsolationError("native_codex_loopx_goals_root_not_directory")

    files: list[Path] = []
    for goal_dir in sorted(goals_root.iterdir()):
        if goal_dir.is_symlink():
            raise NativeCodexIsolationError("native_codex_loopx_goal_dir_symlinked")
        if not goal_dir.is_dir():
            continue
        runs_dir = goal_dir / "runs"
        if not runs_dir.exists():
            continue
        if runs_dir.is_symlink() or not runs_dir.is_dir():
            raise NativeCodexIsolationError("native_codex_loopx_runs_dir_not_directory")
        for path in sorted(runs_dir.iterdir()):
            if path.is_symlink():
                raise NativeCodexIsolationError(
                    "native_codex_loopx_run_artifact_symlinked"
                )
            if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
                files.append(path)
    return tuple(files)


def _rewrite_json_text(text: str, source: str, target: str) -> tuple[str, int]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NativeCodexIsolationError(
            "native_codex_loopx_state_invalid_json"
        ) from exc
    rewritten, count = _replace_path_prefix(payload, source, target)
    return json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n", count


def _rewrite_jsonl_text(text: str, source: str, target: str) -> tuple[str, int]:
    rewritten_lines: list[str] = []
    count = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise NativeCodexIsolationError(
                "native_codex_loopx_state_invalid_jsonl"
            ) from exc
        rewritten, line_count = _replace_path_prefix(payload, source, target)
        rewritten_lines.append(json.dumps(rewritten, ensure_ascii=False))
        count += line_count
    suffix = "\n" if rewritten_lines else ""
    return "\n".join(rewritten_lines) + suffix, count


def _rewrite_markdown_text(text: str, source: str, target: str) -> tuple[str, int]:
    # Generated Markdown embeds paths inside backticks or after punctuation.
    # Refuse identifier-adjacent matches so prose such as ``prefix-/path`` is
    # not silently rewritten.
    pattern = re.compile(
        rf"(?<![0-9A-Za-z_.-]){re.escape(source)}(?=$|[/\s`'\"\[\](){{}}:,])"
    )
    return pattern.subn(lambda _: target, text)


def _atomic_write_text(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, path.stat().st_mode & 0o777)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def rebase_native_codex_loopx_workspace_state(
    storage_root: Path,
    *,
    source_root: Path,
    target_root: Path,
) -> NativeCodexLoopXStateRebase:
    """Relocate LoopX-owned state across an isolated workspace alias.

    Native Codex sees ``workspace_source`` through a temporary path.  LoopX
    registries and generated run-history artifacts may persist that path while
    the process is alive.  This bounded rewrite keeps those artifacts readable
    after the alias disappears without touching task files, model output, raw
    trajectories, verifier evidence, or arbitrary workspace prose.

    Call once before launch from the host path to the alias, then once after
    process termination from the alias back to the host path.  All candidate
    files are parsed before any replacement is committed.  The source must
    exist; the pre-launch target may be a planned alias that the envelope will
    materialize immediately afterwards.
    """

    try:
        resolved_storage = storage_root.resolve(strict=True)
        resolved_source = source_root.resolve(strict=True)
    except OSError as exc:
        raise NativeCodexIsolationError(
            "native_codex_loopx_state_rebase_root_missing"
        ) from exc
    resolved_target = target_root.expanduser().resolve(strict=False)
    if not resolved_storage.is_dir():
        raise NativeCodexIsolationError(
            "native_codex_loopx_state_rebase_storage_not_directory"
        )
    if resolved_source == resolved_target:
        raise NativeCodexIsolationError(
            "native_codex_loopx_state_rebase_roots_identical"
        )

    registry_paths = (
        resolved_storage / ".loopx/registry.json",
        resolved_storage / ".loopx/runtime/registry.global.json",
    )
    existing_registries = tuple(path for path in registry_paths if path.is_file())
    if not existing_registries:
        return NativeCodexLoopXStateRebase(False, (), 0)
    if len(existing_registries) != len(registry_paths):
        raise NativeCodexIsolationError("native_codex_loopx_registry_incomplete")
    if any(path.is_symlink() for path in registry_paths):
        raise NativeCodexIsolationError("native_codex_loopx_registry_symlinked")

    source = str(resolved_source)
    target = str(resolved_target)
    candidates = (*registry_paths, *_generated_runtime_files(resolved_storage))
    pending: list[tuple[Path, str, int]] = []
    replacement_count = 0
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            rewritten, count = _rewrite_json_text(text, source, target)
        elif path.suffix == ".jsonl":
            rewritten, count = _rewrite_jsonl_text(text, source, target)
        else:
            rewritten, count = _rewrite_markdown_text(text, source, target)
        if count:
            pending.append((path, rewritten, count))
            replacement_count += count

    for path, rewritten, _ in pending:
        _atomic_write_text(path, rewritten)

    return NativeCodexLoopXStateRebase(
        control_state_found=True,
        rewritten_files=tuple(path for path, _, _ in pending),
        replacement_count=replacement_count,
    )


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
    workspace_alias: Path | None = None
    workspace_raw = ""
    resolved_workspace: Path | None = None
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
            # A selected workspace may intentionally be a narrow child of the
            # denied private root.  The reverse direction is unsafe because it
            # would re-expose the private root through an ancestor bind.
            raise NativeCodexIsolationError(
                "native_codex_workspace_source_exposes_private_root"
            )
        workspace_raw = str(resolved_workspace)
        workspace_alias = resolved_work_dir / "host-visible"

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

    # Root policy is pure input validation and must fail deterministically even
    # on hosts that do not provide the Linux namespace tools used at launch.
    unshare = _resolve_executable("unshare", error="native_codex_unshare_missing")
    setpriv = _resolve_executable("setpriv", error="native_codex_setpriv_missing")
    shell = _resolve_executable("sh", error="native_codex_shell_missing")
    init = _resolve_executable("tini", error="native_codex_init_missing")
    resolved_executable = _resolve_executable(
        executable, error="native_codex_executable_missing"
    )
    if resolved_executable == resolved_private_root or (
        resolved_private_root in resolved_executable.parents
    ):
        raise NativeCodexIsolationError("native_codex_executable_inside_private_root")
    if resolved_workspace is not None and (
        resolved_executable == resolved_workspace
        or resolved_workspace in resolved_executable.parents
    ):
        raise NativeCodexIsolationError(
            "native_codex_executable_inside_workspace_source"
        )
    if init == resolved_private_root or resolved_private_root in init.parents:
        raise NativeCodexIsolationError("native_codex_init_inside_private_root")
    mutable_roots = [resolved_work_dir]
    if resolved_workspace is not None:
        mutable_roots.append(resolved_workspace)
    if resolved_profile is not None:
        mutable_roots.append(resolved_profile)
    if any(init == root or root in init.parents for root in mutable_roots):
        raise NativeCodexIsolationError("native_codex_init_inside_mutable_root")
    if workspace_alias is not None:
        workspace_alias.mkdir(parents=True, exist_ok=True)

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
        str(init),
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
    "NativeCodexLoopXStateRebase",
    "build_native_codex_isolation_envelope",
    "rebase_native_codex_loopx_workspace_state",
]

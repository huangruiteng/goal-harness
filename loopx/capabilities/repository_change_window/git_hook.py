from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ...registry import atomic_write_json
from .ledger import record_pending_change
from .policy import ChangeWindowPolicy, evaluate_policy
from .repository import (
    RepositoryChangeWindowError,
    git,
    git_text,
    resolve_repository_context,
)


PROVIDER_STATE_SCHEMA_VERSION = "repository_change_window_git_hook_state_v0"
PROVIDER_STATUS_SCHEMA_VERSION = "repository_change_window_git_hook_status_v0"
PROVIDER_RELATIVE_DIR = Path("loopx") / "repository-change-window"
HOOK_NAMES = ("pre-commit", "pre-push")


def _provider_dir(common_dir: Path) -> Path:
    return common_dir / PROVIDER_RELATIVE_DIR


def _state_path(common_dir: Path) -> Path:
    return _provider_dir(common_dir) / "provider.json"


def _hooks_dir(common_dir: Path) -> Path:
    return _provider_dir(common_dir) / "hooks"


def _hook_script(event: str) -> str:
    return "\n".join(
        (
            "#!/bin/sh",
            "set -u",
            (
                "exec loopx --format json change-window hook "
                f'--repo-path . --event {event} -- "$@"'
            ),
            "",
        )
    )


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_state(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RepositoryChangeWindowError(
            "repository change-window provider state must not be a symlink"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepositoryChangeWindowError(
            "repository change-window provider is not installed"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RepositoryChangeWindowError(
            "repository change-window provider state is invalid JSON"
        ) from exc
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != PROVIDER_STATE_SCHEMA_VERSION
    ):
        raise RepositoryChangeWindowError(
            "repository change-window provider state has an unsupported schema"
        )
    policy_raw = raw.get("policy")
    ChangeWindowPolicy.from_dict(policy_raw if isinstance(policy_raw, Mapping) else {})
    return raw


def _effective_hooks_path(repo: Path) -> Path:
    raw = Path(git_text(repo, "rev-parse", "--git-path", "hooks"))
    return (raw if raw.is_absolute() else repo / raw).resolve()


def _local_hooks_override(repo: Path) -> tuple[bool, str | None]:
    value = git_text(repo, "config", "--local", "--get", "core.hooksPath", check=False)
    return bool(value), value or None


def _write_provider_files(
    *,
    state_path: Path,
    hooks_dir: Path,
    state: Mapping[str, Any],
) -> None:
    if state_path.is_symlink() or hooks_dir.is_symlink():
        raise RepositoryChangeWindowError("managed provider paths must not be symlinks")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hooks_dir.parent.chmod(0o700)
    hooks_dir.chmod(0o700)
    for event in HOOK_NAMES:
        path = hooks_dir / event
        if path.is_symlink():
            raise RepositoryChangeWindowError(
                f"managed hook `{event}` must not be a symlink"
            )
        path.write_text(_hook_script(event), encoding="utf-8")
        path.chmod(0o755)
    atomic_write_json(state_path, dict(state))
    state_path.chmod(0o600)


def _provider_checks(
    *,
    repo: Path,
    common_dir: Path,
    state: Mapping[str, Any],
) -> list[dict[str, object]]:
    hooks_dir = _hooks_dir(common_dir)
    repository_matches = (
        state.get("repository_id") == resolve_repository_context(repo).repository_id
    )
    configured = git_text(
        repo, "config", "--local", "--get", "core.hooksPath", check=False
    )
    expected_config = str(hooks_dir)
    checks: list[dict[str, object]] = [
        {
            "check": "repository_identity",
            "ok": repository_matches,
            "status": "match" if repository_matches else "mismatch",
        },
        {
            "check": "local_core_hooks_path",
            "ok": configured == expected_config,
            "status": "match" if configured == expected_config else "drifted",
        },
    ]
    expected_digests = state.get("hook_digests")
    for event in HOOK_NAMES:
        path = hooks_dir / event
        expected = (
            expected_digests.get(event)
            if isinstance(expected_digests, Mapping)
            else None
        )
        actual = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        executable = path.is_file() and os.access(path, os.X_OK)
        ok = bool(actual == expected and executable)
        checks.append(
            {
                "check": f"hook:{event}",
                "ok": ok,
                "status": "current" if ok else "missing_or_modified",
            }
        )
    return checks


def install_git_hook_provider(
    *,
    repo_path: str | Path,
    policy: ChangeWindowPolicy,
    execute: bool = False,
    replace: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    context = resolve_repository_context(repo_path)
    provider_dir = _provider_dir(context.common_dir)
    if provider_dir.is_symlink():
        raise RepositoryChangeWindowError(
            "managed provider directory must not be a symlink"
        )
    state_path = _state_path(context.common_dir)
    hooks_dir = _hooks_dir(context.common_dir)
    existing: dict[str, Any] | None = None
    if state_path.exists():
        existing = _read_state(state_path)
        checks = _provider_checks(
            repo=context.root,
            common_dir=context.common_dir,
            state=existing,
        )
        existing_policy = ChangeWindowPolicy.from_dict(existing["policy"])
        if existing_policy == policy and all(bool(item["ok"]) for item in checks):
            return {
                "ok": True,
                "schema_version": "repository_change_window_install_v0",
                "dry_run": not execute,
                "changed": False,
                "status": "already_installed",
                "repository_id": context.repository_id,
                "provider_id": "git-hook",
                "policy": policy.to_dict(),
            }
        if not replace:
            raise RepositoryChangeWindowError(
                "provider already exists with different policy or local drift; rerun install with --replace only after review"
            )

    if existing is None:
        previous_hook_root = _effective_hooks_path(context.root)
        previous_local_override, previous_local_value = _local_hooks_override(
            context.root
        )
        if previous_hook_root == hooks_dir:
            raise RepositoryChangeWindowError(
                "effective hook root already points at the managed provider without valid state"
            )
    else:
        previous_hook_root = Path(str(existing.get("previous_hook_root") or ""))
        previous_local_override = bool(existing.get("previous_local_override"))
        previous_local_value = (
            str(existing.get("previous_local_value"))
            if existing.get("previous_local_value") is not None
            else None
        )
    installed_at = (
        (now or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    state = {
        "schema_version": PROVIDER_STATE_SCHEMA_VERSION,
        "provider_id": "git-hook",
        "repository_id": context.repository_id,
        "policy": policy.to_dict(),
        "previous_hook_root": str(previous_hook_root),
        "previous_local_override": previous_local_override,
        "previous_local_value": previous_local_value,
        "managed_hooks_path": str(hooks_dir),
        "hook_digests": {
            event: _digest_text(_hook_script(event)) for event in HOOK_NAMES
        },
        "installed_at": installed_at,
    }
    if execute:
        _write_provider_files(state_path=state_path, hooks_dir=hooks_dir, state=state)
        try:
            git(context.root, "config", "--local", "core.hooksPath", str(hooks_dir))
        except BaseException:
            if existing is None:
                shutil.rmtree(_provider_dir(context.common_dir), ignore_errors=True)
            raise
    return {
        "ok": True,
        "schema_version": "repository_change_window_install_v0",
        "dry_run": not execute,
        "changed": execute,
        "status": "installed" if execute else "preview",
        "repository_id": context.repository_id,
        "provider_id": "git-hook",
        "default_enabled": False,
        "enabled": execute,
        "preserves_previous_hooks": True,
        "policy": policy.to_dict(),
        "managed_hook_names": list(HOOK_NAMES),
        "contains_personal_path": False,
    }


def git_hook_provider_status(
    *,
    repo_path: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    context = resolve_repository_context(repo_path)
    state_path = _state_path(context.common_dir)
    if not state_path.exists():
        return {
            "ok": True,
            "schema_version": PROVIDER_STATUS_SCHEMA_VERSION,
            "status": "not_installed",
            "installed": False,
            "enabled": False,
            "repository_id": context.repository_id,
            "provider_id": "git-hook",
            "default_enabled": False,
        }
    state = _read_state(state_path)
    checks = _provider_checks(
        repo=context.root,
        common_dir=context.common_dir,
        state=state,
    )
    policy = ChangeWindowPolicy.from_dict(state["policy"])
    decision = evaluate_policy(policy, now=now)
    healthy = all(bool(item["ok"]) for item in checks)
    return {
        "ok": healthy,
        "schema_version": PROVIDER_STATUS_SCHEMA_VERSION,
        "status": "ready" if healthy else "drifted",
        "installed": True,
        "enabled": healthy,
        "repository_id": context.repository_id,
        "provider_id": "git-hook",
        "policy": policy.to_dict(),
        "decision": decision,
        "checks": checks,
        "preserves_previous_hooks": True,
        "contains_personal_path": False,
    }


def verify_git_hook_provider(
    *,
    repo_path: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = git_hook_provider_status(repo_path=repo_path, now=now)
    verified = payload.get("ok") is True and payload.get("installed") is True
    return {
        **payload,
        "ok": verified,
        "schema_version": "repository_change_window_provider_verify_v0",
        "verified": verified,
    }


def uninstall_git_hook_provider(
    *,
    repo_path: str | Path,
    execute: bool = False,
) -> dict[str, Any]:
    context = resolve_repository_context(repo_path)
    if _provider_dir(context.common_dir).is_symlink():
        raise RepositoryChangeWindowError(
            "managed provider directory must not be a symlink"
        )
    state = _read_state(_state_path(context.common_dir))
    checks = _provider_checks(
        repo=context.root,
        common_dir=context.common_dir,
        state=state,
    )
    if not all(bool(item["ok"]) for item in checks):
        raise RepositoryChangeWindowError(
            "provider drift detected; uninstall will not overwrite modified hook state"
        )
    if execute:
        if state.get("previous_local_override"):
            previous = str(state.get("previous_local_value") or "")
            if not previous:
                raise RepositoryChangeWindowError(
                    "provider state lost the previous local core.hooksPath value"
                )
            git(context.root, "config", "--local", "core.hooksPath", previous)
        else:
            result = git(
                context.root,
                "config",
                "--local",
                "--unset-all",
                "core.hooksPath",
                check=False,
            )
            if result.returncode not in {0, 5}:
                raise RepositoryChangeWindowError(
                    "failed to remove the managed local core.hooksPath override"
                )
        shutil.rmtree(_provider_dir(context.common_dir))
    return {
        "ok": True,
        "schema_version": "repository_change_window_uninstall_v0",
        "dry_run": not execute,
        "changed": execute,
        "status": "uninstalled" if execute else "preview",
        "repository_id": context.repository_id,
        "provider_id": "git-hook",
        "restores_previous_hook_route": True,
        "contains_personal_path": False,
    }


def run_git_hook_provider(
    *,
    repo_path: str | Path,
    runtime_root: Path,
    event: str,
    hook_args: Sequence[str] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    if event not in HOOK_NAMES:
        raise RepositoryChangeWindowError(f"unsupported Git hook event `{event}`")
    context = resolve_repository_context(repo_path)
    state = _read_state(_state_path(context.common_dir))
    checks = _provider_checks(
        repo=context.root,
        common_dir=context.common_dir,
        state=state,
    )
    if not all(bool(item["ok"]) for item in checks):
        return {
            "ok": False,
            "schema_version": "repository_change_window_hook_result_v0",
            "status": "provider_drift",
            "event": event,
            "exit_code": 1,
            "checks": checks,
        }
    policy = ChangeWindowPolicy.from_dict(state["policy"])
    decision = evaluate_policy(policy, now=now)
    if not decision["allowed"]:
        try:
            ledger_record: dict[str, Any] = record_pending_change(
                runtime_root=runtime_root,
                repo_path=context.root,
                decision=decision,
                source=f"git_hook:{event}",
                execute=True,
                now=now,
            )
        except (OSError, ValueError) as exc:
            ledger_record = {
                "ok": False,
                "status": "record_failed",
                "error": str(exc),
            }
        return {
            "ok": False,
            "schema_version": "repository_change_window_hook_result_v0",
            "status": "blocked_by_policy",
            "event": event,
            "exit_code": 1,
            "decision": decision,
            "pending_change": ledger_record,
        }

    previous_root = Path(str(state.get("previous_hook_root") or ""))
    previous_hook = previous_root / event
    previous_exit_code = 0
    if previous_hook.is_file() and os.access(previous_hook, os.X_OK):
        result = subprocess.run(
            [str(previous_hook), *hook_args],
            cwd=context.root,
            check=False,
        )
        previous_exit_code = result.returncode
    return {
        "ok": previous_exit_code == 0,
        "schema_version": "repository_change_window_hook_result_v0",
        "status": "allowed" if previous_exit_code == 0 else "previous_hook_failed",
        "event": event,
        "exit_code": previous_exit_code,
        "decision": decision,
        "previous_hook_invoked": previous_hook.is_file()
        and os.access(previous_hook, os.X_OK),
    }

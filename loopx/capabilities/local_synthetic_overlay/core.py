from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...control_plane.runtime.time import parse_timestamp, utc_isoformat
from ...control_plane.todos.active_state_editing import find_todo_block
from ...history import load_registry
from ...paths import resolve_runtime_root
from ...registry import atomic_write_json, find_registry_goal
from ...state_refresh import resolve_goal_state


LOCAL_SYNTHETIC_SCOPE = "local_synthetic_validation_only"
PRODUCT_WRITE_SCOPE_ZERO = "ZERO"
ALLOWED_CAPABILITIES = ("local_container", "synthetic_database")
RECEIPT_SCHEMA_VERSION = "loopx_local_synthetic_overlay_receipt_v1"
STORE_SCHEMA_VERSION = "loopx_local_synthetic_overlay_store_record_v0"
DOCTOR_SCHEMA_VERSION = "loopx_local_synthetic_overlay_provider_doctor_v0"
VALIDATION_SCHEMA_VERSION = "loopx_local_synthetic_overlay_validation_v1"
CLEANUP_SCHEMA_VERSION = "loopx_local_synthetic_overlay_cleanup_v1"
ISSUER_ID = "loopx-native-local-synthetic-overlay"
PROVIDER_REVISION = "local-docker-disposable-v0"
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 8 * 60 * 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_PINNED_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_RECEIPT_ID = re.compile(r"^overlay_[0-9a-f]{24}$")
_COMPOSE_PROJECT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _canonical_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("overlay receipt must be JSON serializable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def _required_token(value: object, label: str, *, maximum: int = 200) -> str:
    token = str(value or "").strip()
    if not token or len(token) > maximum or any(char.isspace() for char in token):
        raise ValueError(f"{label} must be a non-empty bounded token")
    return token


def _commit(value: object, label: str) -> str:
    commit = str(value or "").strip().lower()
    if not _HEX40.fullmatch(commit):
        raise ValueError(f"{label} must be an exact 40-character lowercase Git id")
    return commit


def _capabilities(values: object) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError("capabilities must be a sequence")
    normalized = sorted({_required_token(item, "capability") for item in values})
    if normalized != sorted(ALLOWED_CAPABILITIES):
        raise ValueError(
            "local synthetic validation requires exactly capabilities "
            f"{list(ALLOWED_CAPABILITIES)}; subsets and escalation are rejected"
        )
    return normalized


def _require_restrictive_envelope(
    *,
    scope: str,
    product_write_scope: str,
    lifetime: str,
    reusable_across_tasks: bool,
    real_customer_data: bool,
    real_child_data: bool,
    real_audio: bool,
    real_provider: bool,
    production: bool,
) -> dict[str, bool]:
    if scope != LOCAL_SYNTHETIC_SCOPE:
        raise ValueError(f"scope must be exact `{LOCAL_SYNTHETIC_SCOPE}`")
    if product_write_scope != PRODUCT_WRITE_SCOPE_ZERO:
        raise ValueError("product_write_scope must be exact `ZERO`")
    if lifetime != "task_bound":
        raise ValueError("lifetime must be exact `task_bound`")
    restrictions = {
        "real_customer_data": bool(real_customer_data),
        "real_child_data": bool(real_child_data),
        "real_audio": bool(real_audio),
        "real_provider": bool(real_provider),
        "production": bool(production),
    }
    if reusable_across_tasks or any(restrictions.values()):
        raise ValueError(
            "local synthetic overlay rejects cross-task reuse and every real or production resource"
        )
    return restrictions


def _image_reference(value: object) -> str:
    image = str(value or "").strip()
    if not _DIGEST_PINNED_IMAGE.fullmatch(image):
        raise ValueError(
            "synthetic database image must be an exact local digest-pinned reference"
        )
    return image


def _compose_project(value: object) -> str:
    project = str(value or "").strip()
    if not _COMPOSE_PROJECT.fullmatch(project):
        raise ValueError("compose_project must be a bounded lowercase local token")
    return project


def doctor_local_synthetic_providers(
    *,
    synthetic_database_image: str,
    runner: CommandRunner = _run,
    which: Which = shutil.which,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Truthfully inspect local providers without pulling or creating resources."""

    image = _image_reference(synthetic_database_image)
    observed_at = checked_at or _now_utc()
    docker = which("docker")
    docker_client = bool(docker)
    daemon_ready = False
    image_ready = False
    daemon_status = "docker_client_missing"
    image_status = "not_checked"
    if docker:
        try:
            daemon = runner(
                [docker, "version", "--format", "{{json .Server.Version}}"],
                8.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            daemon_status = "docker_daemon_unavailable"
        else:
            daemon_ready = daemon.returncode == 0 and bool(daemon.stdout.strip())
            daemon_status = "ready" if daemon_ready else "docker_daemon_unavailable"
        if daemon_ready:
            try:
                inspected = runner(
                    [docker, "image", "inspect", "--format", "{{json .Id}}", image],
                    8.0,
                )
            except (OSError, subprocess.TimeoutExpired):
                image_status = "local_image_unavailable"
            else:
                image_ready = (
                    inspected.returncode == 0 and "sha256:" in inspected.stdout
                )
                image_status = "ready" if image_ready else "local_image_unavailable"

    local_container_ready = docker_client and daemon_ready
    synthetic_database_ready = local_container_ready and image_ready
    payload: dict[str, Any] = {
        "ok": local_container_ready and synthetic_database_ready,
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "checked_at": utc_isoformat(observed_at),
        "provider_revision": PROVIDER_REVISION,
        "network_pull_attempted": False,
        "resource_created": False,
        "providers": {
            "local_container": {
                "provider_id": "loopx-local-docker-container",
                "ready": local_container_ready,
                "status": daemon_status,
                "scope": LOCAL_SYNTHETIC_SCOPE,
                "arbitrary_command_execution": False,
                "production_deployment": False,
            },
            "synthetic_database": {
                "provider_id": "loopx-local-disposable-synthetic-database",
                "ready": synthetic_database_ready,
                "status": image_status,
                "image": image,
                "pull_policy": "never",
                "database_class": "disposable_local_synthetic_only",
                "hosted_or_production": False,
                "cleanup_readback_required": True,
            },
        },
    }
    payload["doctor_digest"] = _canonical_digest(
        {key: value for key, value in payload.items() if key != "doctor_digest"}
    )
    return payload


def _git(repo: Path, *args: str) -> str:
    try:
        result = _run(["git", "-C", str(repo), *args], 10.0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("candidate Git state could not be inspected") from exc
    if result.returncode != 0:
        raise ValueError("candidate Git state could not be inspected")
    return result.stdout.strip()


def _git_worktree_identity(repository: str | Path, *, label: str) -> tuple[Path, Path]:
    repo = Path(repository).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError(f"{label} must be an existing local directory")
    root = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if root != repo:
        raise ValueError(f"{label} must be the exact Git worktree root")
    common_directory = Path(
        _git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        )
    ).resolve()
    if not common_directory.is_dir():
        raise ValueError(f"{label} Git repository identity is unavailable")
    return root, common_directory


def _same_git_repository(candidate: Path, registered: Path) -> bool:
    try:
        return candidate.samefile(registered)
    except OSError:
        return False


def _candidate_snapshot(
    repository: str | Path,
    *,
    registered_repository: str | Path,
    candidate_head: str,
    candidate_tree: str,
) -> dict[str, str]:
    repo, candidate_common_directory = _git_worktree_identity(
        repository,
        label="repository",
    )
    _, registered_common_directory = _git_worktree_identity(
        registered_repository,
        label="Goal registry repository",
    )
    if not _same_git_repository(
        candidate_common_directory,
        registered_common_directory,
    ):
        raise ValueError(
            "candidate repository does not match the Goal registry Git repository"
        )
    expected_head = _commit(candidate_head, "candidate_head")
    expected_tree = _commit(candidate_tree, "candidate_tree")
    observed_head = _git(repo, "rev-parse", "HEAD").lower()
    observed_tree = _git(repo, "rev-parse", "HEAD^{tree}").lower()
    if observed_head != expected_head:
        raise ValueError("candidate HEAD does not match the live repository")
    if observed_tree != expected_tree:
        raise ValueError("candidate tree does not match the live repository")
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=no"):
        raise ValueError("candidate tracked worktree must be clean")
    return {
        "repository": str(repo),
        "head": observed_head,
        "tree": observed_tree,
        "tracked_state": "clean",
    }


def _active_goal_todo(
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    goal_id: str,
    todo_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry = load_registry(registry_path)
    goal = find_registry_goal(registry, goal_id)
    if goal is None:
        raise ValueError(f"Goal `{goal_id}` is not present in the LoopX registry")
    _, _, state_file = resolve_goal_state(
        registry=registry,
        goal_id=goal_id,
        project_override=None,
        state_file_override=None,
    )
    if not state_file.is_file():
        raise ValueError(f"Goal `{goal_id}` active state does not exist")
    match = find_todo_block(
        state_file.read_text(encoding="utf-8").splitlines(),
        todo_id=todo_id,
    )
    if match is None:
        raise ValueError(
            f"Todo `{todo_id}` is not active and unique for Goal `{goal_id}`"
        )
    todo = match[-1]
    status = str(todo.get("status") or "open").strip().lower()
    if status not in {"open", "blocked"}:
        raise ValueError("overlay receipt requires an active open or blocked Todo")
    return dict(goal), dict(todo)


def _registered_goal_repository(goal: Mapping[str, Any]) -> Path:
    repository = str(goal.get("repo") or "").strip()
    if not repository:
        raise ValueError("Goal registry entry does not name a repository")
    return Path(repository).expanduser()


def _receipt_directory(runtime_root: Path) -> Path:
    return runtime_root / "special-overlays" / "local-synthetic-validation-v0"


def _receipt_path(runtime_root: Path, receipt_id: str) -> Path:
    normalized = str(receipt_id or "").strip()
    if not _RECEIPT_ID.fullmatch(normalized):
        raise ValueError("receipt_id is invalid")
    return _receipt_directory(runtime_root) / f"{normalized}.json"


def _resolved_runtime_root(
    *, registry_path: Path, runtime_root_arg: str | None
) -> Path:
    resolved = resolve_runtime_root(
        load_registry(registry_path),
        runtime_root_arg,
        registry_path=registry_path,
    )
    return Path(resolved).expanduser().resolve()


def issue_local_synthetic_overlay_receipt(
    *,
    registry_path: str | Path,
    runtime_root_arg: str | None,
    goal_id: str,
    todo_id: str,
    repository: str | Path,
    candidate_head: str,
    candidate_tree: str,
    capabilities: Sequence[str],
    synthetic_database_image: str,
    compose_project: str,
    scope: str = LOCAL_SYNTHETIC_SCOPE,
    product_write_scope: str = PRODUCT_WRITE_SCOPE_ZERO,
    lifetime: str = "task_bound",
    reusable_across_tasks: bool = False,
    real_customer_data: bool = False,
    real_child_data: bool = False,
    real_audio: bool = False,
    real_provider: bool = False,
    production: bool = False,
    ttl_seconds: int = 4 * 60 * 60,
    execute: bool = False,
    now: datetime | None = None,
    token_factory: Callable[[], str] = lambda: secrets.token_hex(24),
    doctor: Callable[..., dict[str, Any]] = doctor_local_synthetic_providers,
) -> dict[str, Any]:
    """Issue one exact task-bound receipt into LoopX-managed local state."""

    registry = Path(registry_path).expanduser().resolve()
    normalized_goal = _required_token(goal_id, "goal_id")
    normalized_todo = _required_token(todo_id, "todo_id")
    normalized_capabilities = _capabilities(capabilities)
    restrictions = _require_restrictive_envelope(
        scope=scope,
        product_write_scope=product_write_scope,
        lifetime=lifetime,
        reusable_across_tasks=reusable_across_tasks,
        real_customer_data=real_customer_data,
        real_child_data=real_child_data,
        real_audio=real_audio,
        real_provider=real_provider,
        production=production,
    )
    try:
        normalized_ttl = int(ttl_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("ttl_seconds must be an integer") from exc
    if not MIN_TTL_SECONDS <= normalized_ttl <= MAX_TTL_SECONDS:
        raise ValueError(
            f"ttl_seconds must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS}"
        )
    image = _image_reference(synthetic_database_image)
    project = _compose_project(compose_project)
    goal, _ = _active_goal_todo(
        registry_path=registry,
        runtime_root_arg=runtime_root_arg,
        goal_id=normalized_goal,
        todo_id=normalized_todo,
    )
    candidate = _candidate_snapshot(
        repository,
        registered_repository=_registered_goal_repository(goal),
        candidate_head=candidate_head,
        candidate_tree=candidate_tree,
    )
    provider_doctor = doctor(synthetic_database_image=image)
    if provider_doctor.get("ok") is not True:
        raise ValueError("local synthetic overlay providers are not doctor-ready")
    doctor_digest = str(provider_doctor.get("doctor_digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", doctor_digest):
        raise ValueError("provider doctor did not return a valid evidence digest")

    issued_at = (now or _now_utc()).astimezone(timezone.utc).replace(microsecond=0)
    expires_at = issued_at + timedelta(seconds=normalized_ttl)
    receipt_id = (
        "overlay_"
        + hashlib.sha256(
            (
                token_factory()
                + "\0"
                + normalized_goal
                + "\0"
                + normalized_todo
                + "\0"
                + candidate["head"]
                + "\0"
                + candidate["tree"]
            ).encode("utf-8")
        ).hexdigest()[:24]
    )
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "issued_by": ISSUER_ID,
        "authority_path": "loopx_native",
        "system_managed": True,
        "goal_id": normalized_goal,
        "todo_id": normalized_todo,
        "candidate": candidate,
        "compose_project": project,
        "scope": scope,
        "capabilities": normalized_capabilities,
        "product_write_scope": product_write_scope,
        "lifetime": lifetime,
        "reusable_across_tasks": False,
        "restrictions": restrictions,
        "provider_binding": {
            "revision": PROVIDER_REVISION,
            "synthetic_database_image": image,
            "doctor_digest": doctor_digest,
        },
        "issued_at": utc_isoformat(issued_at),
        "expires_at": utc_isoformat(expires_at),
    }
    digest = _canonical_digest(receipt)
    runtime_root = _resolved_runtime_root(
        registry_path=registry, runtime_root_arg=runtime_root_arg
    )
    path = _receipt_path(runtime_root, receipt_id)
    packet: dict[str, Any] = {
        "ok": True,
        "schema_version": STORE_SCHEMA_VERSION,
        "status": "ready" if not execute else "issued",
        "dry_run": not execute,
        "executed": execute,
        "system_managed": execute,
        "receipt": receipt if execute else None,
        "receipt_id": receipt_id if execute else None,
        "receipt_digest": digest if execute else None,
        "receipt_path": str(path) if execute else None,
        "provider_doctor": provider_doctor,
        "would_bind": receipt if not execute else None,
        "legacy_dispatcher_used": False,
    }
    if execute:
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        if path.exists():
            raise ValueError("system-generated overlay receipt identity collision")
        atomic_write_json(
            path,
            {
                "schema_version": STORE_SCHEMA_VERSION,
                "receipt": receipt,
                "receipt_digest": digest,
            },
        )
        os.chmod(path, 0o600)
    return packet


def _load_store_record(
    runtime_root: Path, receipt_id: str
) -> tuple[Path, dict[str, Any]]:
    path = _receipt_path(runtime_root, receipt_id)
    if not path.is_file():
        raise ValueError("system-managed overlay receipt does not exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("system-managed overlay receipt is unreadable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != STORE_SCHEMA_VERSION
    ):
        raise ValueError("system-managed overlay receipt store record is invalid")
    return path, payload


def validate_local_synthetic_overlay_receipt(
    *,
    registry_path: str | Path,
    runtime_root_arg: str | None,
    receipt_id: str,
    goal_id: str,
    todo_id: str,
    repository: str | Path,
    candidate_head: str,
    candidate_tree: str,
    capabilities: Sequence[str],
    synthetic_database_image: str,
    compose_project: str,
    scope: str = LOCAL_SYNTHETIC_SCOPE,
    product_write_scope: str = PRODUCT_WRITE_SCOPE_ZERO,
    lifetime: str = "task_bound",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a stored receipt against the exact live task and candidate."""

    registry = Path(registry_path).expanduser().resolve()
    normalized_goal = _required_token(goal_id, "goal_id")
    normalized_todo = _required_token(todo_id, "todo_id")
    normalized_capabilities = _capabilities(capabilities)
    _require_restrictive_envelope(
        scope=scope,
        product_write_scope=product_write_scope,
        lifetime=lifetime,
        reusable_across_tasks=False,
        real_customer_data=False,
        real_child_data=False,
        real_audio=False,
        real_provider=False,
        production=False,
    )
    image = _image_reference(synthetic_database_image)
    project = _compose_project(compose_project)
    runtime_root = _resolved_runtime_root(
        registry_path=registry, runtime_root_arg=runtime_root_arg
    )
    path, record = _load_store_record(runtime_root, receipt_id)
    receipt = record.get("receipt")
    digest = str(record.get("receipt_digest") or "")
    if not isinstance(receipt, Mapping) or digest != _canonical_digest(receipt):
        raise ValueError("system-managed overlay receipt digest is invalid")
    goal, _ = _active_goal_todo(
        registry_path=registry,
        runtime_root_arg=runtime_root_arg,
        goal_id=normalized_goal,
        todo_id=normalized_todo,
    )
    expected_candidate = _candidate_snapshot(
        repository,
        registered_repository=_registered_goal_repository(goal),
        candidate_head=candidate_head,
        candidate_tree=candidate_tree,
    )
    expires = parse_timestamp(receipt.get("expires_at"))
    current = (now or _now_utc()).astimezone(timezone.utc)
    if expires is None or expires <= current:
        raise ValueError("system-managed overlay receipt is expired")
    expected = {
        "receipt_id": receipt_id,
        "issued_by": ISSUER_ID,
        "authority_path": "loopx_native",
        "system_managed": True,
        "goal_id": normalized_goal,
        "todo_id": normalized_todo,
        "candidate": expected_candidate,
        "compose_project": project,
        "scope": scope,
        "capabilities": normalized_capabilities,
        "product_write_scope": product_write_scope,
        "lifetime": lifetime,
        "reusable_across_tasks": False,
        "restrictions": {
            "real_customer_data": False,
            "real_child_data": False,
            "real_audio": False,
            "real_provider": False,
            "production": False,
        },
    }
    mismatches = [key for key, value in expected.items() if receipt.get(key) != value]
    provider_binding = receipt.get("provider_binding")
    if not isinstance(provider_binding, Mapping):
        mismatches.append("provider_binding")
    else:
        if provider_binding.get("revision") != PROVIDER_REVISION:
            mismatches.append("provider_revision")
        if provider_binding.get("synthetic_database_image") != image:
            mismatches.append("synthetic_database_image")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        mismatches.append("schema_version")
    if mismatches:
        raise ValueError(
            "system-managed overlay receipt binding mismatch: "
            + ", ".join(sorted(set(mismatches)))
        )
    return {
        "ok": True,
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "status": "valid",
        "valid": True,
        "system_managed": True,
        "receipt_id": receipt_id,
        "receipt_digest": digest,
        "receipt_path": str(path),
        "goal_id": normalized_goal,
        "todo_id": normalized_todo,
        "candidate_head": expected_candidate["head"],
        "candidate_tree": expected_candidate["tree"],
        "compose_project": project,
        "capabilities": normalized_capabilities,
        "scope": scope,
        "product_write_scope": product_write_scope,
        "expires_at": receipt.get("expires_at"),
        "legacy_dispatcher_used": False,
    }


def verify_compose_cleanup(
    *,
    validation: Mapping[str, Any],
    compose_project: str,
    runner: CommandRunner = _run,
    which: Which = shutil.which,
) -> dict[str, Any]:
    """Prove a task-labelled Compose project left no container/volume/network."""

    if validation.get("valid") is not True:
        raise ValueError("cleanup readback requires a valid task-bound overlay receipt")
    project = _compose_project(compose_project)
    bound_project = _compose_project(validation.get("compose_project"))
    if project != bound_project:
        raise ValueError("compose_project does not match the validated overlay receipt")
    project = bound_project
    docker = which("docker")
    if not docker:
        raise ValueError("Docker client is unavailable for cleanup readback")
    filters = {
        "containers": [
            docker,
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        "volumes": [
            docker,
            "volume",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        "networks": [
            docker,
            "network",
            "ls",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
    }
    residual_counts: dict[str, int] = {}
    for kind, argv in filters.items():
        try:
            result = runner(argv, 8.0)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError("Docker cleanup readback failed") from exc
        if result.returncode != 0:
            raise ValueError("Docker cleanup readback failed")
        residual_counts[kind] = len(
            [line for line in result.stdout.splitlines() if line.strip()]
        )
    clean = not any(residual_counts.values())
    return {
        "ok": clean,
        "schema_version": CLEANUP_SCHEMA_VERSION,
        "status": "clean" if clean else "residue_detected",
        "clean": clean,
        "compose_project": project,
        "residual_counts": residual_counts,
        "receipt_id": validation.get("receipt_id"),
    }

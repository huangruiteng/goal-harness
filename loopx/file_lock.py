from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
import importlib
from typing import Any, Iterator, TextIO
from uuid import uuid4

try:  # pragma: no cover - exercised on POSIX hosts in integration smokes.
    fcntl: Any = importlib.import_module("fcntl")
except ImportError:  # pragma: no cover
    fcntl = None

try:  # pragma: no cover - imported only on Windows hosts.
    msvcrt: Any = importlib.import_module("msvcrt")
except ImportError:  # pragma: no cover
    msvcrt = None


def _prepare_windows_lock(lock_file: TextIO) -> None:
    lock_file.seek(0, 2)
    if lock_file.tell() == 0:
        lock_file.write("0")
        lock_file.flush()
    lock_file.seek(0)


def _try_acquire_kernel_lock(lock_file: TextIO) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if not _lock_is_busy(exc):
                raise
            return False
        return True
    if msvcrt is None:
        raise RuntimeError("no supported file-lock backend is available")

    _prepare_windows_lock(lock_file)
    try:
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        if not _lock_is_busy(exc):
            raise
        return False
    return True


def _release_kernel_lock(lock_file: TextIO) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    elif msvcrt is not None:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


LOCK_ACQUIRE_TIMEOUT_ERROR_CODE = "lock_acquire_timeout"
LOCK_HOLDER_SCHEMA_VERSION = "file_lock_holder_v0"
LOCK_INCIDENT_SCHEMA_VERSION = "file_lock_incident_v0"
_SAFE_LABEL_PATTERN = re.compile(r"[^A-Za-z0-9._:@-]+")


class LockAcquisitionPolicy(str, Enum):
    MUTATION = "mutation"
    MONITOR = "monitor"
    SINGLE_FLIGHT = "single_flight"


@dataclass(frozen=True, slots=True)
class LockPolicy:
    timeout_seconds: float
    poll_interval_seconds: float
    retry_mode: str


LOCK_POLICIES = {
    LockAcquisitionPolicy.MUTATION: LockPolicy(
        timeout_seconds=5.0,
        poll_interval_seconds=0.05,
        retry_mode="manual_after_holder_inspection",
    ),
    LockAcquisitionPolicy.MONITOR: LockPolicy(
        timeout_seconds=1.0,
        poll_interval_seconds=0.10,
        retry_mode="next_scheduled_poll_after_holder_inspection",
    ),
    LockAcquisitionPolicy.SINGLE_FLIGHT: LockPolicy(
        timeout_seconds=0.0,
        poll_interval_seconds=0.0,
        retry_mode="skip_duplicate_attempt",
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_label(value: object, *, fallback: str) -> str:
    compact = _SAFE_LABEL_PATTERN.sub("_", str(value or "").strip()).strip("._-")
    return compact[:128] or fallback


def _policy(value: LockAcquisitionPolicy | str) -> LockAcquisitionPolicy:
    if isinstance(value, LockAcquisitionPolicy):
        return value
    return LockAcquisitionPolicy(str(value))


def _lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


def lock_holder_path(path: Path) -> Path:
    lock_path = _lock_path(path)
    if os.name == "nt":
        return lock_path.with_name(f"{lock_path.name}.holder.json")
    return lock_path


def lock_incident_path(path: Path) -> Path:
    lock_path = _lock_path(path)
    return lock_path.with_name(f"{lock_path.name}.incidents.jsonl")


def _lock_id(path: Path) -> str:
    resolved = str(path.expanduser().resolve(strict=False)).encode("utf-8")
    return hashlib.sha256(resolved).hexdigest()[:16]


def _identity(
    *,
    agent_id: str | None,
    operation: str | None,
    policy: LockAcquisitionPolicy,
) -> dict[str, object]:
    return {
        "pid": os.getpid(),
        "agent_id": _safe_label(
            agent_id or os.environ.get("LOOPX_AGENT_ID"),
            fallback="unknown",
        ),
        "operation": _safe_label(operation or policy.value, fallback=policy.value),
    }


def _holder_record(
    path: Path,
    *,
    agent_id: str | None,
    operation: str | None,
    policy: LockAcquisitionPolicy,
) -> dict[str, object]:
    return {
        "schema_version": LOCK_HOLDER_SCHEMA_VERSION,
        "lock_id": _lock_id(path),
        "policy": policy.value,
        **_identity(agent_id=agent_id, operation=operation, policy=policy),
        "acquired_at": _utc_now_iso(),
    }


def _write_holder_record(lock_file: TextIO, record: dict[str, object]) -> None:
    lock_file.seek(0)
    lock_file.truncate()
    json.dump(record, lock_file, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    lock_file.write("\n")
    lock_file.flush()
    os.fsync(lock_file.fileno())


def _write_holder_sidecar(holder_path: Path, record: dict[str, object]) -> None:
    holder_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{holder_path.name}.",
        suffix=".tmp",
        dir=holder_path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as holder_file:
            json.dump(
                record,
                holder_file,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            holder_file.write("\n")
            holder_file.flush()
            os.fsync(holder_file.fileno())
        os.replace(temporary_path, holder_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _persist_holder_record(
    lock_file: TextIO,
    *,
    lock_path: Path,
    holder_path: Path,
    record: dict[str, object],
) -> None:
    if holder_path == lock_path:
        _write_holder_record(lock_file, record)
        return
    _write_holder_sidecar(holder_path, record)


def _mark_released(
    lock_file: TextIO,
    *,
    lock_path: Path,
    holder_path: Path,
    record: dict[str, object],
) -> None:
    released = {**record, "released_at": _utc_now_iso()}
    try:
        _persist_holder_record(
            lock_file,
            lock_path=lock_path,
            holder_path=holder_path,
            record=released,
        )
    except OSError:
        # Releasing the kernel lock is more important than refreshing advisory
        # metadata; a future holder overwrites the complete record.
        pass


def _read_holder_record(lock_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    allowed = {
        "schema_version",
        "lock_id",
        "policy",
        "pid",
        "agent_id",
        "operation",
        "acquired_at",
        "released_at",
    }
    return {key: payload[key] for key in allowed if key in payload}


def _operator_action(holder: dict[str, object], *, retry_mode: str) -> dict[str, object]:
    return {
        "required": True,
        "action": "inspect_lock_holder",
        "holder_pid": holder.get("pid"),
        "retry_mode": retry_mode,
        "steps": [
            "Inspect the recorded holder PID and operation.",
            "Confirm the process is stalled before terminating it.",
            "Retry according to retry_mode after the holder exits.",
            "Do not delete the lock file; the kernel lock is authoritative.",
        ],
    }


def _append_incident(path: Path, record: dict[str, object]) -> bool:
    incident_path = lock_incident_path(path)
    incident_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(
            incident_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return True


class LockAcquireTimeoutError(TimeoutError):
    code = LOCK_ACQUIRE_TIMEOUT_ERROR_CODE

    def __init__(
        self,
        *,
        incident: dict[str, object],
        incident_recorded: bool,
        incident_channel: str,
    ) -> None:
        self.incident = incident
        self.incident_recorded = incident_recorded
        self.incident_channel = incident_channel
        raw_holder = incident.get("holder")
        holder: dict[str, object] = raw_holder if isinstance(raw_holder, dict) else {}
        super().__init__(
            "file lock acquisition timed out"
            + (f" while waiting for holder pid {holder.get('pid')}" if holder.get("pid") else "")
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "error_code": self.code,
            "lock_timeout": self.incident,
            "incident_recorded": self.incident_recorded,
            "incident_channel": self.incident_channel,
            "operator_action": self.incident["operator_action"],
        }


def lock_timeout_error_fields(error: BaseException) -> dict[str, object]:
    if isinstance(error, LockAcquireTimeoutError):
        return error.to_payload()
    return {}


def _timeout_error(
    path: Path,
    *,
    policy: LockAcquisitionPolicy,
    timeout_seconds: float,
    waited_seconds: float,
    started_at: str,
    agent_id: str | None,
    operation: str | None,
) -> LockAcquireTimeoutError:
    holder = _read_holder_record(lock_holder_path(path))
    waiter = {
        **_identity(agent_id=agent_id, operation=operation, policy=policy),
        "started_at": started_at,
        "timeout_seconds": round(timeout_seconds, 3),
        "waited_seconds": round(waited_seconds, 3),
    }
    action = _operator_action(holder, retry_mode=LOCK_POLICIES[policy].retry_mode)
    incident: dict[str, object] = {
        "schema_version": LOCK_INCIDENT_SCHEMA_VERSION,
        "error_code": LOCK_ACQUIRE_TIMEOUT_ERROR_CODE,
        "recorded_at": _utc_now_iso(),
        "lock_id": _lock_id(path),
        "policy": policy.value,
        "holder": holder,
        "waiter": waiter,
        "operator_action": action,
    }
    recorded = _append_incident(path, incident)
    return LockAcquireTimeoutError(
        incident=incident,
        incident_recorded=recorded,
        incident_channel=lock_incident_path(path).name,
    )


def _lock_is_busy(error: OSError) -> bool:
    return isinstance(error, BlockingIOError) or error.errno in {
        errno.EACCES,
        errno.EAGAIN,
    }


@contextmanager
def exclusive_file_lock(
    path: Path,
    *,
    policy: LockAcquisitionPolicy | str = LockAcquisitionPolicy.MUTATION,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
    agent_id: str | None = None,
    operation: str | None = None,
) -> Iterator[Path]:
    """Hold a sibling lock file with a finite cross-platform deadline."""

    selected_policy = _policy(policy)
    defaults = LOCK_POLICIES[selected_policy]
    timeout = defaults.timeout_seconds if timeout_seconds is None else max(0.0, timeout_seconds)
    poll_interval = (
        defaults.poll_interval_seconds
        if poll_interval_seconds is None
        else max(0.001, poll_interval_seconds)
    )
    lock_path = _lock_path(path)
    holder_path = lock_holder_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as lock_file:
        started = time.monotonic()
        started_at = _utc_now_iso()
        deadline = started + timeout
        while not _try_acquire_kernel_lock(lock_file):
            now = time.monotonic()
            if now >= deadline:
                raise _timeout_error(
                    path,
                    policy=selected_policy,
                    timeout_seconds=timeout,
                    waited_seconds=now - started,
                    started_at=started_at,
                    agent_id=agent_id,
                    operation=operation,
                ) from None
            time.sleep(min(poll_interval, max(0.0, deadline - now)))
        record = _holder_record(
            path,
            agent_id=agent_id,
            operation=operation,
            policy=selected_policy,
        )
        try:
            _persist_holder_record(
                lock_file,
                lock_path=lock_path,
                holder_path=holder_path,
                record=record,
            )
            yield lock_path
        finally:
            _mark_released(
                lock_file,
                lock_path=lock_path,
                holder_path=holder_path,
                record=record,
            )
            _release_kernel_lock(lock_file)


@contextmanager
def try_exclusive_file_lock(
    path: Path,
    *,
    agent_id: str | None = None,
    operation: str | None = None,
) -> Iterator[Path | None]:
    """Try once to hold a sibling lock file for single-flight work.

    ``None`` means another process already owns the lock. POSIX uses ``flock``;
    Windows uses the standard-library ``msvcrt`` byte-range lock.
    """

    lock_path = _lock_path(path)
    holder_path = lock_holder_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as lock_file:
        if not _try_acquire_kernel_lock(lock_file):
            yield None
            return
        record = _holder_record(
            path,
            agent_id=agent_id,
            operation=operation,
            policy=LockAcquisitionPolicy.SINGLE_FLIGHT,
        )
        try:
            _persist_holder_record(
                lock_file,
                lock_path=lock_path,
                holder_path=holder_path,
                record=record,
            )
            yield lock_path
        finally:
            _mark_released(
                lock_file,
                lock_path=lock_path,
                holder_path=holder_path,
                record=record,
            )
            _release_kernel_lock(lock_file)


EFFECT_MUTATION_LOCK_SUFFIX = ".ts-effect.lock"
EFFECT_MUTATION_INVALID_STALE_SECONDS = 10.0


def _effect_mutation_lock_path(path: Path) -> Path:
    return Path(f"{path}{EFFECT_MUTATION_LOCK_SUFFIX}")


def process_is_alive(pid: object) -> bool:
    """Probe a process without sending signals or console control events."""

    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        # Windows signal 0 is CTRL_C_EVENT, not the side-effect-free POSIX
        # existence probe provided by kill(pid, 0).
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def _windows_process_is_alive(pid: int) -> bool:
    """Probe a Windows process without sending a console control event."""

    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    error_access_denied = 5
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(synchronize, False, pid)
    if not handle:
        return bool(getattr(ctypes, "get_last_error")() == error_access_denied)
    try:
        return bool(wait_for_single_object(handle, 0) == wait_timeout)
    finally:
        close_handle(handle)


def _effect_mutation_process_is_alive(pid: object) -> bool:
    return process_is_alive(pid)


def _read_effect_mutation_owner(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    token = payload.get("token")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or not isinstance(token, str)
    ):
        return None
    return {"pid": pid, "token": token}


def _reclaim_stale_effect_mutation_lock(path: Path) -> None:
    owner = _read_effect_mutation_owner(path)
    if owner is not None and _effect_mutation_process_is_alive(owner.get("pid")):
        return
    if owner is None:
        try:
            age_seconds = time.time() - path.stat().st_mtime
        except OSError:
            return
        if age_seconds < EFFECT_MUTATION_INVALID_STALE_SECONDS:
            return
    stale_path = path.with_name(f"{path.name}.stale.{uuid4()}")
    try:
        path.replace(stale_path)
    except FileNotFoundError:
        return
    stale_path.unlink(missing_ok=True)


@contextmanager
def exclusive_cross_runtime_file_lock(
    path: Path,
    *,
    policy: LockAcquisitionPolicy | str = LockAcquisitionPolicy.MUTATION,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
    agent_id: str | None = None,
    operation: str | None = None,
) -> Iterator[Path]:
    """Hold the TypeScript mutation lock, then the existing Python lock.

    This is a bounded migration lock for state whose writers span both
    runtimes. TypeScript coordinates through exclusive creation of
    ``<target>.ts-effect.lock``; Python keeps its kernel lock underneath so
    existing diagnostics and Python-to-Python exclusion remain unchanged.
    """

    selected_policy = _policy(policy)
    defaults = LOCK_POLICIES[selected_policy]
    timeout = (
        defaults.timeout_seconds
        if timeout_seconds is None
        else max(0.0, timeout_seconds)
    )
    poll_interval = (
        defaults.poll_interval_seconds
        if poll_interval_seconds is None
        else max(0.001, poll_interval_seconds)
    )
    effect_lock_path = _effect_mutation_lock_path(path)
    effect_lock_path.parent.mkdir(parents=True, exist_ok=True)
    token = str(uuid4())
    started = time.monotonic()
    started_at = _utc_now_iso()
    deadline = started + timeout
    while True:
        try:
            descriptor = os.open(
                effect_lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            _reclaim_stale_effect_mutation_lock(effect_lock_path)
            now = time.monotonic()
            if now >= deadline:
                raise _timeout_error(
                    path,
                    policy=selected_policy,
                    timeout_seconds=timeout,
                    waited_seconds=now - started,
                    started_at=started_at,
                    agent_id=agent_id,
                    operation=operation,
                ) from None
            time.sleep(min(poll_interval, max(0.0, deadline - now)))
            continue
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
                json.dump(
                    {"pid": os.getpid(), "token": token},
                    lock_file,
                    separators=(",", ":"),
                )
                lock_file.flush()
                os.fsync(lock_file.fileno())
        except BaseException:
            effect_lock_path.unlink(missing_ok=True)
            raise
        break

    try:
        with exclusive_file_lock(
            path,
            policy=selected_policy,
            timeout_seconds=timeout,
            poll_interval_seconds=poll_interval,
            agent_id=agent_id,
            operation=operation,
        ) as lock_path:
            yield lock_path
    finally:
        owner = _read_effect_mutation_owner(effect_lock_path)
        if owner is not None and owner.get("token") == token:
            effect_lock_path.unlink(missing_ok=True)

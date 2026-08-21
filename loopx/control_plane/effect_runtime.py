from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any


EFFECT_RUNTIME_REQUEST_SCHEMA_VERSION = "loopx_effect_runtime_request_v0"
EFFECT_RUNTIME_RESPONSE_SCHEMA_VERSION = "loopx_effect_runtime_response_v0"
EFFECT_RUNTIME_INFO_SCHEMA_VERSION = "loopx_effect_runtime_info_v0"
EFFECT_RUNTIME_READINESS_SCHEMA_VERSION = "loopx_effect_runtime_readiness_v0"
MINIMUM_NODE_VERSION = (22, 6, 0)
MINIMUM_NODE_VERSION_TEXT = ".".join(str(part) for part in MINIMUM_NODE_VERSION)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
_NODE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")
_SOURCE_FILES = (
    "effect_program.ts",
    "governed_capability.ts",
    "effect_runtime_handlers.ts",
    "effect_runtime_io.ts",
    "effect_runtime_server.ts",
    "todos/completion_fence.ts",
    "todos/completion_state.ts",
    "todos/next_action.ts",
    "turn_driver/turn_journal.ts",
    "turn_driver/turn_journal_effects.ts",
    "turn_transaction_contract.json",
)


class EffectRuntimeRejected(RuntimeError):
    """A typed request reached the runtime but failed semantic validation."""


class EffectRuntimeStartupError(RuntimeError):
    """The managed runtime could not reach a request-serving state."""

    def __init__(self, message: str, *, diagnostic_code: str) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code


def _control_plane_root() -> Path:
    return Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def _runtime_fingerprint() -> str:
    digest = hashlib.sha256()
    root = _control_plane_root()
    for relative in _SOURCE_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update((root / relative).read_bytes())
    return digest.hexdigest()


def _runtime_dir() -> Path:
    owner = str(getattr(os, "getuid", lambda: Path.home())())
    suffix = hashlib.sha256(owner.encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"loopx-effect-runtime-{suffix}"


def _runtime_info_path(fingerprint: str) -> Path:
    return _runtime_dir() / f"runtime-{fingerprint[:16]}.json"


def _runtime_server_path() -> Path:
    return _control_plane_root() / "effect_runtime_server.ts"


def _node_executable() -> str:
    status, executable, _version = _probe_node()
    if status != "ready" or executable is None:
        raise RuntimeError(
            f"LoopX Effect runtime requires Node.js {MINIMUM_NODE_VERSION_TEXT} "
            "or newer"
        )
    return executable


def _probe_node() -> tuple[str, str | None, str | None]:
    executable = shutil.which("node")
    if executable is None:
        return "missing", None, None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "probe_failed", executable, None
    match = _NODE_VERSION_RE.fullmatch(completed.stdout.strip())
    version = tuple(int(part) for part in match.groups()) if match else None
    if completed.returncode != 0 or version is None:
        return "probe_failed", executable, None
    version_text = ".".join(str(part) for part in version)
    if version < MINIMUM_NODE_VERSION:
        return "unsupported", executable, version_text
    return "ready", executable, version_text


def _pid_is_alive(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return False
    if os.name == "nt":
        # Windows signal 0 is CTRL_C_EVENT, not the side-effect-free POSIX
        # existence probe provided by kill(pid, 0).
        return _windows_pid_is_alive(value)
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_is_alive(pid: int) -> bool:
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
        # An access-denied process still exists; it is merely outside the
        # caller's query authority.
        return bool(getattr(ctypes, "get_last_error")() == error_access_denied)
    try:
        return bool(wait_for_single_object(handle, 0) == wait_timeout)
    finally:
        close_handle(handle)


def _start_lock_holder_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if value > 0 else None


def _read_info(path: Path, *, fingerprint: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    if (
        payload.get("schema_version") != EFFECT_RUNTIME_INFO_SCHEMA_VERSION
        or payload.get("fingerprint") != fingerprint
        or payload.get("host") != "127.0.0.1"
        or not isinstance(payload.get("port"), int)
        or not isinstance(payload.get("token"), str)
        or not _pid_is_alive(payload.get("pid"))
    ):
        return None
    return payload


def _request_with_info(
    info: Mapping[str, Any],
    *,
    request_id: str,
    method: str,
    params: Mapping[str, Any],
    timeout: float,
) -> dict[str, Any]:
    request = {
        "schema_version": EFFECT_RUNTIME_REQUEST_SCHEMA_VERSION,
        "token": info["token"],
        "request_id": request_id,
        "method": method,
        "params": dict(params),
    }
    encoded = (json.dumps(request, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_REQUEST_BYTES:
        raise EffectRuntimeRejected("TypeScript Effect runtime request is oversized")
    chunks: list[bytes] = []
    size = 0
    with socket.create_connection(
        (str(info["host"]), int(info["port"])), timeout=timeout
    ) as connection:
        connection.settimeout(timeout)
        connection.sendall(encoded)
        while True:
            chunk = connection.recv(64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise RuntimeError("TypeScript Effect runtime response is oversized")
            if b"\n" in chunk:
                break
    try:
        response = json.loads(b"".join(chunks).split(b"\n", 1)[0])
    except (json.JSONDecodeError, IndexError):
        raise RuntimeError(
            "TypeScript Effect runtime returned malformed JSON"
        ) from None
    if (
        not isinstance(response, dict)
        or response.get("schema_version") != EFFECT_RUNTIME_RESPONSE_SCHEMA_VERSION
        or response.get("request_id") != request_id
    ):
        raise RuntimeError("TypeScript Effect runtime response shape mismatch")
    if response.get("ok") is not True:
        error = response.get("error")
        message = error.get("message") if isinstance(error, Mapping) else None
        raise EffectRuntimeRejected(
            str(message or "TypeScript Effect runtime request failed")
        )
    return response


def _start_runtime(*, fingerprint: str, info_path: Path) -> dict[str, Any]:
    runtime_dir = info_path.parent
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        runtime_dir.chmod(0o700)
    except OSError:
        pass
    lock = runtime_dir / f"start-{fingerprint[:16]}.lock"
    deadline = time.monotonic() + 5.0
    acquired = False
    while time.monotonic() < deadline:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
                lock_file.write(f"{os.getpid()}\n")
                lock_file.flush()
                os.fsync(lock_file.fileno())
            acquired = True
            break
        except FileExistsError:
            existing = _read_info(info_path, fingerprint=fingerprint)
            if existing is not None:
                return existing
            holder_pid = _start_lock_holder_pid(lock)
            if holder_pid is not None and not _pid_is_alive(holder_pid):
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            try:
                if time.time() - lock.stat().st_mtime > 10:
                    lock.unlink(missing_ok=True)
            except OSError:
                pass
            time.sleep(0.025)
    if not acquired:
        raise EffectRuntimeStartupError(
            "TypeScript Effect runtime startup lock timed out",
            diagnostic_code="startup_lock_timeout",
        )
    try:
        existing = _read_info(info_path, fingerprint=fingerprint)
        if existing is not None:
            return existing
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        environment["LOOPX_EFFECT_RUNTIME_TOKEN"] = token
        try:
            process = subprocess.Popen(
                [
                    _node_executable(),
                    "--no-warnings",
                    "--experimental-strip-types",
                    str(_runtime_server_path()),
                    "--info",
                    str(info_path),
                    "--fingerprint",
                    fingerprint,
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
                close_fds=True,
            )
        except OSError as exc:
            raise EffectRuntimeStartupError(
                "TypeScript Effect runtime process could not be launched",
                diagnostic_code="runtime_launch_failed",
            ) from exc
        while time.monotonic() < deadline:
            info = _read_info(info_path, fingerprint=fingerprint)
            if info is not None:
                return info
            exit_code = process.poll()
            if exit_code is not None:
                raise EffectRuntimeStartupError(
                    "TypeScript Effect runtime exited before becoming ready "
                    f"(exit_code={exit_code})",
                    diagnostic_code="runtime_exited_before_ready",
                )
            time.sleep(0.025)
        if process.poll() is None:
            process.terminate()
        raise EffectRuntimeStartupError(
            "TypeScript Effect runtime did not become ready before the startup deadline",
            diagnostic_code="runtime_startup_timeout",
        )
    finally:
        lock.unlink(missing_ok=True)


def effect_runtime_request(
    method: str,
    params: Mapping[str, Any],
    *,
    timeout: float = 5.0,
    retry_safe: bool = True,
) -> dict[str, Any]:
    """Call the managed TS runtime, retrying only idempotent typed effects."""

    fingerprint = _runtime_fingerprint()
    info_path = _runtime_info_path(fingerprint)
    request_id = str(uuid.uuid4())
    last_error: OSError | RuntimeError | None = None
    for attempt in range(2 if retry_safe else 1):
        info = _read_info(info_path, fingerprint=fingerprint)
        if info is None:
            info = _start_runtime(fingerprint=fingerprint, info_path=info_path)
        try:
            return _request_with_info(
                info,
                request_id=request_id,
                method=method,
                params=params,
                timeout=timeout,
            )
        except EffectRuntimeRejected:
            raise
        except (OSError, RuntimeError) as exc:
            last_error = exc
            if attempt == 0 and retry_safe:
                info_path.unlink(missing_ok=True)
                continue
            break
    raise RuntimeError("TypeScript Effect runtime request failed") from last_error


def effect_runtime_result(
    method: str,
    params: Mapping[str, Any],
    *,
    timeout: float = 5.0,
    retry_safe: bool = True,
) -> Any:
    return effect_runtime_request(
        method,
        params,
        timeout=timeout,
        retry_safe=retry_safe,
    ).get("result")


def collect_effect_runtime_readiness(*, deep: bool = False) -> dict[str, object]:
    """Report whether the managed TS Effect runtime can serve control-plane work."""

    status, _executable, version = _probe_node()
    ready = status == "ready"
    runtime_state = "unavailable"
    runtime_diagnostic_code: str | None = None
    if ready:
        try:
            fingerprint = _runtime_fingerprint()
            runtime_state = (
                "running"
                if _read_info(
                    _runtime_info_path(fingerprint),
                    fingerprint=fingerprint,
                )
                is not None
                else "stopped"
            )
        except OSError:
            ready = False
            status = "package_invalid"
            runtime_diagnostic_code = "packaged_runtime_source_unreadable"
    runtime_lifecycle: dict[str, object] = {
        "schema_version": "loopx_effect_runtime_lifecycle_v0",
        "management": "on_demand_managed",
        "state": runtime_state,
        "manual_start_required": False,
        "restart_policy": "automatic_on_next_control_plane_request",
        "idle_shutdown": True,
        "diagnostic_code": runtime_diagnostic_code,
    }
    result: dict[str, object] = {
        "schema_version": EFFECT_RUNTIME_READINESS_SCHEMA_VERSION,
        "ready": ready,
        "status": status,
        "required_for": ["control_plane"],
        "default_cli_blocking": True,
        "minimum_node_version": MINIMUM_NODE_VERSION_TEXT,
        "detected_node_version": version,
        "semantic_probe": "not_requested" if not deep else "not_run",
        "runtime_lifecycle": runtime_lifecycle,
        "recommended_action": (
            None
            if ready
            else (
                f"Install Node.js {MINIMUM_NODE_VERSION_TEXT} or newer, then "
                "rerun `loopx doctor --deep`."
                if status in {"missing", "unsupported"}
                else "Repair Node.js on PATH, then rerun `loopx doctor --deep`."
            )
        ),
    }
    if not ready or not deep:
        return result
    try:
        ping = effect_runtime_result("runtime.ping", {})
        identity = effect_runtime_result(
            "settlement.identity",
            {
                "goal_id": "doctor-probe",
                "agent_id": "doctor-probe",
                "todo_id": "doctor-probe",
                "turn_instance_id": "doctor-probe",
            },
        )
    except RuntimeError as exc:
        diagnostic_code = getattr(exc, "diagnostic_code", "semantic_probe_failed")
        return {
            **result,
            "ready": False,
            "status": "probe_failed",
            "semantic_probe": "failed",
            "runtime_lifecycle": {
                **runtime_lifecycle,
                "state": "unavailable",
                "diagnostic_code": diagnostic_code,
            },
            "recommended_action": (
                "Run `loopx doctor --deep` again after any concurrent startup "
                "finishes. If the same diagnostic code remains, reinstall LoopX "
                "and verify Node.js before retrying."
            ),
        }
    if (
        not isinstance(ping, Mapping)
        or ping.get("ready") is not True
        or not isinstance(identity, Mapping)
        or identity.get("effect_id")
        != "doctor-probe:doctor-probe:doctor-probe:doctor-probe"
    ):
        return {
            **result,
            "ready": False,
            "status": "probe_failed",
            "semantic_probe": "failed",
            "runtime_lifecycle": {
                **runtime_lifecycle,
                "state": "unavailable",
                "diagnostic_code": "semantic_probe_shape_mismatch",
            },
            "recommended_action": (
                "Reinstall LoopX and verify the packaged TypeScript runtime with "
                "`loopx doctor --deep`."
            ),
        }
    return {
        **result,
        "semantic_probe": "passed",
        "runtime_lifecycle": {
            **runtime_lifecycle,
            "state": "running",
            "diagnostic_code": None,
        },
    }

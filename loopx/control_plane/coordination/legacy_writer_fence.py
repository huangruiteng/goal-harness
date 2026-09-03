"""Cheap Python entry guard for the TypeScript-owned coordination fence.

Legacy Todo writes still happen in Python during Stage 2C.  The durable fence
itself and its validation semantics remain owned by the TypeScript control
plane; this module only avoids starting that runtime while no fence exists and
delegates every present-fence decision to the canonical handler.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
from typing import Any, Iterator

from ..effect_runtime import effect_runtime_result
from ...file_lock import exclusive_file_lock
from ...history import load_registry
from ...paths import resolve_runtime_root


LEGACY_COORDINATION_WRITE_CHECK_REQUEST_SCHEMA = (
    "loopx_legacy_coordination_write_check_request_v0"
)
LEGACY_COORDINATION_WRITE_CHECK_METHOD = (
    "coordination.local_authority.legacy_write_check"
)


class LegacyCoordinationWriterFenced(RuntimeError):
    """Raised when a legacy writer is no longer an authority."""

    def __init__(self, message: str, *, code: str, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


def legacy_coordination_writer_fence_path(
    *, runtime_root: Path, goal_id: str
) -> Path:
    digest = hashlib.sha256(goal_id.encode("utf-8")).hexdigest()[:16]
    return (
        runtime_root
        / "authority-transition"
        / "file-v0"
        / f"legacy-writer-fence-{digest}.json"
    )


def legacy_coordination_todo_lock_path(*, runtime_root: Path, goal_id: str) -> Path:
    digest = hashlib.sha256(goal_id.encode("utf-8")).hexdigest()[:16]
    return (
        runtime_root
        / "authority-transition"
        / "file-v0"
        / f"legacy-todo-writer-{digest}"
    )


def require_legacy_coordination_write_allowed(
    *, runtime_root: Path, goal_id: str
) -> None:
    """Allow the default path cheaply; delegate a present fence fail-closed.

    A future promotion transaction must acquire the legacy writer's existing
    mutation lock before engaging the fence.  Calling this function while that
    lock is held then closes the check/write race without introducing a second
    Python authority for fence contents.
    """

    fence_path = legacy_coordination_writer_fence_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    try:
        fence_path.stat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise LegacyCoordinationWriterFenced(
            "legacy coordination writer fence cannot be inspected",
            code="legacy_writer_fence_read_failed",
            payload={"authority_mode": "unknown_fail_closed"},
        ) from exc

    result = effect_runtime_result(
        LEGACY_COORDINATION_WRITE_CHECK_METHOD,
        {
            "schema_version": LEGACY_COORDINATION_WRITE_CHECK_REQUEST_SCHEMA,
            "runtime_root": str(runtime_root.expanduser().resolve(strict=False)),
            "goal_id": goal_id,
        },
    )
    if not isinstance(result, dict):
        raise LegacyCoordinationWriterFenced(
            "legacy coordination writer fence returned an invalid result",
            code="legacy_writer_fence_invalid_result",
            payload={"authority_mode": "unknown_fail_closed"},
        )
    if (
        result.get("status") == "allowed"
        and result.get("authority_mode") == "legacy_canonical"
    ):
        return

    code = str(result.get("reason_code") or "legacy_writer_fence_check_failed")
    message = (
        "legacy coordination writer is fenced; use the canonical file authority"
        if result.get("status") == "blocked"
        else str(result.get("reason") or "legacy coordination writer fence check failed")
    )
    raise LegacyCoordinationWriterFenced(message, code=code, payload=result)


@contextmanager
def legacy_todo_write_transaction(
    registry_path: Path,
    goal_id: str,
    state_file: Path,
    agent_id: str | None,
    operation: str,
    dry_run: bool,
    *,
    runtime_root: Path | None = None,
) -> Iterator[None]:
    """Serialize promotion with one complete legacy Todo mutation.

    ``runtime_root`` is the effective runtime root of the CLI call (the
    ``--runtime-root`` override when given) so the mutex and the fence check
    share the same root as promotion and the observation hooks.  Callers that
    omit it keep the registry-derived root.
    """

    resolved_runtime_root = runtime_root or resolve_runtime_root(
        load_registry(registry_path),
        None,
        registry_path=registry_path,
    )
    with exclusive_file_lock(
        legacy_coordination_todo_lock_path(
            runtime_root=resolved_runtime_root,
            goal_id=goal_id,
        ),
        agent_id=agent_id,
        operation="legacy_coordination_todo_write",
    ), exclusive_file_lock(
        state_file,
        agent_id=agent_id,
        operation=operation,
    ):
        if not dry_run:
            require_legacy_coordination_write_allowed(
                runtime_root=resolved_runtime_root,
                goal_id=goal_id,
            )
        yield

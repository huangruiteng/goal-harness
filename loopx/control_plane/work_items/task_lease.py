from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ...agent_registry import (
    registered_agent_ids_from_registry,
    require_registered_agent_id,
)
from ...file_lock import exclusive_file_lock
from ...history import load_registry
from ...paths import resolve_runtime_root
from ..runtime.time import now_utc as runtime_now_utc
from ..runtime.time import parse_timestamp, utc_isoformat
from ..todos.contract import (
    TODO_TASK_CLASS_USER_GATE,
    normalize_required_write_scopes,
    normalize_todo_claimed_by,
    normalize_todo_excluded_agents,
    normalize_todo_id,
)
from ..todos.handoff_mode import (
    HANDOFF_MODE_HARD_LEASE,
    HANDOFF_MODE_LEGACY,
    HANDOFF_MODE_SOFT_CLAIM,
    HandoffModeError,
    goal_handoff_mode_for_goal,
    resolve_todo_completion_handoff,
)

TASK_LEASE_SCHEMA_VERSION = "task_lease_v0"
DEFAULT_TASK_LEASE_TTL_SECONDS = 45 * 60
MAX_TASK_LEASE_TTL_SECONDS = 24 * 60 * 60
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:@/-]{1,160}$")


class TaskLeaseError(ValueError):
    def __init__(self, message: str, *, code: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


def now_utc() -> datetime:
    return runtime_now_utc()


def isoformat(value: datetime) -> str:
    return utc_isoformat(value)


def normalize_idempotency_key(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate or not IDEMPOTENCY_KEY_PATTERN.match(candidate):
        raise TaskLeaseError(
            "idempotency key must be a public-safe token",
            code="invalid_idempotency_key",
        )
    return candidate


def normalize_owner(value: Any) -> str:
    owner = normalize_todo_claimed_by(value)
    if not owner:
        raise TaskLeaseError("owner must be a public-safe agent id", code="invalid_owner")
    return owner


def normalize_ttl_seconds(value: int | None) -> int:
    ttl = DEFAULT_TASK_LEASE_TTL_SECONDS if value is None else int(value)
    if ttl <= 0 or ttl > MAX_TASK_LEASE_TTL_SECONDS:
        raise TaskLeaseError(
            f"ttl seconds must be between 1 and {MAX_TASK_LEASE_TTL_SECONDS}",
            code="invalid_ttl",
        )
    return ttl


def normalize_goal_id(value: Any) -> str:
    goal_id = str(value or "").strip()
    if not goal_id or goal_id in {".", ".."} or "/" in goal_id or "\\" in goal_id:
        raise TaskLeaseError("goal id must be a single path segment", code="invalid_goal_id")
    if Path(goal_id).name != goal_id:
        raise TaskLeaseError("goal id must not include path traversal", code="invalid_goal_id")
    return goal_id


def normalize_lease_todo_id(value: Any) -> str:
    todo_id = normalize_todo_id(value)
    if not todo_id:
        raise TaskLeaseError("todo id must use the todo_<token> shape", code="invalid_todo_id")
    return todo_id


def task_lease_dir(*, runtime_root: Path, goal_id: str) -> Path:
    return runtime_root / "goals" / normalize_goal_id(goal_id) / "task-leases"


def task_lease_path(*, runtime_root: Path, goal_id: str, todo_id: str) -> Path:
    return task_lease_dir(runtime_root=runtime_root, goal_id=goal_id) / f"{normalize_lease_todo_id(todo_id)}.json"


def task_lease_lock_path(*, runtime_root: Path, goal_id: str) -> Path:
    return task_lease_dir(runtime_root=runtime_root, goal_id=goal_id) / ".task-leases"


class _VerifiedTaskLeaseFence(dict):
    """Key-verified fence payload with its release hook held out-of-band.

    The hook lives on the instance attribute, never inside the mapping, so
    the payload stays JSON-serializable for every consumer at all times.
    """

    release_hook: Callable[[], None] | None = None


def goal_handoff_mode_for_lease(registry_path: Path, goal_id: str) -> str:
    """Resolve the goal handoff mode for lease verbs.

    An invalid ``handoff_mode`` value is re-typed as a TaskLeaseError. A goal
    or state file that cannot be resolved falls back to legacy: each lease
    verb's own todo-projection checks already own that failure surface.
    """

    try:
        return goal_handoff_mode_for_goal(registry_path=registry_path, goal_id=goal_id)
    except HandoffModeError as exc:
        raise TaskLeaseError(str(exc), code=exc.code, payload=exc.payload) from exc
    except (OSError, ValueError):
        return HANDOFF_MODE_LEGACY


def _require_lease_mutation_allowed_by_handoff_mode(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    action: str,
) -> str:
    handoff_mode = goal_handoff_mode_for_lease(registry_path, goal_id)
    if handoff_mode == HANDOFF_MODE_SOFT_CLAIM:
        raise TaskLeaseError(
            f"goal handoff mode 'soft_claim' forbids task lease {action}; "
            "release and inspect remain available for legacy leftovers",
            code="handoff_mode_forbids_lease",
            payload={
                "goal_id": goal_id,
                "todo_id": todo_id,
                "action": action,
                "handoff_mode": handoff_mode,
            },
        )
    return handoff_mode


def _optional_handoff_mode(registry_path: Path | None, goal_id: str) -> str | None:
    if registry_path is None:
        return None
    try:
        return goal_handoff_mode_for_lease(registry_path, goal_id)
    except (TaskLeaseError, OSError, ValueError):
        return None


@contextmanager
def hold_handoff_lease_holder_gate(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    actor_agent_id: str | None,
) -> Iterator[dict[str, Any]]:
    """Hold the per-goal lease lock while proving the actor owns the lease.

    hard_lease handoff mode only: an ownership mutation (claim, claimed_by
    update, clear) on an existing todo requires the acting agent to hold that
    todo's time-active lease. Identity is compared with
    normalize_todo_claimed_by on both sides. Callers must already hold the
    markdown state lock; this guard then takes the per-goal lease lock, the
    same markdown-lock-then-lease-lock order used by the completion fence,
    and the caller keeps it held until the markdown write commits.
    """

    normalized_goal_id = normalize_goal_id(goal_id)
    normalized_todo_id = normalize_lease_todo_id(todo_id)
    actor = normalize_todo_claimed_by(actor_agent_id)
    runtime_root = runtime_root_from_registry(registry_path, None)
    lease_path = task_lease_path(
        runtime_root=runtime_root,
        goal_id=normalized_goal_id,
        todo_id=normalized_todo_id,
    )
    base_payload: dict[str, Any] = {
        "goal_id": normalized_goal_id,
        "todo_id": normalized_todo_id,
        "handoff_mode": HANDOFF_MODE_HARD_LEASE,
        "lease_path": str(lease_path),
    }
    if not actor:
        raise TaskLeaseError(
            "hard_lease handoff mode requires an attributed actor for "
            "ownership changes; provide --agent-id",
            code="handoff_mode_requires_lease",
            payload={**base_payload, "reason": "missing_actor"},
        )
    lock_target = task_lease_lock_path(
        runtime_root=runtime_root,
        goal_id=normalized_goal_id,
    )
    with exclusive_file_lock(
        lock_target,
        agent_id=actor,
        operation="handoff_lease_holder_gate",
    ):
        lease = read_lease(lease_path)
        if not lease_is_active(lease):
            raise TaskLeaseError(
                "hard_lease handoff mode requires a time-active task lease "
                "before ownership of an existing todo can change; acquire one "
                "with `loopx task-lease acquire`",
                code="handoff_mode_requires_lease",
                payload={**base_payload, "reason": "no_active_lease"},
            )
        assert lease is not None
        owner = normalize_todo_claimed_by(lease.get("owner"))
        if owner != actor:
            raise TaskLeaseError(
                f"hard_lease handoff mode: actor {actor!r} does not own the "
                f"time-active task lease held by {owner!r}",
                code="handoff_mode_requires_lease",
                payload={
                    **base_payload,
                    "reason": "lease_owner_mismatch",
                    "actor_agent_id": actor,
                    "lease_owner": owner,
                    "lease_version": lease.get("version"),
                    "lease_epoch": lease_epoch(lease),
                    "expires_at": lease.get("expires_at"),
                },
            )
        yield {
            "schema_version": TASK_LEASE_SCHEMA_VERSION,
            "checked": True,
            "active": True,
            "owner": owner,
            "version": lease.get("version"),
            "lease_epoch": lease_epoch(lease),
        }


@contextmanager
def hold_task_lease_mutation_fence(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    todo: dict[str, Any],
    actor_agent_id: str | None,
    idempotency_key: str | None,
    expected_version: int | None = None,
    require_active_when_key_supplied: bool = True,
    handoff: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """Hold the per-goal lease lock while one todo lifecycle write commits.

    Task leases are optional in legacy and soft_claim handoff modes. Once an
    effective lease exists, however, the lifecycle writer must prove that it
    is the execution instance that acquired the lease. The idempotency key is
    the execution-instance fence; agent ids alone are insufficient because
    multiple host processes may share one peer identity.

    ``handoff`` carries the resolved goal handoff mode plus the delegated
    authority door marker. In hard_lease mode (without the door) the fence is
    mandatory: no effective lease is a typed error instead of a silent
    ``{"required": False}``, and a time-active lease whose owner constraint is
    no longer effective (the legacy self-disarm state) fails loudly instead of
    letting a keyless completion through. For a user-role ``user_gate``
    completion that supplies no explicit lease credentials, the fence mints
    the key itself under the same per-goal lease lock; an existing
    time-active lease is never displaced.
    """

    normalized_goal_id = normalize_goal_id(goal_id)
    normalized_todo_id = normalize_lease_todo_id(todo_id)
    requested_key = (
        normalize_idempotency_key(idempotency_key)
        if idempotency_key is not None
        else None
    )
    runtime_root = runtime_root_from_registry(registry_path, None)
    lease_path = task_lease_path(
        runtime_root=runtime_root,
        goal_id=normalized_goal_id,
        todo_id=normalized_todo_id,
    )
    lock_target = task_lease_lock_path(
        runtime_root=runtime_root,
        goal_id=normalized_goal_id,
    )
    handoff = handoff or {}
    handoff_mode = str(handoff.get("handoff_mode") or HANDOFF_MODE_LEGACY)
    handoff_gate_overridden = handoff.get("handoff_gate_overridden") is True
    auto_acquire_lease = (
        handoff_mode == HANDOFF_MODE_HARD_LEASE
        and not handoff_gate_overridden
        and not require_active_when_key_supplied
        and str(todo.get("role") or "") == "user"
        and str(todo.get("task_class") or "") == TODO_TASK_CLASS_USER_GATE
    )
    auto_acquired = False
    with exclusive_file_lock(
        lock_target,
        agent_id=actor_agent_id,
        operation="task_lease_mutation_fence",
    ):
        lease = read_lease(lease_path)
        time_active = lease_is_active(lease)
        active = time_active
        constraint: dict[str, Any] | None = None
        if active and lease:
            constraint = task_lease_owner_constraint(
                todo,
                owner=lease.get("owner"),
                registered_agents=registered_agent_ids_from_registry(
                    registry_path,
                    normalized_goal_id,
                ),
            )
            active = constraint.get("effective") is True

        if (
            auto_acquire_lease
            and not active
            and not (time_active and lease)
        ):
            # Mint the completion key under the same per-goal lease lock. A
            # time-active lease is never displaced: if one exists but its
            # owner constraint is no longer effective, the hard branch below
            # keeps the loud divergence error.
            normalized_actor = normalize_todo_claimed_by(actor_agent_id)
            if not normalized_actor:
                raise TaskLeaseError(
                    "hard_lease handoff mode auto-acquire requires an "
                    "attributed actor; provide --agent-id",
                    code="handoff_mode_requires_lease",
                    payload={
                        "goal_id": normalized_goal_id,
                        "todo_id": normalized_todo_id,
                        "handoff_mode": handoff_mode,
                        "lease_path": str(lease_path),
                        "reason": "missing_actor",
                    },
                )
            constraint = task_lease_owner_constraint(
                todo,
                owner=normalized_actor,
                registered_agents=registered_agent_ids_from_registry(
                    registry_path,
                    normalized_goal_id,
                ),
            )
            if constraint.get("effective") is not True:
                raise TaskLeaseError(
                    "hard_lease handoff mode auto-acquire rejected for "
                    "the acting agent",
                    code="handoff_mode_requires_lease",
                    payload={
                        "goal_id": normalized_goal_id,
                        "todo_id": normalized_todo_id,
                        "handoff_mode": handoff_mode,
                        "lease_path": str(lease_path),
                        "reason": str(
                            constraint.get("reason") or "owner_not_allowed"
                        ),
                        "constraint": constraint,
                    },
                )
            at = now_utc()
            auto_key = requested_key or f"auto-{normalized_todo_id}"
            updated_at = isoformat(at)
            expires_at = isoformat(
                at + timedelta(seconds=DEFAULT_TASK_LEASE_TTL_SECONDS)
            )
            lease = build_lease(
                goal_id=normalized_goal_id,
                todo_id=normalized_todo_id,
                owner=normalized_actor,
                idempotency_key=auto_key,
                write_scopes=[],
                acquire_ttl_seconds=DEFAULT_TASK_LEASE_TTL_SECONDS,
                version=int((lease or {}).get("version") or 0) + 1,
                lease_epoch=lease_epoch(lease) + 1,
                acquired_at=updated_at,
                updated_at=updated_at,
                expires_at=expires_at,
            )
            write_lease(lease_path, lease)
            requested_key = auto_key
            auto_acquired = True
            active = True
            time_active = True

        if not active:
            if handoff_mode == HANDOFF_MODE_HARD_LEASE and not handoff_gate_overridden:
                if time_active and lease:
                    raise TaskLeaseError(
                        "hard_lease handoff mode found a time-active lease "
                        "diverged from the todo projection; refusing keyless "
                        "completion. Repair ownership (release or transfer the "
                        "lease, or restore claimed_by) before completing.",
                        code="handoff_mode_lease_claim_divergence",
                        payload={
                            "goal_id": normalized_goal_id,
                            "todo_id": normalized_todo_id,
                            "handoff_mode": handoff_mode,
                            "lease_owner": lease.get("owner"),
                            "lease_version": lease.get("version"),
                            "lease_epoch": lease_epoch(lease),
                            "constraint": constraint,
                            "lease_path": str(lease_path),
                        },
                    )
                raise TaskLeaseError(
                    "hard_lease handoff mode requires an effective task lease "
                    "to complete this todo; acquire one with "
                    "`loopx task-lease acquire`",
                    code="handoff_mode_requires_lease",
                    payload={
                        "goal_id": normalized_goal_id,
                        "todo_id": normalized_todo_id,
                        "handoff_mode": handoff_mode,
                        "lease_path": str(lease_path),
                    },
                )
            if (
                require_active_when_key_supplied
                and (requested_key is not None or expected_version is not None)
            ):
                raise TaskLeaseError(
                    "task lease fence was supplied but no effective lease is active",
                    code="lease_not_active",
                    payload={
                        "goal_id": normalized_goal_id,
                        "todo_id": normalized_todo_id,
                        "lease_path": str(lease_path),
                    },
                )
            yield {
                "schema_version": TASK_LEASE_SCHEMA_VERSION,
                "required": False,
                "active": False,
            }
            return

        assert lease is not None
        if requested_key is None:
            raise TaskLeaseError(
                "todo has an active task lease; lifecycle mutation requires its idempotency key",
                code="lease_fence_required",
                payload={
                    "goal_id": normalized_goal_id,
                    "todo_id": normalized_todo_id,
                    "lease_owner": lease.get("owner"),
                    "lease_version": lease.get("version"),
                    "lease_epoch": lease_epoch(lease),
                    "lease_path": str(lease_path),
                },
            )
        normalized_actor = normalize_todo_claimed_by(actor_agent_id)
        if (
            lease.get("owner") != normalized_actor
            or lease.get("idempotency_key") != requested_key
        ):
            raise TaskLeaseError(
                "task lease owner or execution-instance key mismatch",
                code="lease_cas_mismatch",
                payload={
                    "goal_id": normalized_goal_id,
                    "todo_id": normalized_todo_id,
                    "lease_owner": lease.get("owner"),
                    "lease_version": lease.get("version"),
                    "lease_epoch": lease_epoch(lease),
                    "actor_agent_id": normalized_actor,
                    "lease_path": str(lease_path),
                },
            )
        if not auto_acquired:
            expected_version = require_expected_version(
                expected_version,
                action="lifecycle writeback",
            )
        assert_expected_version(lease, expected_version)
        fence_payload = {
            "schema_version": TASK_LEASE_SCHEMA_VERSION,
            "required": True,
            "active": True,
            "owner": normalized_actor,
            "version": lease.get("version"),
            "lease_epoch": lease_epoch(lease),
            "execution_instance_verified": True,
        }
        if auto_acquired:
            fence_payload["auto_acquired"] = True
        fence = _VerifiedTaskLeaseFence(fence_payload)
        verified_lease = dict(lease)
        fence.release_hook = lambda: persist_released_lease(
            lease_path,
            verified_lease,
        )
        yield fence


def enter_terminal_todo_lease_fence(
    stack: ExitStack,
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    todo: dict[str, Any],
    actor_agent_id: str | None,
    state_text: str,
    mutation_authority: dict[str, Any],
    idempotency_key: str | None = None,
    expected_version: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve the goal handoff and hold the lease fence for one terminal write.

    Every transition that moves an existing todo to ``done`` (complete and
    supersede alike) is a completion for the lease contract: it must cross
    the same per-goal lease fence with the same typed outcomes, so a leased
    todo cannot be retired keylessly through a sibling verb. The caller keeps
    the state-file lock and ``stack`` open across its write and then calls
    ``release_verified_task_lease_fence`` with the commit outcome.
    """

    handoff = resolve_todo_completion_handoff(
        state_text=state_text,
        mutation_authority=mutation_authority,
    )
    fence = stack.enter_context(
        hold_task_lease_mutation_fence(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            todo=todo,
            actor_agent_id=actor_agent_id,
            idempotency_key=idempotency_key,
            expected_version=expected_version,
            require_active_when_key_supplied=(
                idempotency_key is not None or expected_version is not None
            ),
            handoff=handoff,
        )
    )
    return handoff, fence


def release_verified_task_lease_fence(
    fence: dict[str, Any] | None,
    *,
    committed: bool,
) -> None:
    """Release the lease behind a key-verified fence once its write committed.

    Must run while the hold_task_lease_mutation_fence context is still open so
    the per-goal lease lock it acquired is still held; the lease therefore
    cannot have been renewed, transferred, or re-acquired since the fence
    verified the owner, idempotency key, and version. The release reuses the
    CLI release semantics and persists the terminal record that fences the
    next lease generation.

    The private release hook rides on the fence object's attribute, not inside
    the payload mapping, and is disarmed here on every call. Only a committed,
    key-verified fence releases the lease; non-verified fences carry no hook
    and are never touched. A release failure never unwinds the committed
    lifecycle write: it is surfaced additively as fence["released"] = False
    and the active record is left for an explicit `loopx task-lease release`
    or TTL expiry.
    """

    hook = getattr(fence, "release_hook", None)
    if hook is None or not isinstance(fence, dict):
        return
    fence.release_hook = None  # type: ignore[attr-defined]
    if not committed or fence.get("execution_instance_verified") is not True:
        return
    try:
        hook()
    except OSError:
        fence["released"] = False
        return
    fence["released"] = True


def runtime_root_from_registry(registry_path: Path, runtime_root_override: str | None) -> Path:
    registry = load_registry(registry_path)
    return resolve_runtime_root(registry, runtime_root_override)


def task_lease_todo_projection(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
) -> dict[str, Any] | None:
    """Resolve the canonical Markdown/event todo projection for lease guards."""

    from ...todos import list_goal_todos

    try:
        payload = list_goal_todos(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
        )
    except (OSError, ValueError) as exc:
        raise TaskLeaseError(
            "cannot resolve todo projection for task lease",
            code="todo_projection_unavailable",
            payload={"goal_id": goal_id, "todo_id": todo_id, "error": str(exc)},
        ) from exc
    todo = payload.get("todo")
    return dict(todo) if isinstance(todo, dict) else None


def task_lease_owner_constraint(
    todo: dict[str, Any] | None,
    *,
    owner: Any,
    registered_agents: list[str] | None = None,
) -> dict[str, Any]:
    if todo is None:
        return {"effective": False, "reason": "todo_not_found"}
    todo_status = str(todo.get("status") or "").strip().lower()
    if todo_status != "open":
        return {
            "effective": False,
            "reason": "todo_not_open",
            "todo_status": todo_status or "unknown",
        }
    normalized_owner = normalize_todo_claimed_by(owner)
    if not normalized_owner:
        return {"effective": False, "reason": "invalid_owner"}
    if registered_agents is not None and normalized_owner not in registered_agents:
        return {
            "effective": False,
            "reason": "owner_not_registered",
            "registered_agents": registered_agents,
        }
    excluded_agents = normalize_todo_excluded_agents(todo.get("excluded_agents"))
    if normalized_owner in excluded_agents:
        return {
            "effective": False,
            "reason": "owner_excluded_from_todo",
            "excluded_agents": excluded_agents,
        }
    claimed_by = normalize_todo_claimed_by(todo.get("claimed_by"))
    if claimed_by and claimed_by != normalized_owner:
        return {
            "effective": False,
            "reason": "owner_conflicts_with_claim",
            "claimed_by": claimed_by,
        }
    return {"effective": True}


def require_registered_task_lease_owner(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
) -> str:
    try:
        return require_registered_agent_id(
            registry_path=registry_path,
            goal_id=goal_id,
            agent_id=owner,
            field="task lease owner",
        )
    except ValueError as exc:
        raise TaskLeaseError(
            str(exc),
            code="owner_not_registered",
            payload={"goal_id": goal_id, "todo_id": todo_id, "owner": owner},
        ) from exc


def require_task_lease_owner_allowed(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
) -> dict[str, Any]:
    owner = require_registered_task_lease_owner(
        registry_path=registry_path,
        goal_id=goal_id,
        todo_id=todo_id,
        owner=owner,
    )
    todo = task_lease_todo_projection(
        registry_path=registry_path,
        goal_id=goal_id,
        todo_id=todo_id,
    )
    constraint = task_lease_owner_constraint(
        todo,
        owner=owner,
        registered_agents=registered_agent_ids_from_registry(registry_path, goal_id),
    )
    if constraint.get("effective") is not True:
        reason = str(constraint.get("reason") or "owner_not_allowed")
        if reason == "todo_not_found":
            message = "todo is missing from the canonical projection"
        elif reason == "todo_not_open":
            message = (
                f"task lease requires an open todo; "
                f"{todo_id!r} is {constraint.get('todo_status')!r}"
            )
        elif reason == "owner_excluded_from_todo":
            message = f"task lease owner {owner!r} is excluded from todo {todo_id!r}"
        elif reason == "owner_conflicts_with_claim":
            message = (
                f"task lease owner {owner!r} conflicts with todo claim "
                f"{constraint.get('claimed_by')!r}"
            )
        elif reason == "owner_not_registered":
            message = f"task lease owner {owner!r} is not registered for goal {goal_id!r}"
        else:
            message = f"task lease owner {owner!r} is not eligible for todo {todo_id!r}"
        raise TaskLeaseError(
            message,
            code=reason,
            payload={
                "goal_id": goal_id,
                "todo_id": todo_id,
                "owner": owner,
                **constraint,
            },
        )
    return todo


def read_lease(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskLeaseError(
            f"lease file is not valid JSON: {path}",
            code="corrupt_lease",
            payload={"lease_path": str(path), "error": str(exc)},
        ) from exc
    if not isinstance(payload, dict):
        raise TaskLeaseError(
            f"lease file must contain an object: {path}",
            code="corrupt_lease",
            payload={"lease_path": str(path)},
        )
    return payload


def write_lease(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{id(payload)}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def lease_epoch(lease: dict[str, Any] | None) -> int:
    """Return the authority-owned generation for one todo's lease lineage.

    Records written before ``lease_epoch`` shipped describe the one active
    generation visible at migration time, so they migrate as epoch 1. Missing
    records are the pre-history state at epoch 0.
    """

    if not lease:
        return 0
    raw_epoch = lease.get("lease_epoch")
    if raw_epoch is None:
        return 1
    try:
        epoch = int(raw_epoch)
    except (TypeError, ValueError) as exc:
        raise TaskLeaseError(
            "lease epoch must be a positive integer",
            code="corrupt_lease",
            payload={"lease_epoch": raw_epoch},
        ) from exc
    if epoch <= 0:
        raise TaskLeaseError(
            "lease epoch must be a positive integer",
            code="corrupt_lease",
            payload={"lease_epoch": raw_epoch},
        )
    return epoch


def released_lease_payload(
    lease: dict[str, Any],
    *,
    at: datetime,
) -> dict[str, Any]:
    released = dict(lease)
    released["lease_epoch"] = lease_epoch(lease)
    released["status"] = "released"
    released["released_at"] = isoformat(at)
    released["updated_at"] = isoformat(at)
    return released


def persist_released_lease(path: Path, lease: dict[str, Any]) -> None:
    """Atomically retain the terminal record that fences the next generation."""

    write_lease(path, released_lease_payload(lease, at=now_utc()))


def lease_expires_at(lease: dict[str, Any] | None) -> datetime | None:
    return parse_timestamp((lease or {}).get("expires_at"))


def lease_is_active(lease: dict[str, Any] | None, *, at: datetime | None = None) -> bool:
    if not lease or lease.get("schema_version") != TASK_LEASE_SCHEMA_VERSION:
        return False
    if lease.get("status") != "active":
        return False
    expires_at = lease_expires_at(lease)
    return bool(expires_at and expires_at > (at or now_utc()))


def scope_root(scope: str) -> str:
    value = scope.strip()
    if value in {"*", "**", "./"}:
        return ""
    wildcard_indexes = [index for index in (value.find("*"), value.find("?"), value.find("[")) if index >= 0]
    if wildcard_indexes:
        value = value[: min(wildcard_indexes)]
    if "/" in value:
        value = value[: value.rfind("/") + 1]
    return value.rstrip("/")


def _scope_has_glob(scope: str) -> bool:
    return any(token in scope for token in ("*", "?", "["))


def _scope_literal_prefix(scope: str) -> str:
    indexes = [scope.find(token) for token in ("*", "?", "[") if scope.find(token) >= 0]
    return scope[: min(indexes)] if indexes else scope


def _scope_pair_overlaps(left: str, right: str) -> bool:
    if left == right:
        return True
    if left in {"*", "**", "./"} or right in {"*", "**", "./"}:
        return True

    left_has_glob = _scope_has_glob(left)
    right_has_glob = _scope_has_glob(right)
    if left_has_glob and not right_has_glob:
        prefix = _scope_literal_prefix(left)
        return fnmatch.fnmatchcase(right, left) or (
            prefix.endswith("/") and right.rstrip("/") == prefix.rstrip("/")
        )
    if right_has_glob and not left_has_glob:
        prefix = _scope_literal_prefix(right)
        return fnmatch.fnmatchcase(left, right) or (
            prefix.endswith("/") and left.rstrip("/") == prefix.rstrip("/")
        )
    if left_has_glob and right_has_glob:
        left_prefix = _scope_literal_prefix(left)
        right_prefix = _scope_literal_prefix(right)
        return bool(
            not left_prefix
            or not right_prefix
            or left_prefix.startswith(right_prefix)
            or right_prefix.startswith(left_prefix)
        )

    left_root = left.rstrip("/")
    right_root = right.rstrip("/")
    return bool(
        (left.endswith("/") and right.startswith(left_root + "/"))
        or (right.endswith("/") and left.startswith(right_root + "/"))
    )


def write_scopes_overlap(left: list[str], right: list[str]) -> bool:
    left_scopes = normalize_required_write_scopes(left)
    right_scopes = normalize_required_write_scopes(right)
    if not left_scopes or not right_scopes:
        return False
    for left_scope in left_scopes:
        for right_scope in right_scopes:
            if _scope_pair_overlaps(left_scope, right_scope):
                return True
    return False


def active_conflicts(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    write_scopes: list[str],
    at: datetime,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    registered_agents = registered_agent_ids_from_registry(registry_path, goal_id)
    lease_dir = task_lease_dir(runtime_root=runtime_root, goal_id=goal_id)
    if not lease_dir.exists():
        return conflicts
    for path in sorted(lease_dir.glob("todo_*.json")):
        lease = read_lease(path)
        if not lease_is_active(lease, at=at):
            continue
        lease_todo_id = normalize_lease_todo_id(lease.get("todo_id"))
        if lease_todo_id == todo_id:
            continue
        todo = task_lease_todo_projection(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=lease_todo_id,
        )
        if task_lease_owner_constraint(
            todo,
            owner=lease.get("owner"),
            registered_agents=registered_agents,
        ).get("effective") is not True:
            continue
        if write_scopes_overlap(write_scopes, normalize_required_write_scopes(lease.get("write_scopes"))):
            conflicts.append(
                {
                    "todo_id": lease.get("todo_id"),
                    "owner": lease.get("owner"),
                    "expires_at": lease.get("expires_at"),
                    "version": lease.get("version"),
                    "lease_epoch": lease_epoch(lease),
                    "write_scopes": lease.get("write_scopes") or [],
                    "lease_path": str(path),
                }
            )
    return conflicts


def assert_expected_version(lease: dict[str, Any] | None, expected_version: int | None) -> None:
    if expected_version is None:
        return
    actual = int((lease or {}).get("version") or 0)
    if actual != expected_version:
        raise TaskLeaseError(
            f"lease version mismatch: expected {expected_version}, got {actual}",
            code="version_mismatch",
            payload={"expected_version": expected_version, "actual_version": actual},
        )


def require_expected_version(expected_version: int | None, *, action: str) -> int:
    if expected_version is None:
        raise TaskLeaseError(
            f"task lease {action} requires the current lease version",
            code="version_required",
            payload={"action": action},
        )
    return int(expected_version)


def build_lease(
    *,
    goal_id: str,
    todo_id: str,
    owner: str,
    idempotency_key: str,
    write_scopes: list[str],
    acquire_ttl_seconds: int,
    version: int,
    lease_epoch: int,
    acquired_at: str,
    updated_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": TASK_LEASE_SCHEMA_VERSION,
        "goal_id": goal_id,
        "todo_id": todo_id,
        "owner": owner,
        "idempotency_key": idempotency_key,
        "write_scopes": write_scopes,
        "acquire_ttl_seconds": acquire_ttl_seconds,
        "version": version,
        "lease_epoch": lease_epoch,
        "acquired_at": acquired_at,
        "updated_at": updated_at,
        "expires_at": expires_at,
        "status": "active",
    }


def acquire_task_lease(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
    idempotency_key: str,
    ttl_seconds: int | None = None,
    write_scopes: list[str] | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    goal_id = normalize_goal_id(goal_id)
    todo_id = normalize_lease_todo_id(todo_id)
    owner = normalize_owner(owner)
    idempotency_key = normalize_idempotency_key(idempotency_key)
    ttl = normalize_ttl_seconds(ttl_seconds)
    normalized_write_scopes = normalize_required_write_scopes(write_scopes)
    lease_dir = task_lease_dir(runtime_root=runtime_root, goal_id=goal_id)
    lock_target = task_lease_lock_path(runtime_root=runtime_root, goal_id=goal_id)
    lease_path = task_lease_path(runtime_root=runtime_root, goal_id=goal_id, todo_id=todo_id)
    at = now_utc()
    with exclusive_file_lock(
        lock_target,
        agent_id=owner,
        operation="task_lease_acquire",
    ):
        handoff_mode = _require_lease_mutation_allowed_by_handoff_mode(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            action="acquire",
        )
        todo = require_task_lease_owner_allowed(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            owner=owner,
        )
        existing = read_lease(lease_path)
        assert_expected_version(existing, expected_version)
        existing_is_effective = bool(
            lease_is_active(existing, at=at)
            and task_lease_owner_constraint(
                todo,
                owner=(existing or {}).get("owner"),
                registered_agents=registered_agent_ids_from_registry(registry_path, goal_id),
            ).get("effective")
            is True
        )
        if existing_is_effective:
            if (
                existing.get("owner") == owner
                and existing.get("idempotency_key") == idempotency_key
            ):
                existing_write_scopes = normalize_required_write_scopes(
                    existing.get("write_scopes")
                )
                existing_ttl = existing.get("acquire_ttl_seconds")
                request_matches = set(existing_write_scopes) == set(normalized_write_scopes)
                if existing_ttl is not None:
                    request_matches = request_matches and int(existing_ttl) == ttl
                if not request_matches:
                    raise TaskLeaseError(
                        "idempotency key was reused with different acquire parameters",
                        code="idempotency_key_reuse",
                        payload={
                            "lease": existing,
                            "lease_path": str(lease_path),
                            "requested_write_scopes": normalized_write_scopes,
                            "requested_ttl_seconds": ttl,
                        },
                    )
                return {
                    "ok": True,
                    "schema_version": TASK_LEASE_SCHEMA_VERSION,
                    "action": "acquire",
                    "acquired": False,
                    "idempotent": True,
                    "lease": existing,
                    "lease_path": str(lease_path),
                    "handoff_mode": handoff_mode,
                }
            raise TaskLeaseError(
                "todo already has an active lease",
                code="todo_lease_conflict",
                payload={"lease": existing, "lease_path": str(lease_path)},
            )
        if existing and existing.get("idempotency_key") == idempotency_key:
            raise TaskLeaseError(
                "idempotency key belongs to an expired or released lease generation; "
                "a new execution must use a new key",
                code="idempotency_key_reuse",
                payload={"lease": existing, "lease_path": str(lease_path)},
            )
        conflicts = active_conflicts(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
            todo_id=todo_id,
            write_scopes=normalized_write_scopes,
            at=at,
        )
        if conflicts:
            raise TaskLeaseError(
                "write scope overlaps another active task lease",
                code="write_scope_conflict",
                payload={"conflicts": conflicts},
            )
        updated_at = isoformat(at)
        expires_at = isoformat(at + timedelta(seconds=ttl))
        lease = build_lease(
            goal_id=goal_id,
            todo_id=todo_id,
            owner=owner,
            idempotency_key=idempotency_key,
            write_scopes=normalized_write_scopes,
            acquire_ttl_seconds=ttl,
            version=int((existing or {}).get("version") or 0) + 1,
            lease_epoch=lease_epoch(existing) + 1,
            acquired_at=updated_at,
            updated_at=updated_at,
            expires_at=expires_at,
        )
        lease_dir.mkdir(parents=True, exist_ok=True)
        write_lease(lease_path, lease)
        return {
            "ok": True,
            "schema_version": TASK_LEASE_SCHEMA_VERSION,
            "action": "acquire",
            "acquired": True,
            "idempotent": False,
            "lease": lease,
            "lease_path": str(lease_path),
            "handoff_mode": handoff_mode,
        }


def renew_task_lease(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
    idempotency_key: str,
    ttl_seconds: int | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    goal_id = normalize_goal_id(goal_id)
    todo_id = normalize_lease_todo_id(todo_id)
    owner = normalize_owner(owner)
    idempotency_key = normalize_idempotency_key(idempotency_key)
    ttl = normalize_ttl_seconds(ttl_seconds)
    lock_target = task_lease_lock_path(runtime_root=runtime_root, goal_id=goal_id)
    lease_path = task_lease_path(runtime_root=runtime_root, goal_id=goal_id, todo_id=todo_id)
    at = now_utc()
    with exclusive_file_lock(
        lock_target,
        agent_id=owner,
        operation="task_lease_renew",
    ):
        handoff_mode = _require_lease_mutation_allowed_by_handoff_mode(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            action="renew",
        )
        expected_version = require_expected_version(expected_version, action="renew")
        require_task_lease_owner_allowed(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            owner=owner,
        )
        lease = read_lease(lease_path)
        assert_expected_version(lease, expected_version)
        if not lease_is_active(lease, at=at):
            raise TaskLeaseError("lease is missing or expired", code="lease_not_active")
        if lease.get("owner") != owner or lease.get("idempotency_key") != idempotency_key:
            raise TaskLeaseError("lease owner or idempotency key mismatch", code="lease_cas_mismatch")
        lease = dict(lease)
        lease["version"] = int(lease.get("version") or 0) + 1
        lease["lease_epoch"] = lease_epoch(lease)
        lease["updated_at"] = isoformat(at)
        lease["expires_at"] = isoformat(at + timedelta(seconds=ttl))
        write_lease(lease_path, lease)
        return {
            "ok": True,
            "schema_version": TASK_LEASE_SCHEMA_VERSION,
            "action": "renew",
            "renewed": True,
            "lease": lease,
            "lease_path": str(lease_path),
            "handoff_mode": handoff_mode,
        }


def transfer_task_lease(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
    idempotency_key: str,
    new_owner: str,
    new_idempotency_key: str,
    ttl_seconds: int | None = None,
    expected_version: int | None = None,
) -> dict[str, Any]:
    goal_id = normalize_goal_id(goal_id)
    todo_id = normalize_lease_todo_id(todo_id)
    owner = normalize_owner(owner)
    idempotency_key = normalize_idempotency_key(idempotency_key)
    new_owner = normalize_owner(new_owner)
    new_idempotency_key = normalize_idempotency_key(new_idempotency_key)
    ttl = normalize_ttl_seconds(ttl_seconds)
    lock_target = task_lease_lock_path(runtime_root=runtime_root, goal_id=goal_id)
    lease_path = task_lease_path(runtime_root=runtime_root, goal_id=goal_id, todo_id=todo_id)
    at = now_utc()
    with exclusive_file_lock(
        lock_target,
        agent_id=owner,
        operation="task_lease_transfer",
    ):
        handoff_mode = _require_lease_mutation_allowed_by_handoff_mode(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            action="transfer",
        )
        expected_version = require_expected_version(expected_version, action="transfer")
        require_registered_task_lease_owner(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            owner=owner,
        )
        require_task_lease_owner_allowed(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            owner=new_owner,
        )
        lease = read_lease(lease_path)
        assert_expected_version(lease, expected_version)
        if not lease_is_active(lease, at=at):
            raise TaskLeaseError("lease is missing or expired", code="lease_not_active")
        if lease.get("owner") != owner or lease.get("idempotency_key") != idempotency_key:
            raise TaskLeaseError("lease owner or idempotency key mismatch", code="lease_cas_mismatch")
        if new_idempotency_key == idempotency_key:
            raise TaskLeaseError(
                "lease transfer must mint a new execution idempotency key",
                code="idempotency_key_reuse",
                payload={"lease": lease, "lease_path": str(lease_path)},
            )
        lease = dict(lease)
        lease["owner"] = new_owner
        lease["idempotency_key"] = new_idempotency_key
        lease["version"] = int(lease.get("version") or 0) + 1
        lease["lease_epoch"] = lease_epoch(lease) + 1
        lease["updated_at"] = isoformat(at)
        lease["expires_at"] = isoformat(at + timedelta(seconds=ttl))
        write_lease(lease_path, lease)
        return {
            "ok": True,
            "schema_version": TASK_LEASE_SCHEMA_VERSION,
            "action": "transfer",
            "transferred": True,
            "lease": lease,
            "lease_path": str(lease_path),
            "handoff_mode": handoff_mode,
        }


def release_task_lease(
    *,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
    idempotency_key: str,
    expected_version: int | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    goal_id = normalize_goal_id(goal_id)
    todo_id = normalize_lease_todo_id(todo_id)
    owner = normalize_owner(owner)
    idempotency_key = normalize_idempotency_key(idempotency_key)
    expected_version = require_expected_version(expected_version, action="release")
    # Release stays allowed in every handoff mode (cleanup of legacy
    # leftovers); the mode is reported additively when resolvable.
    handoff_mode = _optional_handoff_mode(registry_path, goal_id)
    handoff_extra = {"handoff_mode": handoff_mode} if handoff_mode else {}
    lock_target = task_lease_lock_path(runtime_root=runtime_root, goal_id=goal_id)
    lease_path = task_lease_path(runtime_root=runtime_root, goal_id=goal_id, todo_id=todo_id)
    at = now_utc()
    with exclusive_file_lock(
        lock_target,
        agent_id=owner,
        operation="task_lease_release",
    ):
        lease = read_lease(lease_path)
        assert_expected_version(lease, expected_version)
        if not lease:
            return {
                "ok": True,
                "schema_version": TASK_LEASE_SCHEMA_VERSION,
                "action": "release",
                "released": False,
                "missing": True,
                "lease_path": str(lease_path),
                **handoff_extra,
            }
        if lease.get("owner") != owner or lease.get("idempotency_key") != idempotency_key:
            raise TaskLeaseError("lease owner or idempotency key mismatch", code="lease_cas_mismatch")
        if lease.get("status") == "released":
            return {
                "ok": True,
                "schema_version": TASK_LEASE_SCHEMA_VERSION,
                "action": "release",
                "released": True,
                "idempotent": True,
                "lease": lease,
                "lease_path": str(lease_path),
                **handoff_extra,
            }
        released_lease = released_lease_payload(lease, at=at)
        write_lease(lease_path, released_lease)
        return {
            "ok": True,
            "schema_version": TASK_LEASE_SCHEMA_VERSION,
            "action": "release",
            "released": True,
            "idempotent": False,
            "lease": released_lease,
            "lease_path": str(lease_path),
            **handoff_extra,
        }


def inspect_task_lease(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
) -> dict[str, Any]:
    goal_id = normalize_goal_id(goal_id)
    todo_id = normalize_lease_todo_id(todo_id)
    lease_path = task_lease_path(runtime_root=runtime_root, goal_id=goal_id, todo_id=todo_id)
    lease = read_lease(lease_path)
    active = lease_is_active(lease)
    executor_constraint: dict[str, Any] | None = None
    if active and lease:
        try:
            todo = task_lease_todo_projection(
                registry_path=registry_path,
                goal_id=goal_id,
                todo_id=todo_id,
            )
        except TaskLeaseError as exc:
            active = False
            executor_constraint = {
                "effective": False,
                "reason": exc.code,
            }
        else:
            executor_constraint = task_lease_owner_constraint(
                todo,
                owner=lease.get("owner"),
                registered_agents=registered_agent_ids_from_registry(registry_path, goal_id),
            )
            if executor_constraint.get("effective") is not True:
                active = False
            else:
                executor_constraint = None
    handoff_mode = _optional_handoff_mode(registry_path, goal_id)
    return {
        "ok": True,
        "schema_version": TASK_LEASE_SCHEMA_VERSION,
        "action": "inspect",
        "goal_id": goal_id,
        "todo_id": todo_id,
        "active": active,
        "lease": lease,
        "lease_path": str(lease_path),
        **({"handoff_mode": handoff_mode} if handoff_mode else {}),
        **({"executor_constraint": executor_constraint} if executor_constraint else {}),
    }

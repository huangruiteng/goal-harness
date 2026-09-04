"""Post-commit bridge from legacy local authority into a file shadow.

The adapter deliberately owns no lifecycle decision. It is entered only after
the existing Markdown or task-lease writer has succeeded, projects public-safe
facts, and asks the TypeScript authority-store boundary to retain an
observation. Missing configuration is a zero-effect fast path.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...file_lock import (
    LockAcquireTimeoutError,
    exclusive_cross_runtime_file_lock,
    exclusive_file_lock,
    try_exclusive_file_lock,
)
from ...history import load_registry
from ...paths import resolve_runtime_root
from ...registry import find_registry_goal
from ..effect_runtime import effect_runtime_result
from . import local_authority_shadow_outbox as outbox
from .local_authority_shadow_projection import (
    LEASE_PARTITION,
    PARTITIONS,
    TODO_PARTITION,
    canonical_value,
    head_digest,
    partition_digest,
    text_digest,
    todo_partition_projection,
)
from .runtime_shadow import resolve_coordination_runtime_shadow_config


LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA = "loopx_local_authority_shadow_config_v0"
LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA = "loopx_local_authority_shadow_request_v0"
LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA = "loopx_local_authority_shadow_projection_v0"
LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA = "loopx_local_authority_shadow_evidence_v0"
_CONFIG_FIELDS = {"schema_version", "mode"}
_PROJECTION_ATTEMPTS = 3
_CONFLICT_RETRY_ATTEMPTS = 3
_EVIDENCE_OUTCOMES = {
    "captured",
    "replayed",
    "ambiguous_reconciled",
    "ambiguous_unproved",
    "unavailable",
    "failed",
    "protocol_mismatch",
    "conflict_retry_required",
}
_TODO_FIELDS = (
    "todo_id",
    "role",
    "status",
    "claimed_by",
    "bound_agent",
    "goal_bound",
    "blocks_agent",
    "excluded_agents",
    "global_gate",
    "task_class",
    "action_kind",
    "required_write_scopes",
    "required_capabilities",
    "continuation_policy",
    "successor_todo_ids",
    "no_followup",
    "completion_continuation",
)
_LEASE_FIELDS = (
    "todo_id",
    "owner",
    "idempotency_key",
    "write_scopes",
    "version",
    "lease_epoch",
    "acquired_at",
    "updated_at",
    "expires_at",
    "released_at",
    "status",
)


def local_authority_shadow_summary(goal: Mapping[str, Any]) -> dict[str, Any]:
    """Project the closed local-shadow configuration for operator readback."""

    coordination = (
        goal.get("coordination")
        if isinstance(goal.get("coordination"), Mapping)
        else {}
    )
    raw = coordination.get("authority_shadow")
    if raw is None:
        return {"enabled": False, "mode": None, "status": "disabled"}
    valid = bool(
        isinstance(raw, Mapping)
        and set(raw) == _CONFIG_FIELDS
        and raw.get("schema_version") == LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA
        and raw.get("mode") == "file_one_way"
    )
    return {
        "enabled": valid,
        "mode": raw.get("mode") if isinstance(raw, Mapping) else None,
        "status": "enabled" if valid else "invalid",
    }


def validate_local_authority_shadow_change(
    enable_file: bool,
    clear: bool,
) -> None:
    """Reject contradictory CLI intent before reading or mutating the registry."""

    if enable_file and clear:
        raise ValueError(
            "--local-authority-shadow-file cannot be combined with "
            "--clear-local-authority-shadow"
        )


def apply_local_authority_shadow_change(
    goal: dict[str, Any],
    enable_file: bool,
    clear: bool,
) -> None:
    """Apply a validated default-off local-shadow configuration change."""

    if not enable_file and not clear:
        return
    coordination = (
        goal.get("coordination") if isinstance(goal.get("coordination"), dict) else {}
    )
    if clear:
        coordination.pop("authority_shadow", None)
    else:
        coordination["authority_shadow"] = {
            "schema_version": LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA,
            "mode": "file_one_way",
        }
    if coordination:
        goal["coordination"] = coordination
    else:
        goal.pop("coordination", None)


def effective_runtime_root(
    registry_path: Path,
    runtime_root_override: str | Path | None,
) -> Path:
    """Resolve the one runtime root every writer hook of a CLI call must share.

    ``--runtime-root`` wins when given; otherwise the registry's
    ``common_runtime_root`` applies, and a relative value resolves against the
    registry's project root rather than the caller's working directory. Todo,
    follow-up, handoff-mode, and task-lease hooks all consume this value so one
    goal never splits into two candidate lineages.
    """

    registry = load_registry(registry_path)
    override = str(runtime_root_override) if runtime_root_override is not None else None
    return resolve_runtime_root(registry, override, registry_path=registry_path)


def _base_evidence(
    *,
    goal_id: str,
    outcome: str,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA,
        "outcome": outcome,
        "reason_code": reason_code,
        "goal_id": goal_id,
        "observation_id": None,
        "source_digest": None,
        "capture_kind": "post_commit_snapshot",
        "source_transaction_correlated": False,
        "durable_source_outbox": False,
        "source_candidate_compared": False,
        "parity_verdict": "not_evaluated",
        "primary_authority": "legacy_local",
        "candidate_provider": "file",
        "candidate_read_for_decision": False,
        "provider_to_local_writes": False,
        "primary_writeback_preserved": True,
        "store_identity": None,
        "provider_revision": None,
        "cursor": None,
    }


def _shadow_config(registry: dict[str, Any], goal_id: str) -> dict[str, str] | None:
    goal = find_registry_goal(registry, goal_id)
    coordination = goal.get("coordination") if isinstance(goal, dict) else None
    if not isinstance(coordination, dict) or "authority_shadow" not in coordination:
        return None
    raw = coordination.get("authority_shadow")
    if (
        not isinstance(raw, dict)
        or set(raw) != _CONFIG_FIELDS
        or raw.get("schema_version") != LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA
        or raw.get("mode") != "file_one_way"
    ):
        raise ValueError("authority_shadow must be a closed file_one_way config")
    return {"mode": "file_one_way"}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _compact_todo(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    todo_id = str(raw.get("todo_id") or "").strip()
    if not todo_id:
        return None
    compact = {field: raw[field] for field in _TODO_FIELDS if field in raw}
    compact["todo_id"] = todo_id
    if "status" not in compact and isinstance(raw.get("done"), bool):
        compact["status"] = "done" if raw["done"] else "open"
    return json.loads(_canonical(compact))


def _compact_lease(path: Path, *, goal_id: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("task lease must contain an object")
    if raw.get("goal_id") != goal_id or raw.get("todo_id") != path.stem:
        raise ValueError("task lease identity does not match its shadow source")
    return json.loads(
        _canonical({field: raw[field] for field in _LEASE_FIELDS if field in raw})
    )


def _source_projection(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
) -> dict[str, Any]:
    from ...control_plane.todos.handoff_mode import goal_handoff_mode_for_goal
    from ...todos import list_goal_todos

    todo_payload = list_goal_todos(
        registry_path=registry_path,
        goal_id=goal_id,
        runtime_root_arg=str(runtime_root),
    )
    todos = [
        compact
        for raw in todo_payload.get("todos") or []
        if (compact := _compact_todo(raw)) is not None
    ]
    todos.sort(key=lambda item: str(item["todo_id"]))
    lease_dir = runtime_root / "goals" / goal_id / "task-leases"
    leases = (
        [
            _compact_lease(path, goal_id=goal_id)
            for path in sorted(lease_dir.glob("*.json"))
        ]
        if lease_dir.exists()
        else []
    )
    projection = {
        "schema_version": LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA,
        "goal_id": goal_id,
        "handoff_mode": goal_handoff_mode_for_goal(
            registry_path=registry_path,
            goal_id=goal_id,
        ),
        "todos": todos,
        "leases": leases,
    }
    return json.loads(_canonical(projection))


def _stable_projection(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
) -> dict[str, Any]:
    previous = _source_projection(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    for _attempt in range(_PROJECTION_ATTEMPTS):
        current = _source_projection(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
        )
        if current == previous:
            return current
        previous = current
    raise RuntimeError("local authority sources did not stabilize for shadowing")


def _valid_evidence(
    result: object,
    *,
    goal_id: str,
    observation_id: str,
    source_digest: str,
) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        result.get("schema_version") == LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA
        and result.get("outcome") in _EVIDENCE_OUTCOMES
        and result.get("goal_id") == goal_id
        and result.get("observation_id") == observation_id
        and result.get("source_digest") == source_digest
        and result.get("capture_kind") == "post_commit_snapshot"
        and result.get("source_transaction_correlated") is False
        and result.get("durable_source_outbox") is False
        and result.get("source_candidate_compared") is False
        and result.get("parity_verdict") == "not_evaluated"
        and result.get("primary_authority") == "legacy_local"
        and result.get("candidate_provider") == "file"
        and result.get("candidate_read_for_decision") is False
        and result.get("provider_to_local_writes") is False
        and result.get("primary_writeback_preserved") is True
        and (
            result.get("reason_code") is None
            or isinstance(result.get("reason_code"), str)
        )
    )


def observe_local_authority_commit(
    *,
    registry_path: Path,
    runtime_root: Path | None,
    goal_id: str,
    observation_trigger: str,
) -> dict[str, Any] | None:
    """Capture a best-effort post-commit snapshot without changing its verdict.

    ``observation_trigger`` is diagnostic context, not a primary transaction
    identity. The snapshot may include commits that landed after that trigger.
    """

    if not goal_id or goal_id in {".", ".."} or "/" in goal_id or "\\" in goal_id:
        return _base_evidence(
            goal_id=goal_id,
            outcome="failed",
            reason_code="invalid_shadow_goal_id",
        )
    try:
        registry = load_registry(registry_path)
        config = _shadow_config(registry, goal_id)
    except Exception:
        return _base_evidence(
            goal_id=goal_id,
            outcome="failed",
            reason_code="invalid_shadow_config",
        )
    if config is None:
        return None

    try:
        if runtime_root is None:
            runtime_root = resolve_runtime_root(
                registry,
                None,
                registry_path=registry_path,
            )
        # Candidate-provider bytes live outside the legacy per-goal runtime
        # tree. State migration may copy that tree, but it must never copy a
        # store identity or revision and accidentally create a second lineage.
        shadow_root = runtime_root / "authority-shadow" / "file" / goal_id
        with exclusive_file_lock(
            shadow_root / "observation",
            timeout_seconds=1.0,
            operation="local_authority_shadow_observe",
        ):
            result: dict[str, Any] | None = None
            for _attempt in range(_CONFLICT_RETRY_ATTEMPTS):
                projection = _stable_projection(
                    registry_path=registry_path,
                    runtime_root=runtime_root,
                    goal_id=goal_id,
                )
                source_digest = (
                    "sha256:" + hashlib.sha256(_canonical(projection)).hexdigest()
                )
                observation_id = (
                    "local-shadow:"
                    + hashlib.sha256(
                        _canonical(
                            {
                                "goal_id": goal_id,
                                "observation_trigger": observation_trigger,
                                "source_digest": source_digest,
                            }
                        )
                    ).hexdigest()
                )
                raw_result = effect_runtime_result(
                    "coordination.local_authority_shadow.record",
                    {
                        "schema_version": LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA,
                        "mode": config["mode"],
                        "runtime_root": str(runtime_root),
                        "goal_id": goal_id,
                        "observation_id": observation_id,
                        "observation_trigger": observation_trigger,
                        "source_digest": source_digest,
                        "source_projection": projection,
                    },
                    timeout=15.0,
                )
                if not _valid_evidence(
                    raw_result,
                    goal_id=goal_id,
                    observation_id=observation_id,
                    source_digest=source_digest,
                ):
                    return _base_evidence(
                        goal_id=goal_id,
                        outcome="failed",
                        reason_code="shadow_observation_result_invalid",
                    )
                result = dict(raw_result)
                if result["outcome"] != "conflict_retry_required":
                    return result
            if result is not None:
                return result
    except LockAcquireTimeoutError:
        return _base_evidence(
            goal_id=goal_id,
            outcome="unavailable",
            reason_code="shadow_observation_lock_timeout",
        )
    except Exception:
        return _base_evidence(
            goal_id=goal_id,
            outcome="failed",
            reason_code="shadow_observation_failed",
        )
    return _base_evidence(
        goal_id=goal_id,
        outcome="failed",
        reason_code="shadow_observation_failed",
    )


def observe_todo_local_authority_commit(
    payload: dict[str, Any],
    registry_path: Path,
    goal_id: str,
    write_class: str,
    *,
    runtime_root: Path | None = None,
) -> dict[str, Any]:
    """Attach post-commit shadow evidence without changing the Todo verdict.

    ``runtime_root`` is the effective root the writer resolved for this call;
    ``None`` falls back to the registry root exactly as the other hooks do.
    """

    changed = any(
        payload.get(field)
        for field in ("changed", "added", "metadata_updated", "completed", "superseded")
    )
    if payload.get("dry_run") or not changed:
        return payload
    todo_id = str(payload.get("todo_id") or "none")
    updated_at = str(payload.get("updated_at") or "unknown")
    evidence = observe_local_authority_commit(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
        observation_trigger=f"{write_class}:{todo_id}:{updated_at}",
    )
    if evidence is not None:
        payload["authority_shadow"] = evidence
    return payload


__all__ = [
    "LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA",
    "LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA",
    "apply_local_authority_shadow_change",
    "effective_runtime_root",
    "local_authority_shadow_summary",
    "observe_local_authority_commit",
    "observe_todo_local_authority_commit",
    "validate_local_authority_shadow_change",
]


# ---------------------------------------------------------------------------
# Transaction-bound outbox drain (Stage 2C second half plumbing).
#
# Writers record per-partition outbox entries inside the primary lock (see
# ``local_authority_shadow_outbox``). The drain below runs after that lock is
# released and turns each committed entry into exactly one candidate
# transaction. It is bounded, never blocks a writer, and reports what it left
# behind instead of guessing.
# ---------------------------------------------------------------------------

LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA_V1 = "loopx_local_authority_shadow_evidence_v1"
LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA = (
    "loopx_coordination_runtime_shadow_commit_entry_request_v0"
)
LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA = (
    "loopx_coordination_runtime_shadow_commit_entry_result_v0"
)
LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA = "loopx_coordination_runtime_shadow_outbox_read_v0"
LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA = "loopx_coordination_runtime_shadow_outbox_read_result_v0"
INLINE_DRAIN_MAX_ENTRIES = 16
INLINE_DRAIN_BUDGET_SECONDS = 2.0
INLINE_DRAIN_LOCK_TIMEOUT_SECONDS = 0.25
CLI_DRAIN_LOCK_TIMEOUT_SECONDS = 5.0
RETENTION_PRESSURE_BYTES = 8 * 1024 * 1024
_COMMIT_ENTRY_OUTCOMES = {
    "delivered",
    "replayed",
    "ambiguous_reconciled",
    "ambiguous_unproved",
    "unavailable",
    "failed",
    "protocol_mismatch",
    "conflict_retry_required",
}
_SETTLED_OUTCOMES = {"delivered", "replayed", "ambiguous_reconciled"}
_SEED_WRITE_CLASSES = {"seed", "reseed_after_crash_gap"}
_ENTRY_SOURCE_FIELDS = ("kind", "previous_bytes_digest", "bytes_digest", "lease", "event_id")
_EVIDENCE_V1_OUTCOMES = {
    "delivered",
    "replayed",
    "ambiguous_reconciled",
    "pending",
    "drain_deferred",
    "no_transaction",
    "capture_failed",
    "ambiguous_unproved",
    "unavailable",
    "failed",
    "protocol_mismatch",
    "conflict_retry_required",
}


@dataclass
class DrainResult:
    """Typed outcome of one bounded drain pass."""

    goal_id: str
    outcome: str = "nothing_pending"
    config_enabled: bool = False
    delivered: int = 0
    replayed: int = 0
    reconciled: int = 0
    no_op: int = 0
    reseeded: int = 0
    reclaimed_residue: int = 0
    pending_after: int = 0
    prepared_only_after: int = 0
    in_flight_partitions: list[str] = field(default_factory=list)
    budget_exhausted: bool = False
    stopped_at: dict[str, Any] | None = None
    reason_code: str | None = None
    store_identity: str | None = None
    provider_revision: str | None = None
    last_cursor: str | None = None
    cursor_before: str | None = None
    cursor_after: str | None = None
    head_digest: str | None = None
    candidate_readback_verified: bool | None = None
    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.outcome in {"drained", "nothing_pending"} and self.stopped_at is None

    @property
    def drained_count(self) -> int:
        return self.delivered + self.replayed + self.reconciled

    def entry_outcome(self, entry_id: str | None) -> dict[str, Any] | None:
        if entry_id is None:
            return None
        for item in self.entries:
            if item.get("entry_id") == entry_id:
                return item
        return None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        payload["drained_count"] = self.drained_count
        return payload


def todo_partition_projector(
    goal: Mapping[str, Any] | None,
    *,
    state_path: Path,
    rollout_events: list[dict[str, Any]] | None = None,
) -> outbox.TodoPartitionProjector:
    """Production projector: parse active-state text into the todos partition."""

    from ...control_plane.todos.handoff_mode import goal_handoff_mode
    from ..todos.goal_todo_projection import project_goal_todo_items

    goal_record = dict(goal) if isinstance(goal, Mapping) else None
    events = list(rollout_events or [])

    def project(state_text: str) -> dict[str, Any]:
        return todo_partition_projection(
            handoff_mode=goal_handoff_mode(state_text),
            todos=project_goal_todo_items(
                goal_record,
                state_text=state_text,
                state_path=state_path,
                rollout_events=events,
            ),
        )

    return project


def primary_lock_is_free(target: Path) -> bool:
    """Probe a partition's Python primary lock once without waiting."""

    try:
        with try_exclusive_file_lock(target, operation="local_authority_shadow_drain_probe") as held:
            return held is not None
    except OSError:
        return False


@dataclass(frozen=True)
class _GoalSources:
    goal: dict[str, Any] | None
    state_path: Path
    lease_dir: Path


def _goal_sources(
    registry: dict[str, Any],
    *,
    runtime_root: Path,
    goal_id: str,
) -> _GoalSources:
    from ...state_refresh import resolve_goal_state

    goal, _project, state_path = resolve_goal_state(
        registry=registry,
        goal_id=goal_id,
        project_override=None,
        state_file_override=None,
    )
    return _GoalSources(
        goal=goal,
        state_path=state_path,
        lease_dir=outbox.lease_directory(runtime_root, goal_id),
    )


def _read_state_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _event_present(sources: _GoalSources, event_id: str) -> bool:
    from ...event_sourced_state import AppendOnlyStateEventStore
    from ..goals.active_state_event_projection import state_event_log_candidates
    from ..goals.path_resolution import resolve_goal_local_path

    if sources.goal is None:
        return False
    for candidate in state_event_log_candidates(
        sources.goal,
        state_path=sources.state_path,
        resolve_goal_local_path=resolve_goal_local_path,
    ):
        if not candidate.exists():
            continue
        for event in AppendOnlyStateEventStore(candidate).load():
            if isinstance(event, dict) and event.get("event_id") == event_id:
                return True
    return False


def _lease_record(sources: _GoalSources, todo_id: str) -> dict[str, Any] | None:
    if not todo_id:
        return None
    path = sources.lease_dir / f"{todo_id}.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def _todo_partition_seed(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    sources: _GoalSources,
) -> outbox.SeedSource:
    """Full todos-partition snapshot; caller holds the state-file lock."""

    from ...control_plane.todos.handoff_mode import goal_handoff_mode
    from ...todos import list_goal_todos

    state_text = _read_state_text(sources.state_path)
    payload = list_goal_todos(
        registry_path=registry_path,
        goal_id=goal_id,
        runtime_root_arg=str(runtime_root),
    )
    projection = todo_partition_projection(
        handoff_mode=goal_handoff_mode(state_text),
        todos=payload.get("todos") or [],
    )
    return outbox.SeedSource(
        partition=TODO_PARTITION,
        projection=projection,
        source_bytes_digest=text_digest(state_text),
    )


@contextmanager
def _primary_lock_if_free(
    partition: str,
    *,
    runtime_root: Path,
    goal_id: str,
    sources: _GoalSources,
) -> Iterator[bool]:
    """Hold the partition's primary lock only if it is free right now."""

    if partition == TODO_PARTITION:
        with try_exclusive_file_lock(
            sources.state_path,
            operation="local_authority_shadow_drain_resolve",
        ) as held:
            yield held is not None
        return
    from ..work_items.task_lease import task_lease_lock_path

    target = task_lease_lock_path(runtime_root=runtime_root, goal_id=goal_id)
    try:
        with exclusive_cross_runtime_file_lock(
            target,
            timeout_seconds=0.0,
            operation="local_authority_shadow_drain_resolve",
        ):
            yield True
    except LockAcquireTimeoutError:
        yield False


def _entry_projection(
    entry: outbox.OutboxEntry,
    *,
    goal_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Compact projection and digest for a deliverable entry."""

    raw = entry.projection()
    if raw is None:
        return None, None
    if entry.partition == LEASE_PARTITION:
        projection = outbox.compact_lease_projection(raw, goal_id=goal_id)
        return projection, partition_digest(projection)
    projection = dict(canonical_value(raw))
    digest = partition_digest(projection)
    recorded = entry.recorded_partition_digest()
    if recorded is not None and recorded != digest:
        raise outbox.OutboxError(
            "outbox_file_invalid",
            f"entry {entry.entry_id} projection does not match its recorded digest",
        )
    return projection, digest


def _commit_entry_request(
    *,
    runtime_root: Path,
    goal_id: str,
    entry: outbox.OutboxEntry,
    resolution: str,
    projection: dict[str, Any] | None,
    digest: str | None,
) -> dict[str, Any]:
    raw_source = entry.prepared.get("source") if isinstance(entry.prepared.get("source"), dict) else {}
    writer = entry.prepared.get("writer") if isinstance(entry.prepared.get("writer"), dict) else {}
    committed_at = entry.committed.get("committed_at") if entry.committed else None
    return {
        "schema_version": LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA,
        "runtime_root": str(runtime_root),
        "goal_id": goal_id,
        "entry": {
            "entry_id": entry.entry_id,
            "partition": entry.partition,
            "seq": entry.seq,
            "writer": {
                "runtime": writer.get("runtime"),
                "write_class": writer.get("write_class"),
                "operation_id": writer.get("operation_id"),
            },
            "source": {key: raw_source.get(key) for key in _ENTRY_SOURCE_FIELDS},
            "source_root_digest": entry.prepared.get("source_root_digest"),
            "prepared_at": entry.prepared.get("prepared_at"),
            "committed_at": committed_at,
            "resolution": resolution,
        },
        "partition_projection": projection,
        "partition_digest": digest,
    }


def _valid_commit_entry_result(result: object, entry: outbox.OutboxEntry) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        result.get("schema_version") == LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA
        and result.get("outcome") in _COMMIT_ENTRY_OUTCOMES
        and result.get("entry_id") == entry.entry_id
        and result.get("partition") == entry.partition
        and result.get("seq") == entry.seq
        and isinstance(result.get("no_op"), bool)
    )


def read_local_authority_shadow(
    *,
    runtime_root: Path,
    goal_id: str,
    store_kind: str = "runtime_shadow",
    scan_after_cursor: str | None = None,
    scan_limit: int = 0,
) -> dict[str, Any]:
    """Read-only candidate view through the TypeScript store boundary."""

    result = effect_runtime_result(
        "coordination.runtime_shadow.outbox_read",
        {
            "schema_version": LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA,
            "runtime_root": str(runtime_root),
            "goal_id": goal_id,
            "store_kind": store_kind,
            "scan_after_cursor": scan_after_cursor,
            "scan_limit": scan_limit,
        },
        timeout=15.0,
    )
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA
        or result.get("goal_id") != goal_id
    ):
        raise RuntimeError("local authority shadow read result is invalid")
    return dict(result)


class _DrainBudget:
    def __init__(self, *, max_entries: int, budget_seconds: float) -> None:
        self._max_entries = max(1, max_entries)
        self._deadline = time.monotonic() + max(0.0, budget_seconds)
        self.consumed = 0

    def exhausted(self) -> bool:
        return self.consumed >= self._max_entries or time.monotonic() >= self._deadline


class _PartitionDrainer:
    """Drain one partition in sequence order; all state lives on ``result``."""

    def __init__(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
        partition: str,
        sources: _GoalSources,
        result: DrainResult,
        budget: _DrainBudget,
    ) -> None:
        self._registry_path = registry_path
        self._runtime_root = runtime_root
        self._goal_id = goal_id
        self._partition = partition
        self._sources = sources
        self._result = result
        self._budget = budget
        self._directory = outbox.partition_directory(runtime_root, goal_id, partition)
        self.last_delivered_digest: str | None = None

    def run(self) -> None:
        # Files the cursor already covers are settled; reclaim them first so a
        # crash between the cursor write and the unlinks can never wedge the
        # partition.
        self._result.reclaimed_residue += outbox.reclaim_retired_residue(self._directory)
        while not self._budget.exhausted():
            entries = outbox.list_entries(self._directory)
            if not entries:
                return
            entry = entries[0]
            if entry.is_committed:
                settled = self._deliver_committed(entry)
            else:
                settled = self._resolve_prepared_only(entry)
            if not settled:
                return
        if outbox.list_entries(self._directory):
            self._result.budget_exhausted = True

    def _deliver_committed(self, entry: outbox.OutboxEntry) -> bool:
        writer = entry.prepared.get("writer") if isinstance(entry.prepared.get("writer"), dict) else {}
        resolution = "seed" if writer.get("write_class") in _SEED_WRITE_CLASSES else "committed"
        projection, digest = _entry_projection(entry, goal_id=self._goal_id)
        if projection is None:
            raise outbox.OutboxError(
                "outbox_file_invalid",
                f"committed entry {entry.entry_id} has no partition projection",
            )
        return self._commit(entry, resolution=resolution, projection=projection, digest=digest)

    def _resolve_prepared_only(self, entry: outbox.OutboxEntry) -> bool:
        with _primary_lock_if_free(
            self._partition,
            runtime_root=self._runtime_root,
            goal_id=self._goal_id,
            sources=self._sources,
        ) as held:
            if not held:
                if self._partition not in self._result.in_flight_partitions:
                    self._result.in_flight_partitions.append(self._partition)
                return False
            resolution = outbox.resolve_prepared_only_entry(
                entry,
                markdown_text_reader=lambda: _read_state_text(self._sources.state_path),
                lease_record_reader=lambda todo_id: _lease_record(self._sources, todo_id),
                event_presence_reader=lambda event_id: _event_present(self._sources, event_id),
            )
            projection: dict[str, Any] | None = None
            digest: str | None = None
            if resolution == "committed":
                projection, digest = _entry_projection(entry, goal_id=self._goal_id)
                if projection is None:
                    resolution = "unproved"
                else:
                    resolution = "committed_proven_by_readback"
            if resolution == "unproved":
                # The source moved in a way no recorded entry explains; a full
                # partition snapshot under the same lock closes the gap.
                seed = (
                    _todo_partition_seed(
                        registry_path=self._registry_path,
                        runtime_root=self._runtime_root,
                        goal_id=self._goal_id,
                        sources=self._sources,
                    )
                    if self._partition == TODO_PARTITION
                    else outbox.lease_seed_source(self._runtime_root, self._goal_id)
                )
                outbox.write_seed_entry(
                    runtime_root=self._runtime_root,
                    goal_id=self._goal_id,
                    seed=seed,
                    write_class="reseed_after_crash_gap",
                )
                self._result.reseeded += 1
        return self._commit(entry, resolution=resolution, projection=projection, digest=digest)

    def _commit(
        self,
        entry: outbox.OutboxEntry,
        *,
        resolution: str,
        projection: dict[str, Any] | None,
        digest: str | None,
    ) -> bool:
        expected_root = outbox.runtime_root_digest(self._runtime_root)
        if entry.prepared.get("source_root_digest") != expected_root:
            # The entry was written for a different runtime root; delivering it
            # here would stitch another lineage's transaction into this one.
            raise outbox.OutboxError(
                "source_root_mismatch",
                f"entry {entry.entry_id} was recorded for a different runtime root",
            )
        request = _commit_entry_request(
            runtime_root=self._runtime_root,
            goal_id=self._goal_id,
            entry=entry,
            resolution=resolution,
            projection=projection,
            digest=digest,
        )
        raw = effect_runtime_result(
            "coordination.runtime_shadow.commit_entry",
            request,
            timeout=15.0,
        )
        self._budget.consumed += 1
        if not _valid_commit_entry_result(raw, entry):
            self._result.stopped_at = {
                "partition": entry.partition,
                "seq": entry.seq,
                "entry_id": entry.entry_id,
                "outcome": "failed",
                "reason_code": "shadow_commit_entry_result_invalid",
            }
            return False
        result = dict(raw)
        summary = {
            "entry_id": entry.entry_id,
            "partition": entry.partition,
            "seq": entry.seq,
            "resolution": resolution,
            "outcome": result["outcome"],
            "reason_code": result.get("reason_code"),
            "cursor": result.get("cursor"),
            "provider_revision": result.get("provider_revision"),
            "partition_digest": digest,
        }
        self._result.entries.append(summary)
        if result.get("store_identity"):
            self._result.store_identity = str(result["store_identity"])
        if result["outcome"] not in _SETTLED_OUTCOMES:
            self._result.stopped_at = {
                "partition": entry.partition,
                "seq": entry.seq,
                "entry_id": entry.entry_id,
                "outcome": result["outcome"],
                "reason_code": result.get("reason_code"),
            }
            return False
        previous = outbox.read_cursor(self._directory)
        cursor_digest = digest
        if cursor_digest is None and previous is not None:
            cursor_digest = previous.get("last_partition_digest")
        outbox.write_cursor(
            self._directory,
            partition=entry.partition,
            last_seq=entry.seq,
            last_entry_id=entry.entry_id,
            last_partition_digest=cursor_digest,
            last_cursor=result.get("cursor"),
            last_provider_revision=result.get("provider_revision"),
        )
        outbox.remove_entry_files(entry)
        if result["outcome"] == "delivered":
            self._result.delivered += 1
        elif result["outcome"] == "replayed":
            self._result.replayed += 1
        else:
            self._result.reconciled += 1
        if result["no_op"]:
            self._result.no_op += 1
        elif digest is not None:
            self.last_delivered_digest = digest
        if result.get("cursor"):
            self._result.last_cursor = str(result["cursor"])
        if result.get("provider_revision"):
            self._result.provider_revision = str(result["provider_revision"])
        return True


def _candidate_cursor(runtime_root: Path, goal_id: str) -> str | None:
    """Current candidate cursor, or None when the store has no document yet."""

    directory = runtime_root / "authority-shadow" / "file-v0"
    if not directory.is_dir() or not any(directory.glob("authority-store-*.json")):
        return None
    try:
        view = read_local_authority_shadow(runtime_root=runtime_root, goal_id=goal_id)
    except Exception:
        return None
    cursor = view.get("cursor")
    return str(cursor) if isinstance(cursor, str) else None


def _verify_readback(
    result: DrainResult,
    *,
    runtime_root: Path,
    goal_id: str,
    delivered_digests: dict[str, str],
) -> None:
    try:
        view = read_local_authority_shadow(runtime_root=runtime_root, goal_id=goal_id)
    except Exception:
        result.candidate_readback_verified = False
        return
    head = view.get("head")
    if view.get("status") != "loaded" or not isinstance(head, dict):
        result.candidate_readback_verified = False
        return
    result.store_identity = view.get("store_identity") or result.store_identity
    result.head_digest = view.get("head_digest")
    result.cursor_after = view.get("cursor")
    verified = head_digest(head) == view.get("head_digest")
    partitions = head.get("partitions") if isinstance(head.get("partitions"), dict) else {}
    for partition, digest in delivered_digests.items():
        marker = partitions.get(partition) if isinstance(partitions, dict) else None
        verified = verified and isinstance(marker, dict) and marker.get("partition_digest") == digest
    result.candidate_readback_verified = verified


def _drain_prelude(
    result: DrainResult,
    *,
    registry_path: Path,
    runtime_root: Path | None,
    goal_id: str,
) -> tuple[dict[str, Any], Path] | None:
    """Validate the goal id and resolve the registry and root; typed failure on error."""

    if not goal_id or goal_id in {".", ".."} or "/" in goal_id or "\\" in goal_id:
        result.outcome = "failed"
        result.reason_code = "invalid_shadow_goal_id"
        return None
    try:
        registry = load_registry(registry_path)
        result.config_enabled = (
            resolve_coordination_runtime_shadow_config(
                find_registry_goal(registry, goal_id)
            ).enabled
            or _shadow_config(registry, goal_id) is not None
        )
        resolved = (
            runtime_root
            if runtime_root is not None
            else resolve_runtime_root(registry, None, registry_path=registry_path)
        )
    except Exception:
        result.outcome = "failed"
        result.reason_code = "invalid_shadow_config"
        return None
    return registry, resolved


def _outbox_is_idle(summary: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(
        item["committed_pending"] == 0
        and item["prepared_only"] == 0
        and item["retired_residue"] == 0
        and item["invalid"] is None
        for item in summary.values()
    )


def _drain_partitions(
    result: DrainResult,
    *,
    registry: dict[str, Any],
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    max_entries: int,
    budget_seconds: float,
) -> None:
    """Drain every partition in order under the held drain lock, then read back."""

    sources = _goal_sources(registry, runtime_root=runtime_root, goal_id=goal_id)
    result.cursor_before = _candidate_cursor(runtime_root, goal_id)
    budget = _DrainBudget(max_entries=max_entries, budget_seconds=budget_seconds)
    delivered_digests: dict[str, str] = {}
    for partition in PARTITIONS:
        if result.stopped_at is not None:
            break
        drainer = _PartitionDrainer(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
            partition=partition,
            sources=sources,
            result=result,
            budget=budget,
        )
        drainer.run()
        if drainer.last_delivered_digest is not None:
            delivered_digests[partition] = drainer.last_delivered_digest
    if delivered_digests or result.drained_count:
        _verify_readback(
            result,
            runtime_root=runtime_root,
            goal_id=goal_id,
            delivered_digests=delivered_digests,
        )


def _settle_drain_outcome(result: DrainResult) -> None:
    if result.stopped_at is not None:
        result.outcome = "stopped"
        result.reason_code = str(result.stopped_at.get("reason_code") or result.stopped_at["outcome"])
    else:
        result.outcome = "drained"


def _count_backlog(result: DrainResult, runtime_root: Path, goal_id: str) -> None:
    summary_after = outbox.outbox_summary(runtime_root, goal_id)
    result.pending_after = sum(int(item["committed_pending"]) for item in summary_after.values())
    result.prepared_only_after = sum(int(item["prepared_only"]) for item in summary_after.values())


def drain_local_authority_shadow_outbox(
    *,
    registry_path: Path,
    runtime_root: Path | None,
    goal_id: str,
    max_entries: int = INLINE_DRAIN_MAX_ENTRIES,
    budget_seconds: float = INLINE_DRAIN_BUDGET_SECONDS,
    lock_timeout_seconds: float = INLINE_DRAIN_LOCK_TIMEOUT_SECONDS,
) -> DrainResult:
    """Deliver pending outbox entries to the candidate store, one transaction each.

    The drain lock is per goal. A held lock means another drainer is already
    at work, so the caller's write stays ``pending`` instead of waiting on it.
    """

    result = DrainResult(goal_id=goal_id)
    prelude = _drain_prelude(
        result, registry_path=registry_path, runtime_root=runtime_root, goal_id=goal_id
    )
    if prelude is None:
        return result
    registry, resolved_root = prelude
    if _outbox_is_idle(outbox.outbox_summary(resolved_root, goal_id)):
        result.outcome = "nothing_pending"
        return result
    try:
        with exclusive_file_lock(
            outbox.drain_lock_target(resolved_root, goal_id),
            timeout_seconds=lock_timeout_seconds,
            operation="local_authority_shadow_drain",
        ):
            _drain_partitions(
                result,
                registry=registry,
                registry_path=registry_path,
                runtime_root=resolved_root,
                goal_id=goal_id,
                max_entries=max_entries,
                budget_seconds=budget_seconds,
            )
    except LockAcquireTimeoutError:
        result.outcome = "drain_deferred"
        result.reason_code = "drain_lock_busy"
    except outbox.OutboxError as error:
        result.outcome = "stopped"
        result.reason_code = error.reason_code
    except Exception:
        result.outcome = "stopped"
        result.reason_code = "shadow_drain_failed"
    else:
        _settle_drain_outcome(result)
    _count_backlog(result, resolved_root, goal_id)
    return result


class _CandidateMissing(Exception):
    """The candidate store directory does not exist yet."""


def _store_bytes(runtime_root: Path, goal_id: str, *, legacy_observation: bool) -> int:
    directory = (
        runtime_root / "authority-shadow" / "file" / goal_id
        if legacy_observation
        else runtime_root / "authority-shadow" / "file-v0"
    )
    if not directory.is_dir():
        return 0
    return sum(path.stat().st_size for path in directory.iterdir() if path.is_file())


def local_authority_shadow_status(
    *,
    registry_path: Path,
    runtime_root: Path | None,
    goal_id: str,
) -> dict[str, Any]:
    """Operator readback: configuration, outbox backlog, and candidate head facts."""

    registry = load_registry(registry_path)
    goal = find_registry_goal(registry, goal_id)
    if not isinstance(goal, dict):
        raise ValueError(f"goal {goal_id!r} is not registered")
    if runtime_root is None:
        runtime_root = resolve_runtime_root(registry, None, registry_path=registry_path)
    config = local_authority_shadow_summary(goal)
    legacy_observation = config["enabled"] is True
    backlog = outbox.outbox_summary(runtime_root, goal_id)
    candidate: dict[str, Any]
    try:
        directory = (
            runtime_root / "authority-shadow" / "file" / goal_id
            if legacy_observation
            else runtime_root / "authority-shadow" / "file-v0"
        )
        if not directory.is_dir() or not any(directory.glob("authority-store-*.json")):
            # Reading through the store boundary would mint a store identity;
            # a status probe must not create candidate lineage.
            raise _CandidateMissing
        view = read_local_authority_shadow(
            runtime_root=runtime_root,
            goal_id=goal_id,
            store_kind=("legacy_observation" if legacy_observation else "runtime_shadow"),
        )
        head = view.get("head") if isinstance(view.get("head"), dict) else None
        candidate = {
            "status": view.get("status"),
            "reason_code": view.get("reason_code"),
            "store_identity": view.get("store_identity"),
            "provider_revision": view.get("provider_revision"),
            "cursor": view.get("cursor"),
            "head_digest": view.get("head_digest"),
            "head_schema_version": head.get("schema_version") if head else None,
            "partitions": view.get("partitions"),
            "codec_agreement": (head_digest(head) == view.get("head_digest")) if head else None,
        }
    except _CandidateMissing:
        candidate = {
            "status": "missing",
            "reason_code": None,
            "store_identity": None,
            "provider_revision": None,
            "cursor": None,
            "head_digest": None,
            "head_schema_version": None,
            "partitions": None,
            "codec_agreement": None,
        }
    except Exception:
        candidate = {
            "status": "unavailable",
            "reason_code": "shadow_read_failed",
            "store_identity": None,
            "provider_revision": None,
            "cursor": None,
            "head_digest": None,
            "head_schema_version": None,
            "partitions": None,
            "codec_agreement": None,
        }
    store_bytes = _store_bytes(
        runtime_root,
        goal_id,
        legacy_observation=legacy_observation,
    )
    return {
        "ok": all(item["invalid"] is None for item in backlog.values()),
        "action": "status",
        "goal_id": goal_id,
        "config": config,
        "runtime_root_digest": outbox.runtime_root_digest(runtime_root),
        "outbox": backlog,
        "candidate": candidate,
        "store_bytes": store_bytes,
        "retention_pressure": store_bytes > RETENTION_PRESSURE_BYTES,
    }


def capture_evidence(
    *,
    goal_id: str,
    capture: outbox.CaptureOutcome,
    drain: DrainResult | None,
) -> dict[str, Any]:
    """Evidence v1 attached to a writer payload: capture facts plus drain facts.

    Every flag here is a measured fact of this write. ``source_candidate_compared``
    and ``parity_verdict`` stay negative until the verify step exists.
    """

    if capture.failure is not None:
        outcome = "capture_failed"
        reason_code: str | None = str(capture.failure.get("reason_code"))
    elif capture.entry_id is None:
        outcome = "no_transaction"
        reason_code = capture.skipped_reason
    elif drain is None or drain.outcome == "drain_deferred":
        outcome = "drain_deferred" if drain is not None else "pending"
        reason_code = drain.reason_code if drain is not None else None
    else:
        settled = drain.entry_outcome(capture.entry_id)
        if settled is None:
            outcome = "pending"
            reason_code = drain.reason_code
        else:
            outcome = str(settled["outcome"])
            reason_code = settled.get("reason_code")
    return {
        "schema_version": LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA_V1,
        "outcome": outcome,
        "reason_code": reason_code,
        "goal_id": goal_id,
        "entry": {
            "entry_id": capture.entry_id,
            "partition": capture.partition,
            "seq": capture.seq,
            "partition_digest": capture.partition_digest,
            "source_bytes_digest": capture.source_bytes_digest,
        },
        "drain": None
        if drain is None
        else {
            "outcome": drain.outcome,
            "delivered": drain.delivered,
            "replayed": drain.replayed,
            "reclaimed_residue": drain.reclaimed_residue,
            "pending_after": drain.pending_after,
            "prepared_only_after": drain.prepared_only_after,
            "stopped_at": drain.stopped_at,
            "last_cursor": drain.last_cursor,
            "provider_revision": drain.provider_revision,
            "candidate_readback_verified": drain.candidate_readback_verified,
        },
        "capture_kind": "source_transaction_outbox",
        # Both flags are measured facts of this write: they are true only when
        # a prepared/committed entry was actually recorded for it. A disabled
        # or unchanged capture recorded nothing and claims nothing.
        "source_transaction_correlated": capture.recorded,
        "durable_source_outbox": capture.recorded,
        "source_candidate_compared": False,
        "parity_verdict": "not_evaluated",
        "primary_authority": "legacy_local",
        "candidate_provider": "file",
        "candidate_read_for_decision": False,
        "provider_to_local_writes": False,
        "primary_writeback_preserved": True,
        "store_identity": drain.store_identity if drain is not None else None,
    }


def valid_evidence_v1(result: object, *, goal_id: str) -> bool:
    """Closed-shape check for evidence v1 as attached to writer payloads."""

    if not isinstance(result, dict):
        return False
    entry = result.get("entry")
    return (
        result.get("schema_version") == LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA_V1
        and result.get("outcome") in _EVIDENCE_V1_OUTCOMES
        and result.get("goal_id") == goal_id
        and isinstance(entry, dict)
        and result.get("capture_kind") == "source_transaction_outbox"
        and isinstance(result.get("source_transaction_correlated"), bool)
        and isinstance(result.get("durable_source_outbox"), bool)
        and result.get("source_candidate_compared") is False
        and result.get("parity_verdict") == "not_evaluated"
        and result.get("primary_authority") == "legacy_local"
        and result.get("candidate_provider") == "file"
        and result.get("candidate_read_for_decision") is False
        and result.get("provider_to_local_writes") is False
        and result.get("primary_writeback_preserved") is True
        and (result.get("reason_code") is None or isinstance(result.get("reason_code"), str))
    )


__all__ += [
    "CLI_DRAIN_LOCK_TIMEOUT_SECONDS",
    "INLINE_DRAIN_BUDGET_SECONDS",
    "INLINE_DRAIN_LOCK_TIMEOUT_SECONDS",
    "INLINE_DRAIN_MAX_ENTRIES",
    "LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_REQUEST_SCHEMA",
    "LOCAL_AUTHORITY_SHADOW_COMMIT_ENTRY_RESULT_SCHEMA",
    "LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA_V1",
    "LOCAL_AUTHORITY_SHADOW_READ_REQUEST_SCHEMA",
    "LOCAL_AUTHORITY_SHADOW_READ_RESULT_SCHEMA",
    "RETENTION_PRESSURE_BYTES",
    "DrainResult",
    "capture_evidence",
    "primary_lock_is_free",
    "todo_partition_projector",
    "drain_local_authority_shadow_outbox",
    "local_authority_shadow_status",
    "read_local_authority_shadow",
    "valid_evidence_v1",
]

"""Task-level checkpoint snapshots (recovery anchor, not a source of truth).

RFC C4 (Task Checkpoint and Replay) + §10.3 Checkpoint Contract:

* A checkpoint is a *recovery optimization*, never an authoritative state
  store. Events remain the source of truth.
* It stores a reference (``goal_id`` / ``todo_id`` / ``run_id`` /
  ``last_event_id``) plus a lightweight state snapshot with a content hash,
  so replay can resume exactly where the checkpoint was taken.
* Schema-versioned so incompatible snapshots are never replayed blindly.
* Checkpoints are appended idempotently under the Goal's runtime directory
  and coexist with existing migration / legacy mechanisms (RFC §10.5).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .time import now_utc_iso

CHECKPOINT_SCHEMA_VERSION = 1

#: Identity fields used for idempotent checkpoint appends.
CHECKPOINT_IDENTITY_FIELDS: tuple[str, ...] = (
    "goal_id",
    "todo_id",
    "last_event_id",
    "state_hash",
)


@dataclass(frozen=True)
class Checkpoint:
    """An immutable Task recovery anchor."""

    checkpoint_id: str
    goal_id: str
    todo_id: str
    run_id: str
    last_event_id: str
    schema_version: int = CHECKPOINT_SCHEMA_VERSION
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    state_hash: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> "Checkpoint":
        payload = value if isinstance(value, dict) else {}
        return cls(
            checkpoint_id=str(payload.get("checkpoint_id") or ""),
            goal_id=str(payload.get("goal_id") or ""),
            todo_id=str(payload.get("todo_id") or ""),
            run_id=str(payload.get("run_id") or ""),
            last_event_id=str(payload.get("last_event_id") or ""),
            schema_version=int(payload.get("schema_version") or CHECKPOINT_SCHEMA_VERSION),
            state_snapshot=dict(payload.get("state_snapshot") or {}),
            state_hash=str(payload.get("state_hash") or ""),
            created_at=str(payload.get("created_at") or ""),
        )


def compute_state_hash(state_snapshot: Mapping[str, Any]) -> str:
    """Deterministic content hash of a state snapshot.

    Sort-keys + stable JSON so identical states always hash identically.
    """
    encoded = json.dumps(
        dict(state_snapshot),
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_checkpoint(
    *,
    goal_id: str,
    todo_id: str,
    run_id: str,
    last_event_id: str,
    state_snapshot: Mapping[str, Any],
    schema_version: int = CHECKPOINT_SCHEMA_VERSION,
    created_at: str | None = None,
) -> Checkpoint:
    """Build a checkpoint; ``state_hash`` is derived automatically."""
    snapshot = dict(state_snapshot)
    state_hash = compute_state_hash(snapshot)
    checkpoint_id = f"{goal_id}:{todo_id}:{last_event_id}:{state_hash[:12]}"
    return Checkpoint(
        checkpoint_id=checkpoint_id,
        goal_id=str(goal_id),
        todo_id=str(todo_id),
        run_id=str(run_id),
        last_event_id=str(last_event_id),
        schema_version=schema_version,
        state_snapshot=snapshot,
        state_hash=state_hash,
        created_at=created_at or now_utc_iso(),
    )


def _goal_checkpoint_dir(runtime_root: Path, goal_id: str) -> Path:
    return Path(runtime_root) / "goals" / goal_id / "checkpoints"


def write_checkpoint(
    runtime_root: Path,
    checkpoint: Checkpoint,
    *,
    identity_fields: tuple[str, ...] = CHECKPOINT_IDENTITY_FIELDS,
) -> tuple[Checkpoint, bool]:
    """Append a checkpoint idempotently; returns (checkpoint, was_new).

    A checkpoint with the same (goal, todo, last_event_id, state_hash) is
    considered an exact duplicate and is not appended twice.
    """
    goal_id = str(checkpoint.goal_id or "").strip()
    todo_id = str(checkpoint.todo_id or "").strip()
    if not goal_id or not todo_id:
        raise ValueError("checkpoint requires goal_id and todo_id")
    checkpoint_dir = _goal_checkpoint_dir(runtime_root, goal_id)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / f"{todo_id}.jsonl"
    payload = checkpoint.to_dict()

    if checkpoint_path.exists():
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if all(str(existing.get(f) or "") == str(payload.get(f) or "") for f in identity_fields):
                return checkpoint, False

    with checkpoint_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
    return checkpoint, True


def load_latest_checkpoint(
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
) -> Checkpoint | None:
    """Load the newest checkpoint for a Task, or ``None``."""
    checkpoint_path = _goal_checkpoint_dir(runtime_root, goal_id) / f"{todo_id}.jsonl"
    if not checkpoint_path.exists():
        return None
    latest: Checkpoint | None = None
    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        checkpoint = Checkpoint.from_dict(payload)
        if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
            continue
        if latest is None or str(checkpoint.created_at or "") >= str(latest.created_at or ""):
            # On timestamp ties, the append-ordered later checkpoint wins.
            latest = checkpoint
    return latest


def load_checkpoints(
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
) -> list[Checkpoint]:
    """Load all checkpoints for a Task in append order."""
    checkpoint_path = _goal_checkpoint_dir(runtime_root, goal_id) / f"{todo_id}.jsonl"
    if not checkpoint_path.exists():
        return []
    checkpoints: list[Checkpoint] = []
    for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            checkpoints.append(Checkpoint.from_dict(payload))
    return checkpoints


def verify_checkpoint_integrity(checkpoint: Checkpoint) -> bool:
    """True when the stored state hash matches a recomputed hash."""
    if not checkpoint.state_hash:
        return False
    return compute_state_hash(checkpoint.state_snapshot) == checkpoint.state_hash


def remove_checkpoints(runtime_root: Path, goal_id: str, todo_id: str) -> bool:
    """Delete a Task's checkpoint file (rollback helper)."""
    checkpoint_path = _goal_checkpoint_dir(runtime_root, goal_id) / f"{todo_id}.jsonl"
    if not checkpoint_path.exists():
        return False
    os.remove(checkpoint_path)
    return True

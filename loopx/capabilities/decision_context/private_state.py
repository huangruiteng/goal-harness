"""Private cursor-state IO for Decision Context."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .profile import DecisionContextProfile


def load_private_decision_cursors(
    path: Path | None,
    *,
    profile: DecisionContextProfile,
) -> dict[str, str]:
    """Load private cursors without projecting their values into public output."""

    if path is None or not path.expanduser().exists():
        return {}
    try:
        with path.expanduser().open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("decision-context cursor state is unavailable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("decision-context cursor state must be an object")

    source_ids = {source.source_id for source in profile.sources}
    unexpected = sorted(str(key) for key in payload if str(key) not in source_ids)
    if unexpected:
        raise ValueError(
            "decision-context cursor state contains unknown source ids: "
            + ", ".join(unexpected)
        )

    cursors: dict[str, str] = {}
    for source_id, value in payload.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError("decision-context cursor values must be non-empty strings")
        cursors[str(source_id)] = value.strip()
    return cursors


def private_file_digest(path: Path) -> str:
    try:
        payload = path.expanduser().read_bytes()
    except OSError as exc:
        raise ValueError("decision-context private state is unavailable") from exc
    return hashlib.sha256(payload).hexdigest()


def write_private_decision_cursors_atomic(
    path: Path,
    cursors: Mapping[str, str],
) -> None:
    destination = path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                dict(sorted(cursors.items())),
                handle,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(
            destination.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)

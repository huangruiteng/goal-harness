"""Private cursor-state IO for Decision Context."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .assembler import DecisionContextAssembly
from .profile import DecisionContextProfile


DECISION_PENDING_SETTLEMENT_SCHEMA_VERSION = (
    "decision_context_pending_settlement_v0"
)


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
    _write_private_json_atomic(path, dict(sorted(cursors.items())))


def write_private_pending_decision_settlement(
    path: Path,
    assembly: DecisionContextAssembly,
) -> None:
    """Persist unapplied cursor proposals for a cross-turn owner gate."""

    _write_private_json_atomic(
        path,
        {
            "schema_version": DECISION_PENDING_SETTLEMENT_SCHEMA_VERSION,
            "assembly": assembly.public_packet(),
            "proposed_cursors": dict(sorted(assembly.proposed_cursors.items())),
            "expected_cursors": dict(sorted(assembly.expected_cursors.items())),
            "profile_digest": assembly.profile_digest,
            "runtime_bound_provider_ids": list(assembly.runtime_bound_provider_ids),
            "active_cursor_state_mutated": False,
        },
    )


def load_private_pending_decision_settlement(
    path: Path,
) -> DecisionContextAssembly:
    """Reload a private pending settlement without exposing cursor values."""

    try:
        with path.expanduser().open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("decision-context pending settlement is unavailable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("decision-context pending settlement must be an object")
    allowed = {
        "schema_version",
        "assembly",
        "proposed_cursors",
        "expected_cursors",
        "profile_digest",
        "runtime_bound_provider_ids",
        "active_cursor_state_mutated",
    }
    if set(payload) != allowed:
        raise ValueError("decision-context pending settlement fields are invalid")
    if payload.get("schema_version") != DECISION_PENDING_SETTLEMENT_SCHEMA_VERSION:
        raise ValueError("decision-context pending settlement schema is invalid")
    if payload.get("active_cursor_state_mutated") is not False:
        raise ValueError("decision-context pending settlement cannot apply cursors")
    assembly = payload.get("assembly")
    proposed = payload.get("proposed_cursors")
    expected = payload.get("expected_cursors")
    provider_ids = payload.get("runtime_bound_provider_ids")
    profile_digest = payload.get("profile_digest")
    if not isinstance(assembly, Mapping):
        raise ValueError("decision-context pending assembly is invalid")
    if not isinstance(proposed, Mapping) or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not key.strip()
        or not value.strip()
        for key, value in proposed.items()
    ):
        raise ValueError("decision-context pending cursor proposals are invalid")
    if not isinstance(expected, Mapping) or any(
        not isinstance(key, str)
        or not key.strip()
        or (value is not None and (not isinstance(value, str) or not value.strip()))
        for key, value in expected.items()
    ):
        raise ValueError("decision-context pending expected cursors are invalid")
    if (
        isinstance(provider_ids, (str, bytes))
        or not isinstance(provider_ids, list)
        or any(not isinstance(value, str) or not value.strip() for value in provider_ids)
    ):
        raise ValueError("decision-context pending provider ids are invalid")
    if not isinstance(profile_digest, str) or not profile_digest.strip():
        raise ValueError("decision-context pending profile digest is invalid")
    return DecisionContextAssembly(
        packet=dict(assembly),
        proposed_cursors={str(key): str(value) for key, value in proposed.items()},
        expected_cursors={str(key): value for key, value in expected.items()},
        profile_digest=profile_digest,
        runtime_bound_provider_ids=tuple(sorted(set(provider_ids))),
    )


def _write_private_json_atomic(
    path: Path,
    payload: Mapping[str, object],
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
                payload,
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

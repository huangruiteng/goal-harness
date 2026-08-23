"""File-backed coordination provider: one atomic CAS document per goal.

Storage plane only (RFC section 6.2): it serializes the opaque head it is
given, replaces the document atomically, and reports typed outcomes. It never
parses commands, mints clocks or leases, or interprets the head. Concurrency
is resolved by generation compare inside an exclusive file lock; crash
windows surface as ``ambiguous`` so the authority reloads and trusts only its
atomically stored receipt index.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any


class ProviderProtocolError(RuntimeError):
    """Persisted bytes or a provider outcome violated the storage contract."""


def _canonical(envelope: dict[str, Any]) -> bytes:
    # allow_nan=False: non-finite floats would produce bytes a strict JSON
    # reader rejects, so they must fail before ever reaching the document.
    return json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class FileCoordinationProvider:
    """Map one goal's head document onto an atomically replaced JSON file."""

    def __init__(self, directory: Path | str, goal_id: str):
        if not goal_id:
            raise ProviderProtocolError("provider goal_id must be non-empty")
        self.directory = Path(directory)
        self.goal_id = goal_id
        digest = hashlib.sha256(goal_id.encode("utf-8")).hexdigest()[:16]
        self._document = self.directory / f"coordination-head-{digest}.json"
        self._lock_path = self.directory / f"coordination-head-{digest}.lock"

    def _read_envelope(self) -> tuple[dict[str, Any] | None, int]:
        try:
            raw = self._document.read_bytes()
        except FileNotFoundError:
            return None, 0
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderProtocolError(
                f"coordination document is not valid JSON: {exc}"
            ) from exc
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"provider_generation", "head"}
            or not isinstance(envelope["provider_generation"], int)
            or envelope["provider_generation"] < 1
            or not isinstance(envelope["head"], dict)
        ):
            raise ProviderProtocolError(
                "coordination document envelope does not match the v0 contract"
            )
        return envelope["head"], envelope["provider_generation"]

    def load(self) -> tuple[dict[str, Any] | None, int]:
        """Return ``(head | None, provider_generation)``."""

        return self._read_envelope()

    def compare_and_put(
        self,
        expected_provider_generation: int,
        head: dict[str, Any],
    ) -> dict[str, Any]:
        """Serialize and conditionally replace the opaque head document."""

        if (
            not isinstance(expected_provider_generation, int)
            or expected_provider_generation < 0
        ):
            return {
                "result": "failed",
                "error": "expected_provider_generation must be a non-negative integer",
            }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            lock_file = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            # No replace was attempted, so this failure proves no write.
            return {"result": "failed", "error": str(exc)}
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            current_head, current_generation = self._read_envelope()
            del current_head
            if current_generation != expected_provider_generation:
                return {
                    "result": "conflict",
                    "current_provider_generation": current_generation,
                }
            next_generation = expected_provider_generation + 1
            try:
                envelope = _canonical(
                    {"provider_generation": next_generation, "head": head}
                )
            except (TypeError, ValueError) as exc:
                # Serialization runs before any write, so this failure proves
                # no write; it must surface as the typed verb, never as an
                # unclassified exception through the seam.
                return {
                    "result": "failed",
                    "error": f"head is not canonically serializable: {exc}",
                }
            temp_path = self._document.with_suffix(
                f".tmp-{os.getpid()}-{next_generation}"
            )
            try:
                descriptor = os.open(
                    temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
                )
                try:
                    os.write(descriptor, envelope)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temp_path, self._document)
            except OSError:
                # The replace outcome is unknown from here: the temp write may
                # or may not have been renamed. Never parse error text as
                # commit proof — report ambiguous and let the authority
                # reload its atomically stored receipt index.
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                return {"result": "ambiguous"}
            return {"result": "applied", "provider_generation": next_generation}
        finally:
            os.close(lock_file)

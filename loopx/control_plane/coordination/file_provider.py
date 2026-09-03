"""File-backed coordination provider: one atomic CAS document per goal.

Storage plane only (RFC section 6.2): it serializes the opaque head it is
given, replaces the document atomically, and reports typed outcomes. It never
parses commands, mints clocks or leases, or interprets the head. Concurrency
is resolved by generation compare while holding the repository's one
cross-platform lock owner (``loopx.file_lock``) with its bounded deadline; a
lock that cannot be acquired in time is a typed ``failed`` because no write
was attempted.

Durability is a fixed commit sequence: write the complete canonical bytes to
an exclusive temporary file (short writes are continued, never ignored),
fsync the file, atomically rename it over the document, then fsync the parent
directory so the rename itself is durable. ``applied`` is returned only after
the whole sequence converges; any storage fault inside the sequence surfaces
as ``ambiguous`` so the authority reloads and trusts only its atomically
stored receipt index. On Windows there is no directory-handle fsync; the
rename's durability there follows platform semantics and the directory step
is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from ...file_lock import LockAcquireTimeoutError, exclusive_file_lock


class ProviderProtocolError(RuntimeError):
    """Persisted bytes or a provider outcome violated the storage contract."""


_STORE_IDENTITY_PATTERN = re.compile(r"file:[0-9a-f]{32}\Z")


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


def _write_all(descriptor: int, payload: bytes) -> None:
    # os.write may write fewer bytes than asked; a partial write that is not
    # continued would let a truncated document masquerade as applied.
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("write made no progress")
        view = view[written:]


# The commit-sequence steps below are module seams on purpose: fault
# injection in tests targets the provider's own document commit without
# touching the global os attributes that loopx.file_lock's holder
# bookkeeping also uses (its Windows sidecar path calls os.fsync and
# os.replace of its own).


def _fsync_file(descriptor: int) -> None:
    os.fsync(descriptor)


def _replace_document(source: Path, target: Path) -> None:
    os.replace(source, target)


def _fsync_directory(directory: Path) -> None:
    # The rename only becomes durable once the parent directory entry is
    # flushed. Windows exposes no directory-handle fsync; there the rename's
    # durability follows platform semantics.
    if os.name != "posix":  # pragma: no cover - exercised on Windows hosts
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durably_replace_bytes(target: Path, payload: bytes, temp_path: Path) -> None:
    """Publish complete bytes atomically and make the directory entry durable."""

    try:
        descriptor = os.open(
            temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
        )
        try:
            _write_all(descriptor, payload)
            _fsync_file(descriptor)
        finally:
            os.close(descriptor)
        _replace_document(temp_path, target)
        _fsync_directory(target.parent)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


class FileCoordinationProvider:
    """Map one goal's head document onto an atomically replaced JSON file."""

    def __init__(
        self,
        directory: Path | str,
        goal_id: str,
        *,
        lock_timeout_seconds: float | None = None,
    ):
        if not goal_id:
            raise ProviderProtocolError("provider goal_id must be non-empty")
        self.directory = Path(directory)
        self.goal_id = goal_id
        self._lock_timeout_seconds = lock_timeout_seconds
        digest = hashlib.sha256(goal_id.encode("utf-8")).hexdigest()[:16]
        self._document = self.directory / f"coordination-head-{digest}.json"
        self._identity_path = self.directory / "store-identity"
        self._store_identity: str | None = None

    def store_identity(self) -> str:
        """The stable identity of this store lineage (Stage 3 binding fence).

        Minted once per directory under the provider's cross-process lock and
        published only after a complete temp-file write, file fsync, atomic
        rename, and parent-directory fsync. Every competing creator therefore
        observes the same complete value. A copy of the documents into a fresh
        directory yields a NEW identity, so a head bound to the original
        lineage is detectable there.
        """

        if self._store_identity is not None:
            return self._store_identity
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with exclusive_file_lock(
                self._identity_path,
                timeout_seconds=self._lock_timeout_seconds,
                operation="coordination_store_identity",
            ):
                try:
                    raw_identity = self._identity_path.read_bytes()
                except FileNotFoundError:
                    identity = f"file:{uuid.uuid4().hex}"
                    temp_path = self._identity_path.with_name(
                        f"{self._identity_path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
                    )
                    _durably_replace_bytes(
                        self._identity_path,
                        identity.encode("ascii"),
                        temp_path,
                    )
                    self._store_identity = identity
                    return identity
                try:
                    identity = raw_identity.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise ProviderProtocolError(
                        "store identity does not match file:<32 lowercase hex>"
                    ) from exc
                if _STORE_IDENTITY_PATTERN.fullmatch(identity) is None:
                    raise ProviderProtocolError(
                        "store identity does not match file:<32 lowercase hex>"
                    )
                # A previous creator may have renamed successfully but failed
                # while fsyncing the directory. Retrying the read completes
                # that durability sequence before the identity is trusted.
                _fsync_directory(self.directory)
                self._store_identity = identity
                return identity
        except LockAcquireTimeoutError as exc:
            raise ProviderProtocolError(
                f"store identity lock is unavailable: {exc}"
            ) from exc
        except ProviderProtocolError:
            raise
        except OSError as exc:
            raise ProviderProtocolError(
                f"store identity is unavailable: {exc}"
            ) from exc

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
        generation = envelope.get("provider_generation") if isinstance(envelope, dict) else None
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"provider_generation", "head"}
            # bool is an int subclass; JSON true must not load as generation 1
            # and silently repair a corrupt envelope into a valid lineage.
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 1
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
            or isinstance(expected_provider_generation, bool)
            or expected_provider_generation < 0
        ):
            return {
                "result": "failed",
                "error": "expected_provider_generation must be a non-negative integer",
            }
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # No replace was attempted, so this failure proves no write.
            return {"result": "failed", "error": str(exc)}
        outcome: dict[str, Any] | None = None
        try:
            with exclusive_file_lock(
                self._document,
                timeout_seconds=self._lock_timeout_seconds,
                operation="coordination_compare_and_put",
            ):
                outcome = self._replace_under_lock(
                    expected_provider_generation, head
                )
        except LockAcquireTimeoutError as exc:
            # Bounded wait expired before any write was attempted.
            return {"result": "failed", "error": str(exc)}
        except ProviderProtocolError:
            raise
        except OSError as exc:
            if outcome is not None:
                # The verdict was already computed; a release-bookkeeping
                # failure afterwards must not misreport a durable write.
                return outcome
            return {"result": "failed", "error": str(exc)}
        return outcome

    def _replace_under_lock(
        self,
        expected_provider_generation: int,
        head: dict[str, Any],
    ) -> dict[str, Any]:
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
            f".tmp-{os.getpid()}-{next_generation}-{uuid.uuid4().hex}"
        )
        try:
            _durably_replace_bytes(self._document, envelope, temp_path)
        except OSError:
            # The commit sequence did not provably converge: the temp write
            # may or may not have been renamed, and a rename may or may not
            # be durable yet. Never parse error text as commit proof —
            # report ambiguous and let the authority reload its atomically
            # stored receipt index.
            return {"result": "ambiguous"}
        return {"result": "applied", "provider_generation": next_generation}

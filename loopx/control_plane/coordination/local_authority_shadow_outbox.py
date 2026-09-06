"""Durable, transaction-bound outbox for the local authority shadow.

A legacy writer that changes coordination facts records, inside the lock it
already holds, a two-phase entry for exactly the state that lock guards (one
*partition*): a ``prepared`` file computed from the bytes about to be written,
then a ``committed`` marker after the primary write returns. Nothing in the
lock talks to the TypeScript runtime. A later drain (same process after the
lock, or an operator command) turns each committed entry into exactly one
candidate-store transaction whose ``operation_id`` is the entry id.

The outbox never changes the primary verdict: every failure here is swallowed
into typed capture evidence and the primary write proceeds unchanged.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_authority_shadow_projection import (
    LEASE_PARTITION,
    PARTITIONS,
    TODO_PARTITION,
    ProjectionValueError,
    canonical_value,
    lease_partition_projection,
    partition_digest,
    sha256_digest,
    text_digest,
)
from .coordination_state_contract_generated import (
    LOCAL_AUTHORITY_SHADOW_DRAIN_CURSOR_SCHEMA,
    LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA,
    LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA,
)


OUTBOX_ENTRY_SCHEMA = LOCAL_AUTHORITY_SHADOW_OUTBOX_ENTRY_SCHEMA
OUTBOX_COMMIT_SCHEMA = LOCAL_AUTHORITY_SHADOW_OUTBOX_COMMIT_SCHEMA
DRAIN_CURSOR_SCHEMA = LOCAL_AUTHORITY_SHADOW_DRAIN_CURSOR_SCHEMA
SOURCE_MARKDOWN = "markdown_active_state"
SOURCE_STATE_EVENT_LOG = "state_event_log"
SOURCE_TASK_LEASE = "task_lease_record"
WRITER_RUNTIME_PYTHON = "python"
WRITER_RUNTIME_TYPESCRIPT = "typescript"
ENTRY_ID_PREFIX = "local-shadow-tx-"
_ENTRY_FILE = re.compile(
    r"^(?P<seq>\d{10})-(?P<entry_id>local-shadow-tx-[0-9a-f]{64})\.(?P<phase>prepared|committed)\.json$"
)
_LEASE_FILE = re.compile(r"^[A-Za-z0-9_.-]+\.json$")


class OutboxError(RuntimeError):
    """Typed outbox failure; never escapes into a primary write."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


TodoPartitionProjector = Callable[[str], dict[str, Any]]
"""Active-state Markdown text -> ``{"handoff_mode": str, "todos": [compact...]}``."""


def utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def outbox_root(runtime_root: Path, goal_id: str) -> Path:
    return runtime_root / "authority-shadow" / "outbox" / goal_id


def partition_directory(runtime_root: Path, goal_id: str, partition: str) -> Path:
    if partition not in PARTITIONS:
        raise OutboxError("invalid_partition", f"unknown outbox partition {partition!r}")
    return outbox_root(runtime_root, goal_id) / partition


def drain_lock_target(runtime_root: Path, goal_id: str) -> Path:
    return outbox_root(runtime_root, goal_id) / "drain"


def lease_directory(runtime_root: Path, goal_id: str) -> Path:
    return runtime_root / "goals" / goal_id / "task-leases"


def entry_identity(*, goal_id: str, partition: str, seq: int, source_ref: str) -> str:
    """Bind the entry id to the exact primary bytes (or event) it records."""

    return ENTRY_ID_PREFIX + sha256_digest(
        {"goal_id": goal_id, "partition": partition, "seq": seq, "source_ref": source_ref}
    ).removeprefix("sha256:")


def entry_file_name(seq: int, entry_id: str, phase: str) -> str:
    return f"{seq:010d}-{entry_id}.{phase}.json"


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Temp file in the same directory, fsync, atomic replace, directory fsync."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _as_object(value: object) -> dict[str, Any]:
    """Narrow an untyped JSON value to an object; anything else is empty."""

    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise OutboxError("outbox_file_invalid", f"{path.name} is not a JSON object")
    return raw


@dataclass(frozen=True, slots=True)
class OutboxEntry:
    """One two-phase entry as found on disk."""

    partition: str
    seq: int
    entry_id: str
    prepared_path: Path
    committed_path: Path | None
    prepared: dict[str, Any]
    committed: dict[str, Any] | None

    @property
    def is_committed(self) -> bool:
        return self.committed is not None

    @property
    def source_ref(self) -> str:
        return str(record_source_ref(self.prepared))

    def projection(self) -> dict[str, Any] | None:
        """The partition projection recorded for this entry, if any."""

        for record in (self.committed, self.prepared):
            if isinstance(record, dict) and isinstance(record.get("projection"), dict):
                return dict(record["projection"])
        return None

    def recorded_partition_digest(self) -> str | None:
        for record in (self.committed, self.prepared):
            if isinstance(record, dict) and isinstance(record.get("partition_digest"), str):
                return str(record["partition_digest"])
        return None


_EntryKey = tuple[int, str]


def _index_entry_files(directory: Path) -> tuple[dict[_EntryKey, Path], dict[_EntryKey, Path]]:
    """Map ``(seq, entry_id)`` to the prepared and committed files present."""

    prepared: dict[_EntryKey, Path] = {}
    committed: dict[_EntryKey, Path] = {}
    for path in directory.iterdir():
        match = _ENTRY_FILE.match(path.name)
        if match is None:
            continue
        key = (int(match.group("seq")), match.group("entry_id"))
        target = prepared if match.group("phase") == "prepared" else committed
        target[key] = path
    return prepared, committed


_WRITER_RUNTIMES = frozenset({WRITER_RUNTIME_PYTHON, WRITER_RUNTIME_TYPESCRIPT})
_SOURCE_KINDS = frozenset({SOURCE_MARKDOWN, SOURCE_STATE_EVENT_LOG, SOURCE_TASK_LEASE})
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _load_prepared_record(
    path: Path,
    *,
    directory: Path,
    seq: int,
    entry_id: str,
) -> dict[str, Any]:
    """Load one prepared record and prove it binds this directory and entry id.

    The file name, the directory (``outbox/<goal>/<partition>``), the record's
    own goal/partition fields, and the entry id recomputed from the record's
    source reference must all agree; a record that was copied, edited, or
    written for another goal fails closed before it can reach the candidate.
    """

    record = _load_json(path)
    writer = _as_object(record.get("writer"))
    source = _as_object(record.get("source"))
    expected_goal = directory.parent.name
    expected_partition = directory.name
    source_ref = record_source_ref(record)
    root_digest = record.get("source_root_digest")
    bound = (
        record.get("schema_version") == OUTBOX_ENTRY_SCHEMA
        and record.get("entry_id") == entry_id
        and record.get("seq") == seq
        and record.get("goal_id") == expected_goal
        and record.get("partition") == expected_partition
        and writer.get("runtime") in _WRITER_RUNTIMES
        and isinstance(writer.get("write_class"), str)
        and bool(writer.get("write_class"))
        and source.get("kind") in _SOURCE_KINDS
        and isinstance(root_digest, str)
        and _DIGEST_PATTERN.match(root_digest) is not None
        and source_ref is not None
        and entry_identity(
            goal_id=expected_goal,
            partition=expected_partition,
            seq=seq,
            source_ref=source_ref,
        )
        == entry_id
    )
    if not bound:
        raise OutboxError(
            "outbox_file_invalid",
            f"{path.name} does not bind its directory, identity, and source reference",
        )
    return record


def _load_committed_record(path: Path | None, *, entry_id: str) -> dict[str, Any] | None:
    if path is None:
        return None
    record = _load_json(path)
    if record.get("schema_version") != OUTBOX_COMMIT_SCHEMA or record.get("entry_id") != entry_id:
        raise OutboxError("outbox_file_invalid", f"{path.name} does not match its entry")
    return record


def _retired_watermark(directory: Path) -> int:
    cursor = read_cursor(directory)
    return int(cursor.get("last_seq") or 0) if cursor is not None else 0


def retired_residue(directory: Path) -> list[Path]:
    """Entry files at or below the durable cursor.

    The cursor is written before an entry's files are unlinked, so anything it
    covers is already settled in the candidate store. A crash between the
    cursor write and the unlinks, or between the two unlinks, leaves these
    files behind; they are residue to reclaim, never entries to deliver or
    markers to reject.
    """

    if not directory.is_dir():
        return []
    watermark = _retired_watermark(directory)
    prepared, committed = _index_entry_files(directory)
    residue = [
        path
        for key, path in [*prepared.items(), *committed.items()]
        if key[0] <= watermark
    ]
    return sorted(residue)


def reclaim_retired_residue(directory: Path) -> int:
    """Unlink retired residue; the caller must hold the goal's drain lock."""

    residue = retired_residue(directory)
    for path in residue:
        path.unlink(missing_ok=True)
    return len(residue)


def list_entries(directory: Path) -> list[OutboxEntry]:
    """All live entries of one partition directory, oldest first.

    Files the durable cursor already covers are retired residue and are not
    listed; a committed marker without a prepared entry above the cursor is
    real corruption and fails closed.
    """

    if not directory.is_dir():
        return []
    watermark = _retired_watermark(directory)
    prepared, committed = _index_entry_files(directory)
    prepared = {key: path for key, path in prepared.items() if key[0] > watermark}
    committed = {key: path for key, path in committed.items() if key[0] > watermark}
    orphan_markers = sorted(set(committed) - set(prepared))
    if orphan_markers:
        seq, entry_id = orphan_markers[0]
        raise OutboxError(
            "outbox_file_invalid",
            f"committed marker without prepared entry: {entry_file_name(seq, entry_id, 'committed')}",
        )
    entries: list[OutboxEntry] = []
    for seq, entry_id in sorted(prepared):
        key = (seq, entry_id)
        prepared_record = _load_prepared_record(
            prepared[key], directory=directory, seq=seq, entry_id=entry_id
        )
        entries.append(
            OutboxEntry(
                partition=str(prepared_record.get("partition") or directory.name),
                seq=seq,
                entry_id=entry_id,
                prepared_path=prepared[key],
                committed_path=committed.get(key),
                prepared=prepared_record,
                committed=_load_committed_record(committed.get(key), entry_id=entry_id),
            )
        )
    return entries


def cursor_path(directory: Path) -> Path:
    return directory / "drain-cursor.json"


def read_cursor(directory: Path) -> dict[str, Any] | None:
    path = cursor_path(directory)
    if not path.exists():
        return None
    record = _load_json(path)
    if record.get("schema_version") != DRAIN_CURSOR_SCHEMA:
        raise OutboxError("outbox_file_invalid", "drain cursor schema is unsupported")
    return record


def write_cursor(
    directory: Path,
    *,
    partition: str,
    last_seq: int,
    last_entry_id: str,
    last_partition_digest: str | None,
    last_cursor: str | None,
    last_provider_revision: str | None,
) -> None:
    durable_write_json(
        cursor_path(directory),
        {
            "schema_version": DRAIN_CURSOR_SCHEMA,
            "partition": partition,
            "last_seq": last_seq,
            "last_entry_id": last_entry_id,
            "last_partition_digest": last_partition_digest,
            "last_cursor": last_cursor,
            "last_provider_revision": last_provider_revision,
            "updated_at": utc_now_text(),
        },
    )


def next_seq(directory: Path) -> int:
    """Gap-free sequence: past the newest file and the drained watermark."""

    highest = 0
    if directory.is_dir():
        for path in directory.iterdir():
            match = _ENTRY_FILE.match(path.name)
            if match is not None:
                highest = max(highest, int(match.group("seq")))
    cursor = read_cursor(directory)
    if cursor is not None:
        highest = max(highest, int(cursor.get("last_seq") or 0))
    return highest + 1


def latest_partition_digest(directory: Path) -> str | None:
    """Digest of the newest known partition state (pending entry, else cursor)."""

    entries = list_entries(directory)
    for entry in reversed(entries):
        digest = entry.recorded_partition_digest()
        if digest is not None:
            return digest
    cursor = read_cursor(directory)
    if cursor is not None and isinstance(cursor.get("last_partition_digest"), str):
        return str(cursor["last_partition_digest"])
    return None


def runtime_root_digest(runtime_root: Path) -> str:
    """Digest of the absolute, dot-normalized root; must match the TypeScript writer.

    Symlinks are deliberately not resolved: both runtimes normalize the string
    they were given, so a root passed through the effect runtime hashes the
    same on either side.
    """

    return text_digest(os.path.abspath(str(runtime_root)))


def record_source_ref(record: Mapping[str, Any]) -> str | None:
    """The source reference an entry id binds: bytes digest, event id, or seed digest."""

    source = _as_object(record.get("source"))
    bytes_digest = source.get("bytes_digest")
    if isinstance(bytes_digest, str) and bytes_digest:
        return bytes_digest
    event_id = source.get("event_id")
    if isinstance(event_id, str) and event_id:
        return f"event:{event_id}"
    digest = record.get("partition_digest")
    if isinstance(digest, str) and digest:
        return f"seed:{digest}"
    return None


def read_lease_records(directory: Path) -> list[tuple[str, dict[str, Any]]]:
    """Top-level lease records of a goal; lifecycle receipts are excluded."""

    if not directory.is_dir():
        return []
    records: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or not _LEASE_FILE.match(path.name) or path.name.startswith("."):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            records.append((path.stem, raw))
    return records


def compact_lease_projection(
    raw_projection: Mapping[str, Any], *, goal_id: str
) -> dict[str, Any]:
    """Compact the TypeScript-written lease partition (``{leases: [{file_stem, record}]}``)."""

    raw_leases = raw_projection.get("leases")
    if not isinstance(raw_leases, list):
        raise OutboxError("outbox_file_invalid", "lease partition projection must list leases")
    records: list[tuple[str, object]] = []
    for item in raw_leases:
        if not isinstance(item, dict):
            raise OutboxError("outbox_file_invalid", "lease projection item must be an object")
        stem = item.get("file_stem")
        if not isinstance(stem, str) or not stem:
            raise OutboxError("outbox_file_invalid", "lease projection item needs a file_stem")
        records.append((stem, item.get("record")))
    try:
        return lease_partition_projection(records, goal_id=goal_id)
    except ProjectionValueError as error:
        raise OutboxError("outbox_file_invalid", str(error)) from error


def _writer(write_class: str, *, runtime: str, operation_id: str | None) -> dict[str, Any]:
    return {"runtime": runtime, "write_class": write_class, "operation_id": operation_id}


def _entry_record(
    *,
    goal_id: str,
    partition: str,
    seq: int,
    entry_id: str,
    writer: Mapping[str, Any],
    source: Mapping[str, Any],
    source_root_digest: str,
    projection: Mapping[str, Any] | None,
    digest: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": OUTBOX_ENTRY_SCHEMA,
        "goal_id": goal_id,
        "partition": partition,
        "seq": seq,
        "entry_id": entry_id,
        "writer": dict(writer),
        "source": dict(source),
        "source_root_digest": source_root_digest,
        "projection": canonical_value(dict(projection)) if projection is not None else None,
        "partition_digest": digest,
        "prepared_at": utc_now_text(),
    }


@dataclass
class CaptureOutcome:
    """What the capture did for one primary write (attached to its evidence)."""

    entry_id: str | None = None
    partition: str | None = None
    seq: int | None = None
    partition_digest: str | None = None
    source_bytes_digest: str | None = None
    skipped_reason: str | None = None
    failure: dict[str, Any] | None = None

    @property
    def recorded(self) -> bool:
        return self.entry_id is not None and self.failure is None


class TodoPartitionCapture:
    """Two-phase capture of the todos partition inside the active-state lock.

    ``begin`` returns an inert capture when the goal has no shadow binding, so
    default-off writers create no directory, lock, or file.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        runtime_root: Path | None,
        goal_id: str,
        state_path: Path | None,
        write_class: str,
        original_text: str,
        projector: TodoPartitionProjector | None,
    ) -> None:
        self._enabled = enabled
        self._runtime_root = runtime_root
        self._goal_id = goal_id
        self._state_path = state_path
        self._write_class = write_class
        self._original_digest = text_digest(original_text)
        self._projector = projector
        self._directory = (
            partition_directory(runtime_root, goal_id, TODO_PARTITION)
            if enabled and runtime_root is not None
            else None
        )
        self._seq: int | None = None
        self._entry_id: str | None = None
        self._event_id: str | None = None
        self.outcome = CaptureOutcome(partition=TODO_PARTITION if enabled else None)

    @classmethod
    def begin(
        cls,
        *,
        enabled: bool,
        runtime_root: Path | None,
        goal_id: str,
        state_path: Path | None,
        write_class: str,
        original_text: str,
        projector: TodoPartitionProjector | None,
    ) -> TodoPartitionCapture:
        """``projector`` maps active-state text to the todos partition projection.

        It is injected so this module stays free of the Markdown parser; the
        adapter supplies the production projector.
        """

        return cls(
            enabled=enabled,
            runtime_root=runtime_root,
            goal_id=goal_id,
            state_path=state_path,
            write_class=write_class,
            original_text=original_text,
            projector=projector,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled and self._directory is not None

    def skip(self, reason: str) -> None:
        """Record why this writer deliberately did not open a transaction."""

        if self.enabled and self.outcome.entry_id is None:
            self.outcome.skipped_reason = reason

    def _project(self, state_text: str) -> dict[str, Any]:
        if self._projector is None:
            raise OutboxError("outbox_prepare_failed", "a todo partition projector is required")
        projection = self._projector(state_text)
        if set(projection) != {"handoff_mode", "todos"}:
            raise OutboxError("outbox_prepare_failed", "projector must return {handoff_mode, todos}")
        return projection

    def _fail(self, reason_code: str, error: BaseException) -> None:
        self.outcome.failure = {
            "reason_code": reason_code,
            "error_class": error.__class__.__name__,
        }

    def prepare(self, new_text: str, *, event_id: str | None = None) -> None:
        """Record the prepared entry for the bytes about to be written.

        For the state-event-log branch pass ``new_text=original`` plus the
        event id; the projection is then recorded by ``committed`` after the
        append, still inside the same lock.
        """

        if not self.enabled or self._directory is None or self._runtime_root is None:
            self.outcome.skipped_reason = "shadow_disabled"
            return
        try:
            if event_id is None:
                projection = self._project(new_text)
                digest = partition_digest(projection)
                if digest == latest_partition_digest(self._directory):
                    self.outcome.skipped_reason = "partition_unchanged"
                    return
                source_ref = text_digest(new_text)
                bytes_digest: str | None = source_ref
                source_kind = SOURCE_MARKDOWN
            else:
                projection = None
                digest = None
                bytes_digest = None
                source_kind = SOURCE_STATE_EVENT_LOG
                source_ref = f"event:{event_id}"
            seq = next_seq(self._directory)
            entry_id = entry_identity(
                goal_id=self._goal_id,
                partition=TODO_PARTITION,
                seq=seq,
                source_ref=source_ref,
            )
            record = _entry_record(
                goal_id=self._goal_id,
                partition=TODO_PARTITION,
                seq=seq,
                entry_id=entry_id,
                writer=_writer(
                    self._write_class,
                    runtime=WRITER_RUNTIME_PYTHON,
                    operation_id=event_id,
                ),
                source={
                    "kind": source_kind,
                    "previous_bytes_digest": self._original_digest,
                    "bytes_digest": bytes_digest,
                    "lease": None,
                    "event_id": event_id,
                },
                source_root_digest=runtime_root_digest(self._runtime_root),
                projection=projection,
                digest=digest,
            )
            durable_write_json(
                self._directory / entry_file_name(seq, entry_id, "prepared"),
                record,
            )
        except Exception as error:  # noqa: BLE001 - the primary write must proceed
            self._fail("outbox_prepare_failed", error)
            return
        self._seq = seq
        self._entry_id = entry_id
        self._event_id = event_id
        self.outcome.entry_id = entry_id
        self.outcome.seq = seq
        self.outcome.partition_digest = digest
        self.outcome.source_bytes_digest = bytes_digest

    def committed(self, *, projection_from_disk: bool = False) -> None:
        """Mark the prepared entry committed after the primary write returned."""

        if self._seq is None or self._entry_id is None or self._directory is None:
            return
        if self.outcome.failure is not None:
            return
        marker: dict[str, Any] = {
            "schema_version": OUTBOX_COMMIT_SCHEMA,
            "entry_id": self._entry_id,
            "committed_at": utc_now_text(),
        }
        try:
            if projection_from_disk:
                if self._state_path is None:
                    raise OutboxError("outbox_commit_marker_failed", "state path is required")
                projection = self._project(self._state_path.read_text(encoding="utf-8"))
                digest = partition_digest(projection)
                if digest == latest_partition_digest(self._directory):
                    # The event changed nothing the shadow compares; retire the
                    # prepared entry so no crash-window resolution is needed.
                    (self._directory / entry_file_name(self._seq, self._entry_id, "prepared")).unlink(
                        missing_ok=True
                    )
                    self.outcome.entry_id = None
                    self.outcome.seq = None
                    self.outcome.skipped_reason = "partition_unchanged"
                    return
                marker["projection"] = canonical_value(projection)
                marker["partition_digest"] = digest
                self.outcome.partition_digest = digest
            durable_write_json(
                self._directory / entry_file_name(self._seq, self._entry_id, "committed"),
                marker,
            )
        except Exception as error:  # noqa: BLE001 - the primary write already landed
            self._fail("outbox_commit_marker_failed", error)


SourceProbe = Callable[[OutboxEntry], str]
"""Return ``committed``, ``abandoned`` or ``unproved`` for a prepared-only entry."""


_LEASE_FENCE_KEYS = ("version", "lease_epoch", "status", "updated_at")


def _resolve_markdown_source(source: Mapping[str, Any], reader: Callable[[], str]) -> str:
    current_digest = text_digest(reader())
    if current_digest == source.get("bytes_digest"):
        return "committed"
    if current_digest == source.get("previous_bytes_digest"):
        return "abandoned"
    return "unproved"


def _lease_matches(current: Mapping[str, Any] | None, expected: Mapping[str, Any]) -> bool:
    if current is None or not expected:
        return False
    return all(current.get(key) == expected.get(key) for key in _LEASE_FENCE_KEYS)


def _resolve_lease_source(
    source: Mapping[str, Any],
    reader: Callable[[str], dict[str, Any] | None],
) -> str:
    planned = _as_object(source.get("lease"))
    if not planned:
        return "unproved"
    current = reader(str(planned.get("todo_id") or ""))
    if _lease_matches(current, planned):
        return "committed"
    previous = _as_object(source.get("previous_lease"))
    if (not previous and current is None) or _lease_matches(current, previous):
        return "abandoned"
    return "unproved"


def _resolve_event_source(source: Mapping[str, Any], reader: Callable[[str], bool]) -> str:
    event_id = source.get("event_id")
    if isinstance(event_id, str) and event_id and reader(event_id):
        # The append landed but the projection was never recorded; only a
        # fresh full-partition capture can say what the state now is.
        return "unproved"
    return "abandoned"


def resolve_prepared_only_entry(
    entry: OutboxEntry,
    *,
    markdown_text_reader: Callable[[], str] | None,
    lease_record_reader: Callable[[str], dict[str, Any] | None] | None,
    event_presence_reader: Callable[[str], bool] | None,
) -> str:
    """Decide what a prepared entry without a committed marker means.

    The caller must hold the partition's primary lock (or have proven it free),
    otherwise the source may still be mid-write.
    """

    source = _as_object(entry.prepared.get("source"))
    kind = source.get("kind")
    if kind == SOURCE_MARKDOWN and markdown_text_reader is not None:
        return _resolve_markdown_source(source, markdown_text_reader)
    if kind == SOURCE_TASK_LEASE and lease_record_reader is not None:
        return _resolve_lease_source(source, lease_record_reader)
    if kind == SOURCE_STATE_EVENT_LOG and event_presence_reader is not None:
        return _resolve_event_source(source, event_presence_reader)
    return "unproved"


def entries_by_partition(runtime_root: Path, goal_id: str) -> dict[str, list[OutboxEntry]]:
    return {
        partition: list_entries(partition_directory(runtime_root, goal_id, partition))
        for partition in PARTITIONS
    }


def outbox_summary(runtime_root: Path, goal_id: str) -> dict[str, Any]:
    """Counts per partition for operator readback; never raises on an empty outbox."""

    summary: dict[str, Any] = {}
    for partition in PARTITIONS:
        directory = partition_directory(runtime_root, goal_id, partition)
        try:
            entries = list_entries(directory)
            cursor = read_cursor(directory)
            invalid: str | None = None
        except OutboxError as error:
            entries, cursor, invalid = [], None, error.reason_code
        summary[partition] = {
            "committed_pending": sum(1 for entry in entries if entry.is_committed),
            "prepared_only": sum(1 for entry in entries if not entry.is_committed),
            "retired_residue": len(retired_residue(directory)),
            "next_seq": (max((entry.seq for entry in entries), default=0) if entries else 0),
            "cursor_last_seq": int(cursor.get("last_seq") or 0) if cursor else None,
            "cursor_last_entry_id": cursor.get("last_entry_id") if cursor else None,
            "invalid": invalid,
        }
    return summary


def remove_entry_files(entry: OutboxEntry) -> None:
    entry.prepared_path.unlink(missing_ok=True)
    if entry.committed_path is not None:
        entry.committed_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class SeedSource:
    """A full-partition snapshot taken under the partition's primary lock."""

    partition: str
    projection: dict[str, Any]
    source_bytes_digest: str | None = None
    extra_source: dict[str, Any] = field(default_factory=dict)


def write_seed_entry(
    *,
    runtime_root: Path,
    goal_id: str,
    seed: SeedSource,
    write_class: str = "seed",
) -> OutboxEntry:
    """Write a committed full-partition entry (seed or reseed); caller holds the lock."""

    directory = partition_directory(runtime_root, goal_id, seed.partition)
    digest = partition_digest(seed.projection)
    seq = next_seq(directory)
    source_ref: str = seed.source_bytes_digest if seed.source_bytes_digest else f"seed:{digest}"
    entry_id = entry_identity(goal_id=goal_id, partition=seed.partition, seq=seq, source_ref=source_ref)
    record = _entry_record(
        goal_id=goal_id,
        partition=seed.partition,
        seq=seq,
        entry_id=entry_id,
        writer=_writer(write_class, runtime=WRITER_RUNTIME_PYTHON, operation_id=None),
        source={
            "kind": SOURCE_MARKDOWN if seed.partition == TODO_PARTITION else SOURCE_TASK_LEASE,
            "previous_bytes_digest": None,
            "bytes_digest": seed.source_bytes_digest,
            "lease": None,
            "event_id": None,
            **dict(seed.extra_source),
        },
        source_root_digest=runtime_root_digest(runtime_root),
        projection=seed.projection,
        digest=digest,
    )
    prepared_path = directory / entry_file_name(seq, entry_id, "prepared")
    committed_path = directory / entry_file_name(seq, entry_id, "committed")
    durable_write_json(prepared_path, record)
    marker = {
        "schema_version": OUTBOX_COMMIT_SCHEMA,
        "entry_id": entry_id,
        "committed_at": utc_now_text(),
    }
    durable_write_json(committed_path, marker)
    return OutboxEntry(
        partition=seed.partition,
        seq=seq,
        entry_id=entry_id,
        prepared_path=prepared_path,
        committed_path=committed_path,
        prepared=record,
        committed=marker,
    )


def lease_seed_source(runtime_root: Path, goal_id: str) -> SeedSource:
    """Snapshot the lease partition from disk; caller holds the lease lock."""

    records = read_lease_records(lease_directory(runtime_root, goal_id))
    try:
        projection = lease_partition_projection(records, goal_id=goal_id)
    except ProjectionValueError as error:
        raise OutboxError("outbox_prepare_failed", str(error)) from error
    return SeedSource(partition=LEASE_PARTITION, projection=projection)


def iter_committed(entries: Iterable[OutboxEntry]) -> list[OutboxEntry]:
    return [entry for entry in entries if entry.is_committed]


__all__ = [
    "DRAIN_CURSOR_SCHEMA",
    "OUTBOX_COMMIT_SCHEMA",
    "OUTBOX_ENTRY_SCHEMA",
    "SOURCE_MARKDOWN",
    "SOURCE_STATE_EVENT_LOG",
    "SOURCE_TASK_LEASE",
    "CaptureOutcome",
    "OutboxEntry",
    "OutboxError",
    "SeedSource",
    "TodoPartitionCapture",
    "TodoPartitionProjector",
    "compact_lease_projection",
    "drain_lock_target",
    "durable_write_json",
    "entries_by_partition",
    "entry_file_name",
    "entry_identity",
    "iter_committed",
    "latest_partition_digest",
    "lease_directory",
    "lease_seed_source",
    "list_entries",
    "next_seq",
    "outbox_root",
    "outbox_summary",
    "partition_directory",
    "read_cursor",
    "read_lease_records",
    "reclaim_retired_residue",
    "record_source_ref",
    "remove_entry_files",
    "resolve_prepared_only_entry",
    "retired_residue",
    "runtime_root_digest",
    "utc_now_text",
    "write_cursor",
    "write_seed_entry",
]

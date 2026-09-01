"""The file-backed coordination provider: storage-only CAS with typed outcomes.

RFC section 6.2: ``load() -> (head | None, provider_generation)`` and
``compare_and_put(expected_provider_generation, head) -> applied | conflict |
ambiguous | failed``. The provider never interprets the head; crash windows
must map onto ``ambiguous`` (never a silent success or a lost document).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from loopx.control_plane.coordination.file_provider import (
    FileCoordinationProvider,
    ProviderProtocolError,
)


def head(revision: int = 0) -> dict:
    return {
        "schema_version": "loopx_coordination_head_v1",
        "goal_id": "goal-a",
        "handoff_mode": "hard_lease",
        "store_binding": "test:store",
        "authority_revision": revision,
        "coordination": {"todos": {}, "leases": {}},
        "receipt_index": {},
        "receipt_retention": {"mode": "retain_all_v0"},
    }


@pytest.fixture
def provider(tmp_path) -> FileCoordinationProvider:
    return FileCoordinationProvider(tmp_path / "coordination", "goal-a")


def test_load_uninitialized_returns_none_zero(provider) -> None:
    assert provider.load() == (None, 0)


def test_store_identity_is_stable_and_strictly_formatted(provider) -> None:
    identity = provider.store_identity()
    assert identity.startswith("file:")
    assert len(identity) == len("file:") + 32
    assert set(identity.removeprefix("file:")) <= set("0123456789abcdef")
    assert provider.store_identity() == identity


@pytest.mark.parametrize(
    "invalid_identity",
    [
        b"",
        b"f",
        b"file:0123456789abcdef0123456789abcde",
        b"file:0123456789abcdef0123456789abcdef\n",
        b"file:0123456789ABCDEF0123456789ABCDEF",
        b"nokv:0123456789abcdef0123456789abcdef",
        b"file:\xff",
    ],
)
def test_store_identity_rejects_invalid_persisted_bytes(
    tmp_path, invalid_identity
) -> None:
    directory = tmp_path / "coordination"
    directory.mkdir()
    (directory / "store-identity").write_bytes(invalid_identity)
    provider = FileCoordinationProvider(directory, "goal-a")
    with pytest.raises(ProviderProtocolError, match="32 lowercase hex"):
        provider.store_identity()


def test_concurrent_store_identity_creation_publishes_one_complete_value(
    tmp_path, monkeypatch
) -> None:
    import loopx.control_plane.coordination.file_provider as module

    directory = tmp_path / "coordination"
    providers = [
        FileCoordinationProvider(directory, "goal-a"),
        FileCoordinationProvider(directory, "goal-b"),
    ]
    entered_replace = threading.Event()
    allow_replace = threading.Event()
    real_replace = module._replace_document

    def blocked_identity_replace(source: Path, target: Path) -> None:
        if target.name == "store-identity":
            entered_replace.set()
            assert allow_replace.wait(timeout=5)
        real_replace(source, target)

    monkeypatch.setattr(module, "_replace_document", blocked_identity_replace)
    results: list[str] = []
    failures: list[BaseException] = []

    def create_identity(provider: FileCoordinationProvider) -> None:
        try:
            results.append(provider.store_identity())
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    first = threading.Thread(target=create_identity, args=(providers[0],))
    second = threading.Thread(target=create_identity, args=(providers[1],))
    first.start()
    assert entered_replace.wait(timeout=5)
    second.start()
    assert second.is_alive()
    allow_replace.set()
    first.join(timeout=5)
    second.join(timeout=5)
    monkeypatch.undo()

    assert not failures
    assert len(results) == 2
    assert results[0] == results[1]
    assert len(results[0]) == len("file:") + 32


def test_store_identity_short_writes_are_continued(tmp_path, monkeypatch) -> None:
    import loopx.control_plane.coordination.file_provider as module

    provider = FileCoordinationProvider(tmp_path / "coordination", "goal-a")
    real_write = module.os.write
    chunks: list[int] = []

    def short_write(descriptor, view):
        chunk = bytes(view)[:3]
        chunks.append(len(chunk))
        return real_write(descriptor, chunk)

    monkeypatch.setattr(module.os, "write", short_write)
    identity = provider.store_identity()
    monkeypatch.undo()
    assert len(chunks) > 1
    assert provider.store_identity() == identity
    assert (tmp_path / "coordination" / "store-identity").read_text() == identity


def test_store_identity_crash_before_rename_retries_cleanly(
    tmp_path, monkeypatch
) -> None:
    import loopx.control_plane.coordination.file_provider as module

    directory = tmp_path / "coordination"
    provider = FileCoordinationProvider(directory, "goal-a")

    def crash_before_identity_rename(_source: Path, target: Path) -> None:
        assert target.name == "store-identity"
        raise OSError("simulated crash before identity rename")

    monkeypatch.setattr(module, "_replace_document", crash_before_identity_rename)
    with pytest.raises(ProviderProtocolError, match="store identity is unavailable"):
        provider.store_identity()
    assert not (directory / "store-identity").exists()
    assert not list(directory.glob("store-identity.tmp-*"))

    monkeypatch.undo()
    identity = provider.store_identity()
    assert provider.store_identity() == identity


def test_store_identity_directory_fsync_failure_converges_on_retry(
    tmp_path, monkeypatch
) -> None:
    import loopx.control_plane.coordination.file_provider as module

    provider = FileCoordinationProvider(tmp_path / "coordination", "goal-a")
    real_fsync_directory = module._fsync_directory
    calls = 0

    def fail_first_directory_fsync(directory: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated identity directory fsync failure")
        real_fsync_directory(directory)

    monkeypatch.setattr(module, "_fsync_directory", fail_first_directory_fsync)
    with pytest.raises(ProviderProtocolError, match="store identity is unavailable"):
        provider.store_identity()
    identity = provider.store_identity()
    monkeypatch.undo()
    assert calls == 2
    assert provider.store_identity() == identity


def test_create_replace_conflict_cycle(provider) -> None:
    created = provider.compare_and_put(0, head())
    assert created == {"result": "applied", "provider_generation": 1}
    loaded, generation = provider.load()
    assert loaded == head() and generation == 1

    replaced = provider.compare_and_put(1, head(1))
    assert replaced == {"result": "applied", "provider_generation": 2}

    stale = provider.compare_and_put(1, head(9))
    assert stale == {"result": "conflict", "current_provider_generation": 2}
    lost_create = provider.compare_and_put(0, head())
    assert lost_create == {"result": "conflict", "current_provider_generation": 2}
    assert provider.load() == (head(1), 2)


def test_two_handles_share_one_document(tmp_path) -> None:
    a = FileCoordinationProvider(tmp_path / "c", "goal-a")
    b = FileCoordinationProvider(tmp_path / "c", "goal-a")
    assert a.compare_and_put(0, head())["result"] == "applied"
    assert b.load() == (head(), 1)
    assert b.compare_and_put(1, head(1))["result"] == "applied"
    assert a.compare_and_put(1, head(2))["result"] == "conflict"


def test_goals_are_isolated_documents(tmp_path) -> None:
    a = FileCoordinationProvider(tmp_path / "c", "goal-a")
    b = FileCoordinationProvider(tmp_path / "c", "goal-b")
    assert a.compare_and_put(0, head())["result"] == "applied"
    assert b.load() == (None, 0)


def test_concurrent_cas_from_same_generation_has_one_winner(provider) -> None:
    assert provider.compare_and_put(0, head())["result"] == "applied"
    barrier = threading.Barrier(2)
    results = {}

    def racer(name: str, revision: int) -> None:
        barrier.wait()
        results[name] = provider.compare_and_put(1, head(revision))

    threads = [
        threading.Thread(target=racer, args=("a", 1)),
        threading.Thread(target=racer, args=("b", 2)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    outcomes = sorted(result["result"] for result in results.values())
    assert outcomes in (["applied", "conflict"], ["ambiguous", "applied"]), results
    loaded, generation = provider.load()
    assert generation == 2
    assert loaded in (head(1), head(2))


def test_bool_disguised_generations_fail_closed(provider, tmp_path) -> None:
    """The provider generation is typed state exactly like revisions and
    epochs: JSON ``true`` must not load as generation 1, and a bool expected
    generation must not hit the CAS and silently repair a corrupt envelope
    into a valid lineage."""

    for expected in (True, False):
        outcome = provider.compare_and_put(expected, head())
        assert outcome["result"] == "failed"
        assert "non-negative integer" in outcome["error"]
    assert provider.compare_and_put(0, head())["result"] == "applied"
    document = next((tmp_path / "coordination").glob("*.json"))
    body = document.read_text(encoding="utf-8")
    document.write_text(
        body.replace('"provider_generation":1', '"provider_generation":true'),
        encoding="utf-8",
    )
    with pytest.raises(ProviderProtocolError, match="v0 contract"):
        provider.load()
    with pytest.raises(ProviderProtocolError, match="v0 contract"):
        provider.compare_and_put(1, head(1))


def test_corrupt_document_fails_closed(provider, tmp_path) -> None:
    assert provider.compare_and_put(0, head())["result"] == "applied"
    document = next((tmp_path / "coordination").glob("*.json"))
    document.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProviderProtocolError):
        provider.load()
    with pytest.raises(ProviderProtocolError):
        provider.compare_and_put(1, head(1))


def test_crash_after_temp_write_before_rename_changes_nothing(
    provider, monkeypatch
) -> None:
    # Faults are injected through the provider's own commit seam, not the
    # global os attributes: loopx.file_lock's Windows holder sidecar also
    # calls os.replace, and a global patch would crash lock bookkeeping
    # instead of the document commit under test.
    assert provider.compare_and_put(0, head())["result"] == "applied"
    import loopx.control_plane.coordination.file_provider as module

    def crash(_source, _target):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(module, "_replace_document", crash)
    outcome = provider.compare_and_put(1, head(1))
    assert outcome["result"] == "ambiguous"
    monkeypatch.undo()
    assert provider.load() == (head(), 1)
    retry = provider.compare_and_put(1, head(1))
    assert retry == {"result": "applied", "provider_generation": 2}


def test_lost_response_after_rename_is_recoverable_by_reload(
    provider, monkeypatch
) -> None:
    assert provider.compare_and_put(0, head())["result"] == "applied"
    import loopx.control_plane.coordination.file_provider as module

    real_replace = module._replace_document

    def replace_then_crash(source, target):
        real_replace(source, target)
        raise OSError("simulated lost response after rename")

    monkeypatch.setattr(module, "_replace_document", replace_then_crash)
    outcome = provider.compare_and_put(1, head(1))
    assert outcome["result"] == "ambiguous"
    monkeypatch.undo()
    assert provider.load() == (head(1), 2)


def test_document_bytes_are_canonical_json(provider, tmp_path) -> None:
    provider.compare_and_put(0, head())
    document = next((tmp_path / "coordination").glob("*.json"))
    envelope = json.loads(document.read_text(encoding="utf-8"))
    assert set(envelope) == {"provider_generation", "head"}
    assert envelope["provider_generation"] == 1
    assert envelope["head"] == head()


def test_short_writes_are_continued_until_complete(
    provider, tmp_path, monkeypatch
) -> None:
    """os.write may write fewer bytes than asked; the commit sequence must
    continue until every byte landed, or a truncated document could be
    reported as applied and fail to parse on the next load."""

    import loopx.control_plane.coordination.file_provider as module

    real_write = module.os.write
    chunks = []

    def short_write(descriptor, view):
        chunk = bytes(view)[:7]
        chunks.append(len(chunk))
        return real_write(descriptor, chunk)

    monkeypatch.setattr(module.os, "write", short_write)
    outcome = provider.compare_and_put(0, head())
    monkeypatch.undo()
    assert outcome == {"result": "applied", "provider_generation": 1}
    assert len(chunks) > 1
    assert provider.load() == (head(), 1)


def test_write_fault_after_short_write_is_ambiguous_and_document_intact(
    provider, tmp_path, monkeypatch
) -> None:
    """A storage fault midway through the write must never surface as
    applied: the document keeps its previous readable state and the verdict
    is ambiguous, which the authority resolves by reload."""

    import loopx.control_plane.coordination.file_provider as module

    assert provider.compare_and_put(0, head())["result"] == "applied"
    real_write = module.os.write
    state = {"calls": 0}

    def failing_write(descriptor, view):
        state["calls"] += 1
        if state["calls"] == 1:
            return real_write(descriptor, bytes(view)[: max(1, len(view) // 2)])
        raise OSError("simulated storage fault after a short write")

    monkeypatch.setattr(module.os, "write", failing_write)
    outcome = provider.compare_and_put(1, head(1))
    monkeypatch.undo()
    assert outcome == {"result": "ambiguous"}
    assert provider.load() == (head(), 1)
    assert not list((tmp_path / "coordination").glob("*.tmp-*"))


def test_commit_sequence_fsyncs_file_before_rename_and_directory_after(
    provider, monkeypatch
) -> None:
    import loopx.control_plane.coordination.file_provider as module

    events = []
    real_file_fsync = module._fsync_file
    real_replace = module._replace_document
    real_directory_fsync = module._fsync_directory

    def recording_file_fsync(descriptor):
        events.append("fsync")
        return real_file_fsync(descriptor)

    def recording_replace(source, target):
        events.append("replace")
        return real_replace(source, target)

    def recording_directory_fsync(directory):
        events.append("dir_fsync")
        return real_directory_fsync(directory)

    monkeypatch.setattr(module, "_fsync_file", recording_file_fsync)
    monkeypatch.setattr(module, "_replace_document", recording_replace)
    monkeypatch.setattr(module, "_fsync_directory", recording_directory_fsync)
    assert provider.compare_and_put(0, head())["result"] == "applied"
    monkeypatch.undo()
    assert events == ["fsync", "replace", "dir_fsync"]


def test_directory_fsync_fault_is_ambiguous_not_applied(
    provider, monkeypatch
) -> None:
    """Until the parent directory entry is flushed the rename is not provably
    durable, so a fault there must stay ambiguous instead of applied."""

    import loopx.control_plane.coordination.file_provider as module

    def failing_directory_fsync(directory):
        raise OSError("simulated directory fsync fault")

    monkeypatch.setattr(module, "_fsync_directory", failing_directory_fsync)
    outcome = provider.compare_and_put(0, head())
    monkeypatch.undo()
    assert outcome == {"result": "ambiguous"}
    # The rename itself landed; reload recovers the write, which is exactly
    # the ambiguous contract.
    assert provider.load() == (head(), 1)


def test_lock_timeout_is_typed_failed_without_write(tmp_path) -> None:
    from loopx.file_lock import exclusive_file_lock

    directory = tmp_path / "coordination"
    provider = FileCoordinationProvider(
        directory, "goal-a", lock_timeout_seconds=0.05
    )
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / provider_document_name()):
        outcome = provider.compare_and_put(0, head())
    assert outcome["result"] == "failed"
    assert provider.load() == (None, 0)
    assert provider.compare_and_put(0, head())["result"] == "applied"


def provider_document_name() -> str:
    import hashlib

    digest = hashlib.sha256(b"goal-a").hexdigest()[:16]
    return f"coordination-head-{digest}.json"


def test_module_imports_without_fcntl() -> None:
    """The provider must stay importable on interpreters without ``fcntl``
    (Windows); platform locking belongs to ``loopx.file_lock``, the one lock
    owner with both backends."""

    import importlib
    import sys

    import loopx.control_plane.coordination.file_provider as module

    sentinel = object()
    saved = sys.modules.pop("fcntl", sentinel)
    sys.modules["fcntl"] = None  # type: ignore[assignment]
    try:
        reloaded = importlib.reload(module)
        assert hasattr(reloaded, "FileCoordinationProvider")
    finally:
        if saved is sentinel:
            sys.modules.pop("fcntl", None)
        else:
            sys.modules["fcntl"] = saved
        importlib.reload(module)


def test_unserializable_head_fails_typed_and_writes_nothing(
    provider, tmp_path
) -> None:
    """A head with no faithful strict-JSON form must surface as the typed
    ``failed`` verb (serialization runs before any write), never leak an
    exception through the seam or leave partial bytes behind."""

    for poison in ({"x": float("nan")}, {"x": object()}):
        outcome = provider.compare_and_put(0, poison)
        assert outcome["result"] == "failed"
        assert "serializable" in outcome["error"]
    assert provider.load() == (None, 0)
    assert not list((tmp_path / "coordination").glob("*.tmp-*"))
    assert provider.compare_and_put(0, head())["result"] == "applied"

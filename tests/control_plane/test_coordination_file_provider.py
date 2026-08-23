"""The file-backed coordination provider: storage-only CAS with typed outcomes.

RFC section 6.2: ``load() -> (head | None, provider_generation)`` and
``compare_and_put(expected_provider_generation, head) -> applied | conflict |
ambiguous | failed``. The provider never interprets the head; crash windows
must map onto ``ambiguous`` (never a silent success or a lost document).
"""

from __future__ import annotations

import json
import threading

import pytest

from loopx.control_plane.coordination.file_provider import (
    FileCoordinationProvider,
    ProviderProtocolError,
)


def head(revision: int = 0) -> dict:
    return {
        "schema_version": "loopx_coordination_head_v0",
        "goal_id": "goal-a",
        "handoff_mode": "hard_lease",
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
    assert provider.compare_and_put(0, head())["result"] == "applied"
    import loopx.control_plane.coordination.file_provider as module

    def crash(_source, _target):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(module.os, "replace", crash)
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

    real_replace = module.os.replace

    def replace_then_crash(source, target):
        real_replace(source, target)
        raise OSError("simulated lost response after rename")

    monkeypatch.setattr(module.os, "replace", replace_then_crash)
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

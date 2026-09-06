from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.coordination import local_authority_shadow_adapter as adapter
from loopx.control_plane.coordination import local_authority_shadow_outbox as outbox
from loopx.control_plane.coordination.local_authority_shadow_projection import (
    head_digest,
    partition_digest,
    text_digest,
)
from loopx.file_lock import exclusive_file_lock
from loopx.history import load_registry
from loopx.registry import find_registry_goal
from loopx.todos import add_goal_todo, list_goal_todos


GOAL_ID = "goal-drain"


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "---\n"
        f"goal_id: {GOAL_ID}\n"
        "handoff_mode: hard_lease\n"
        "updated_at: 2026-09-03T00:00:00+00:00\n"
        "---\n\n"
        "## Agent Todo\n\n",
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime_root),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state.name,
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["agent-a"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state, runtime_root


def _record_todo_write(
    registry: Path,
    state: Path,
    runtime_root: Path,
    text: str,
    *,
    mark_committed: bool = True,
    write_file: bool = True,
) -> outbox.TodoPartitionCapture:
    """Simulate a hooked writer: capture around one add_goal_todo write."""

    original = state.read_text(encoding="utf-8")
    goal = find_registry_goal(load_registry(registry), GOAL_ID)
    capture = outbox.TodoPartitionCapture.begin(
        enabled=True,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        state_path=state,
        write_class="todo_add",
        original_text=original,
        projector=adapter.todo_partition_projector(goal, state_path=state),
    )
    if write_file:
        result = add_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            role="agent",
            text=text,
            task_class="advancement_task",
        )
        assert result["ok"] is True
        new_text = state.read_text(encoding="utf-8")
    else:
        # The bytes the writer would have produced, without producing them.
        result = add_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            role="agent",
            text=text,
            task_class="advancement_task",
        )
        assert result["ok"] is True
        new_text = state.read_text(encoding="utf-8")
        state.write_text(original, encoding="utf-8")
    capture.prepare(new_text)
    assert capture.outcome.failure is None
    assert capture.outcome.entry_id is not None
    if mark_committed:
        capture.committed()
    return capture


def _drain(registry: Path, runtime_root: Path, **overrides: object) -> adapter.DrainResult:
    return adapter.drain_local_authority_shadow_outbox(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        **overrides,  # type: ignore[arg-type]
    )


def _todo_dir(runtime_root: Path) -> Path:
    return outbox.partition_directory(runtime_root, GOAL_ID, "todos")


def test_drain_delivers_each_committed_entry_once_in_order_and_verifies_readback(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    captures = [
        _record_todo_write(registry, state, runtime_root, f"Fact {index}") for index in range(3)
    ]
    assert [capture.outcome.seq for capture in captures] == [1, 2, 3]

    result = _drain(registry, runtime_root)

    assert result.ok is True
    assert result.outcome == "drained"
    assert result.config_enabled is False
    assert (result.delivered, result.replayed, result.no_op) == (3, 0, 0)
    assert result.pending_after == 0
    assert result.prepared_only_after == 0
    assert result.budget_exhausted is False
    assert result.candidate_readback_verified is True
    assert result.last_cursor == "3"
    assert (result.cursor_before, result.cursor_after, result.drained_count) == (None, "3", 3)
    payload = result.to_payload()
    assert payload["ok"] is True
    assert payload["drained_count"] == 3
    assert payload["cursor_after"] == "3"
    assert [item["outcome"] for item in result.entries] == ["delivered"] * 3
    assert [item["cursor"] for item in result.entries] == ["1", "2", "3"]
    assert [item["entry_id"] for item in result.entries] == [
        capture.outcome.entry_id for capture in captures
    ]
    assert result.store_identity is not None
    assert result.store_identity.startswith("file:")
    assert list(_todo_dir(runtime_root).iterdir()) == [_todo_dir(runtime_root) / "drain-cursor.json"]
    cursor = outbox.read_cursor(_todo_dir(runtime_root))
    assert cursor is not None
    assert cursor["last_seq"] == 3
    assert cursor["last_entry_id"] == captures[-1].outcome.entry_id
    assert cursor["last_partition_digest"] == captures[-1].outcome.partition_digest

    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=10)
    assert view["status"] == "loaded"
    head = view["head"]
    assert head["schema_version"] == "loopx_coordination_runtime_shadow_projection_v0"
    assert head["partitions"]["todos"] == {
        "seq": 3,
        "partition_digest": captures[-1].outcome.partition_digest,
    }
    assert head["partitions"]["leases"] is None
    listed = list_goal_todos(registry_path=registry, goal_id=GOAL_ID, runtime_root_arg=str(runtime_root))
    assert [todo["todo_id"] for todo in head["todos"]] == sorted(
        todo["todo_id"] for todo in listed["todos"]
    )
    assert view["head_digest"] == head_digest(head) == result.head_digest
    assert [tx["operation_id"] for tx in view["scan"]["transactions"]] == [
        capture.outcome.entry_id for capture in captures
    ]
    receipts = [tx["receipts"][0] for tx in view["scan"]["transactions"]]
    assert all(receipt["source_transaction_correlated"] is True for receipt in receipts)
    assert all(receipt["durable_source_outbox"] is True for receipt in receipts)
    assert all(receipt["parity_verdict"] == "not_evaluated" for receipt in receipts)
    assert [receipt["source_bytes_digest"] for receipt in receipts] == [
        capture.outcome.source_bytes_digest for capture in captures
    ]
    assert str(runtime_root) not in json.dumps(view)

    again = _drain(registry, runtime_root)
    assert again.outcome == "nothing_pending"
    assert again.ok is True


def test_drain_replays_when_store_committed_but_cursor_was_not_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _record_todo_write(registry, state, runtime_root, "Crash after store commit")

    def crash(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash before the drain cursor landed")

    monkeypatch.setattr(outbox, "write_cursor", crash)
    first = _drain(registry, runtime_root)
    assert first.outcome == "stopped"
    assert first.reason_code == "shadow_drain_failed"
    assert first.pending_after == 1
    monkeypatch.undo()

    second = _drain(registry, runtime_root)
    assert second.ok is True
    assert (second.delivered, second.replayed) == (0, 1)
    assert second.entries[0]["entry_id"] == capture.outcome.entry_id
    assert second.entries[0]["cursor"] == "1"
    assert second.pending_after == 0
    assert second.candidate_readback_verified is True
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=10)
    assert len(view["scan"]["transactions"]) == 1


def test_drain_defers_when_another_drainer_holds_the_lock(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    _record_todo_write(registry, state, runtime_root, "Pending behind a drainer")
    with exclusive_file_lock(
        outbox.drain_lock_target(runtime_root, GOAL_ID), timeout_seconds=1.0, operation="test_hold"
    ):
        result = _drain(registry, runtime_root, lock_timeout_seconds=0.05)
    assert result.outcome == "drain_deferred"
    assert result.reason_code == "drain_lock_busy"
    assert result.ok is False
    assert result.pending_after == 1
    assert not (runtime_root / "authority-shadow" / "file").exists()


def test_drain_batch_is_bounded_and_reports_what_it_left(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    for index in range(3):
        _record_todo_write(registry, state, runtime_root, f"Bounded {index}")

    first = _drain(registry, runtime_root, max_entries=2)
    assert first.outcome == "drained"
    assert first.ok is True
    assert first.delivered == 2
    assert first.budget_exhausted is True
    assert first.pending_after == 1
    assert first.candidate_readback_verified is True

    second = _drain(registry, runtime_root)
    assert second.delivered == 1
    assert second.pending_after == 0
    assert (second.cursor_before, second.cursor_after) == ("2", "3")
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID)
    assert view["cursor"] == "3"
    assert view["head"]["partitions"]["todos"]["seq"] == 3


def test_drain_stops_in_order_when_the_store_boundary_misbehaves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    for index in range(3):
        _record_todo_write(registry, state, runtime_root, f"Ordered {index}")
    real = adapter.effect_runtime_result
    calls: list[str] = []

    def flaky(method: str, params: object, **kwargs: object) -> object:
        calls.append(method)
        if method == "coordination.runtime_shadow.commit_entry" and len(calls) == 2:
            return {"schema_version": "garbage"}
        return real(method, params, **kwargs)

    monkeypatch.setattr(adapter, "effect_runtime_result", flaky)
    result = _drain(registry, runtime_root)
    assert result.outcome == "stopped"
    assert result.delivered == 1
    assert result.stopped_at is not None
    assert result.stopped_at["seq"] == 2
    assert result.stopped_at["reason_code"] == "shadow_commit_entry_result_invalid"
    assert result.pending_after == 2
    assert [entry.seq for entry in outbox.list_entries(_todo_dir(runtime_root))] == [2, 3]
    monkeypatch.undo()

    recovered = _drain(registry, runtime_root)
    assert recovered.delivered == 2
    assert recovered.pending_after == 0


def test_prepared_only_entries_resolve_only_under_a_free_primary_lock(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    proven = _record_todo_write(registry, state, runtime_root, "Marker lost after write", mark_committed=False)
    with exclusive_file_lock(state, timeout_seconds=1.0, operation="writer_in_flight"):
        busy = _drain(registry, runtime_root)
    assert busy.outcome == "drained"
    assert busy.in_flight_partitions == ["todos"]
    assert busy.prepared_only_after == 1
    assert busy.delivered == 0

    result = _drain(registry, runtime_root)
    assert result.ok is True
    assert result.delivered == 1
    assert result.no_op == 0
    assert result.entries[0]["resolution"] == "committed_proven_by_readback"
    assert result.entries[0]["entry_id"] == proven.outcome.entry_id
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=5)
    assert view["head"]["partitions"]["todos"]["partition_digest"] == proven.outcome.partition_digest
    receipt = view["scan"]["transactions"][0]["receipts"][0]
    assert receipt["resolution"] == "committed_proven_by_readback"

    abandoned = _record_todo_write(
        registry, state, runtime_root, "Never landed", mark_committed=False, write_file=False
    )
    result = _drain(registry, runtime_root)
    assert result.delivered == 1
    assert result.no_op == 1
    assert result.entries[0]["resolution"] == "abandoned"
    assert result.entries[0]["entry_id"] == abandoned.outcome.entry_id
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=5)
    assert view["cursor"] == "2"
    assert view["head"]["partitions"]["todos"]["seq"] == 1
    assert view["scan"]["transactions"][1]["events"][0]["kind"] == "source_transaction_abandoned"


def test_unexplained_prepared_only_entry_triggers_reseed_under_the_primary_lock(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    _record_todo_write(registry, state, runtime_root, "Baseline")
    assert _drain(registry, runtime_root).delivered == 1
    stale = _record_todo_write(registry, state, runtime_root, "Half-recorded", mark_committed=False)
    # An unhooked writer edits the file after the crash: neither digest matches.
    state.write_text(
        state.read_text(encoding="utf-8") + "\n- [ ] (agent) foreign edit <!-- todo_id: todo_0000000000ff -->\n",
        encoding="utf-8",
    )

    result = _drain(registry, runtime_root)

    assert result.ok is True
    assert result.reseeded == 1
    assert result.no_op == 1
    assert [item["resolution"] for item in result.entries] == ["unproved", "seed"]
    assert result.entries[0]["entry_id"] == stale.outcome.entry_id
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=10)
    kinds = [tx["events"][0]["kind"] for tx in view["scan"]["transactions"]]
    assert kinds == ["source_transaction_delivered", "source_transaction_unproved", "partition_seeded"]
    listed = list_goal_todos(registry_path=registry, goal_id=GOAL_ID, runtime_root_arg=str(runtime_root))
    assert [todo["todo_id"] for todo in view["head"]["todos"]] == sorted(
        todo["todo_id"] for todo in listed["todos"]
    )
    assert len(view["head"]["todos"]) == 3
    assert view["head"]["partitions"]["todos"]["seq"] == 3
    seed_receipt = view["scan"]["transactions"][2]["receipts"][0]
    assert seed_receipt["write_class"] == "reseed_after_crash_gap"
    assert seed_receipt["source_bytes_digest"] == text_digest(state.read_text(encoding="utf-8"))


def test_lease_partition_entries_retain_complete_records_at_drain(tmp_path: Path) -> None:
    registry, _state, runtime_root = _fixture(tmp_path)
    directory = outbox.partition_directory(runtime_root, GOAL_ID, "leases")
    record = {
        "goal_id": GOAL_ID,
        "todo_id": "todo_00000000000a",
        "owner": "agent-a",
        "idempotency_key": "k1",
        "write_scopes": ["loopx/**"],
        "version": 2,
        "lease_epoch": 1,
        "acquired_at": "2026-09-03T00:00:00+00:00",
        "updated_at": "2026-09-03T00:01:00+00:00",
        "expires_at": "2026-09-03T00:31:00+00:00",
        "released_at": None,
        "status": "active",
        "lease_path": "/should/never/be/compared",
        "acquire_ttl_seconds": 1800,
    }
    bytes_digest = text_digest(json.dumps(record, indent=2) + "\n")
    entry_id = outbox.entry_identity(goal_id=GOAL_ID, partition="leases", seq=1, source_ref=bytes_digest)
    outbox.durable_write_json(
        directory / outbox.entry_file_name(1, entry_id, "prepared"),
        {
            "schema_version": outbox.OUTBOX_ENTRY_SCHEMA,
            "goal_id": GOAL_ID,
            "partition": "leases",
            "seq": 1,
            "entry_id": entry_id,
            "writer": {"runtime": "typescript", "write_class": "task_lease_acquire", "operation_id": "op-1"},
            "source": {
                "kind": "task_lease_record",
                "previous_bytes_digest": None,
                "bytes_digest": bytes_digest,
                "lease": {"todo_id": record["todo_id"], "version": 2, "lease_epoch": 1, "status": "active", "updated_at": record["updated_at"]},
                "previous_lease": None,
                "event_id": None,
            },
            "source_root_digest": outbox.runtime_root_digest(runtime_root),
            "projection": {"leases": [{"file_stem": record["todo_id"], "record": record}]},
            "partition_digest": None,
            "prepared_at": "2026-09-03T00:01:00.000Z",
        },
    )
    outbox.durable_write_json(
        directory / outbox.entry_file_name(1, entry_id, "committed"),
        {"schema_version": outbox.OUTBOX_COMMIT_SCHEMA, "entry_id": entry_id, "committed_at": "2026-09-03T00:01:00.100Z"},
    )

    result = _drain(registry, runtime_root)

    assert result.ok is True
    assert result.delivered == 1
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=5)
    head = view["head"]
    assert head["todos"] == []
    assert head["handoff_mode"] is None
    assert head["leases"] == [record]
    expected_digest = partition_digest({"leases": head["leases"]})
    assert head["partitions"]["leases"] == {"seq": 1, "partition_digest": expected_digest}
    assert result.entries[0]["partition_digest"] == expected_digest
    assert "/should/never/be/compared" in json.dumps(view)


def test_status_reports_backlog_candidate_and_growth_facts(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    empty = adapter.local_authority_shadow_status(registry_path=registry, runtime_root=runtime_root, goal_id=GOAL_ID)
    assert empty["ok"] is True
    assert empty["config"]["status"] == "disabled"
    assert empty["candidate"]["status"] == "missing"
    assert empty["store_bytes"] == 0
    assert empty["retention_pressure"] is False
    assert str(runtime_root) not in json.dumps(empty)

    _record_todo_write(registry, state, runtime_root, "Status fact")
    pending = adapter.local_authority_shadow_status(registry_path=registry, runtime_root=runtime_root, goal_id=GOAL_ID)
    assert pending["outbox"]["todos"]["committed_pending"] == 1
    assert _drain(registry, runtime_root).delivered == 1

    drained = adapter.local_authority_shadow_status(registry_path=registry, runtime_root=runtime_root, goal_id=GOAL_ID)
    assert drained["outbox"]["todos"] == {
        "committed_pending": 0,
        "prepared_only": 0,
        "retired_residue": 0,
        "next_seq": 0,
        "cursor_last_seq": 1,
        "cursor_last_entry_id": outbox.read_cursor(_todo_dir(runtime_root))["last_entry_id"],
        "invalid": None,
    }
    assert drained["candidate"]["status"] == "loaded"
    assert drained["candidate"]["cursor"] == "1"
    assert drained["candidate"]["codec_agreement"] is True
    assert drained["candidate"]["head_schema_version"] == "loopx_coordination_runtime_shadow_projection_v0"
    assert drained["store_bytes"] > 0


def test_capture_evidence_v1_reports_measured_facts_only(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _record_todo_write(registry, state, runtime_root, "Evidence fact")
    drain = _drain(registry, runtime_root)
    evidence = adapter.capture_evidence(goal_id=GOAL_ID, capture=capture.outcome, drain=drain)
    assert adapter.valid_evidence_v1(evidence, goal_id=GOAL_ID)
    assert evidence["outcome"] == "delivered"
    assert evidence["entry"]["entry_id"] == capture.outcome.entry_id
    assert evidence["source_transaction_correlated"] is True
    assert evidence["durable_source_outbox"] is True
    assert evidence["source_candidate_compared"] is False
    assert evidence["parity_verdict"] == "not_evaluated"
    assert evidence["drain"]["candidate_readback_verified"] is True

    deferred = adapter.DrainResult(goal_id=GOAL_ID, outcome="drain_deferred", reason_code="drain_lock_busy")
    assert adapter.capture_evidence(goal_id=GOAL_ID, capture=capture.outcome, drain=deferred)["outcome"] == "drain_deferred"
    pending = adapter.capture_evidence(goal_id=GOAL_ID, capture=capture.outcome, drain=None)
    assert pending["outcome"] == "pending"
    assert pending["drain"] is None

    for skipped_reason in ("partition_unchanged", "shadow_disabled"):
        skipped = outbox.CaptureOutcome(partition="todos", skipped_reason=skipped_reason)
        no_transaction = adapter.capture_evidence(goal_id=GOAL_ID, capture=skipped, drain=None)
        assert no_transaction["outcome"] == "no_transaction"
        assert no_transaction["reason_code"] == skipped_reason
        # Nothing was recorded, so nothing durable or correlated may be claimed.
        assert no_transaction["durable_source_outbox"] is False
        assert no_transaction["source_transaction_correlated"] is False
        assert adapter.valid_evidence_v1(no_transaction, goal_id=GOAL_ID)
    failed = outbox.CaptureOutcome(partition="todos", failure={"reason_code": "outbox_prepare_failed", "error_class": "OSError"})
    failed_evidence = adapter.capture_evidence(goal_id=GOAL_ID, capture=failed, drain=None)
    assert failed_evidence["outcome"] == "capture_failed"
    assert failed_evidence["durable_source_outbox"] is False
    assert failed_evidence["source_transaction_correlated"] is False
    assert adapter.valid_evidence_v1(failed_evidence, goal_id=GOAL_ID)


def _commit_entry_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = adapter.effect_runtime_result

    def counting(method: str, params: object, **kwargs: object) -> object:
        calls.append(method)
        return real(method, params, **kwargs)

    monkeypatch.setattr(adapter, "effect_runtime_result", counting)
    return calls


def test_crash_between_the_two_unlinks_leaves_residue_the_next_drain_reclaims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _record_todo_write(registry, state, runtime_root, "Retired but half-removed")
    real_remove = outbox.remove_entry_files

    def crash_between_unlinks(entry: outbox.OutboxEntry) -> None:
        entry.prepared_path.unlink(missing_ok=True)
        raise OSError("simulated crash between the prepared and committed unlinks")

    monkeypatch.setattr(outbox, "remove_entry_files", crash_between_unlinks)
    first = _drain(registry, runtime_root)
    assert first.outcome == "stopped"
    assert first.reason_code == "shadow_drain_failed"
    monkeypatch.setattr(outbox, "remove_entry_files", real_remove)

    # On disk: the cursor covers seq 1 and only the committed marker survives.
    marker_name = outbox.entry_file_name(1, str(capture.outcome.entry_id), "committed")
    names = sorted(path.name for path in _todo_dir(runtime_root).iterdir())
    assert names == sorted([marker_name, "drain-cursor.json"])
    assert outbox.read_cursor(_todo_dir(runtime_root))["last_seq"] == 1
    # The marker is retired residue, not corruption: listing stays valid.
    assert outbox.list_entries(_todo_dir(runtime_root)) == []
    assert [path.name for path in outbox.retired_residue(_todo_dir(runtime_root))] == [marker_name]
    summary = outbox.outbox_summary(runtime_root, GOAL_ID)["todos"]
    assert summary["invalid"] is None
    assert summary["retired_residue"] == 1
    assert summary["committed_pending"] == 0
    status = adapter.local_authority_shadow_status(registry_path=registry, runtime_root=runtime_root, goal_id=GOAL_ID)
    assert status["ok"] is True
    assert status["outbox"]["todos"]["retired_residue"] == 1

    calls = _commit_entry_calls(monkeypatch)
    second = _drain(registry, runtime_root)
    assert second.ok is True
    assert second.outcome == "drained"
    assert second.reclaimed_residue == 1
    assert (second.delivered, second.replayed) == (0, 0)
    assert "coordination.runtime_shadow.commit_entry" not in calls
    assert list(_todo_dir(runtime_root).iterdir()) == [_todo_dir(runtime_root) / "drain-cursor.json"]
    view = adapter.read_local_authority_shadow(runtime_root=runtime_root, goal_id=GOAL_ID, scan_limit=5)
    assert view["cursor"] == "1"

    # A later write mints seq 2 from the cursor, never reusing the retired seq.
    later = _record_todo_write(registry, state, runtime_root, "After the reclaim")
    assert later.outcome.seq == 2
    third = _drain(registry, runtime_root)
    assert third.delivered == 1
    assert third.reclaimed_residue == 0


def test_crash_after_the_cursor_but_before_any_unlink_is_reclaimed_without_a_store_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _record_todo_write(registry, state, runtime_root, "Cursor written, files untouched")
    real_remove = outbox.remove_entry_files

    def crash_before_unlinks(entry: outbox.OutboxEntry) -> None:
        raise OSError("simulated crash after the cursor write")

    monkeypatch.setattr(outbox, "remove_entry_files", crash_before_unlinks)
    assert _drain(registry, runtime_root).outcome == "stopped"
    monkeypatch.setattr(outbox, "remove_entry_files", real_remove)
    names = sorted(path.name for path in _todo_dir(runtime_root).iterdir())
    entry_id = str(capture.outcome.entry_id)
    assert names == [
        outbox.entry_file_name(1, entry_id, "committed"),
        outbox.entry_file_name(1, entry_id, "prepared"),
        "drain-cursor.json",
    ]
    assert outbox.list_entries(_todo_dir(runtime_root)) == []

    calls = _commit_entry_calls(monkeypatch)
    result = _drain(registry, runtime_root)
    assert result.ok is True
    assert result.reclaimed_residue == 2
    assert "coordination.runtime_shadow.commit_entry" not in calls
    assert list(_todo_dir(runtime_root).iterdir()) == [_todo_dir(runtime_root) / "drain-cursor.json"]


def test_an_orphan_marker_above_the_cursor_is_still_corruption(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _record_todo_write(registry, state, runtime_root, "Marker without its prepared file")
    (_todo_dir(runtime_root) / outbox.entry_file_name(1, str(capture.outcome.entry_id), "prepared")).unlink()
    with pytest.raises(outbox.OutboxError) as raised:
        outbox.list_entries(_todo_dir(runtime_root))
    assert raised.value.reason_code == "outbox_file_invalid"
    result = _drain(registry, runtime_root)
    assert result.outcome == "stopped"
    assert result.reason_code == "outbox_file_invalid"
    status = adapter.local_authority_shadow_status(registry_path=registry, runtime_root=runtime_root, goal_id=GOAL_ID)
    assert status["ok"] is False
    assert status["outbox"]["todos"]["invalid"] == "outbox_file_invalid"


def test_drain_fails_closed_on_an_entry_recorded_for_another_runtime_root(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _record_todo_write(registry, state, runtime_root, "Written under a foreign root")
    entry_id = str(capture.outcome.entry_id)
    prepared_path = _todo_dir(runtime_root) / outbox.entry_file_name(1, entry_id, "prepared")
    record = json.loads(prepared_path.read_text(encoding="utf-8"))
    record["source_root_digest"] = outbox.runtime_root_digest(tmp_path / "elsewhere")
    outbox.durable_write_json(prepared_path, record)

    result = _drain(registry, runtime_root)

    assert result.outcome == "stopped"
    assert result.reason_code == "source_root_mismatch"
    assert result.delivered == 0
    assert result.pending_after == 1
    assert [entry.seq for entry in outbox.list_entries(_todo_dir(runtime_root))] == [1]

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.coordination import local_authority_shadow_adapter as adapter
from loopx.control_plane.coordination import local_authority_shadow_outbox as outbox
from loopx.control_plane.coordination.local_authority_shadow_projection import (
    ProjectionValueError,
    canonical_bytes,
    lease_partition_projection,
    partition_digest,
    sha256_digest,
    text_digest,
    todo_partition_projection,
)
from loopx.file_lock import exclusive_file_lock
from loopx.history import load_registry
from loopx.registry import find_registry_goal
from loopx.todos import add_goal_todo


GOAL_ID = "goal-outbox"


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


def _capture(
    registry: Path,
    state: Path,
    runtime_root: Path,
    *,
    original_text: str,
    enabled: bool = True,
    write_class: str = "todo_add",
) -> outbox.TodoPartitionCapture:
    goal = find_registry_goal(load_registry(registry), GOAL_ID)
    return outbox.TodoPartitionCapture.begin(
        enabled=enabled,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        state_path=state,
        write_class=write_class,
        original_text=original_text,
        projector=adapter.todo_partition_projector(goal, state_path=state),
    )


def _add_todo(registry: Path, text: str) -> str:
    result = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=text,
        task_class="advancement_task",
    )
    assert result["ok"] is True
    return str(result["todo_id"])


def _todo_dir(runtime_root: Path) -> Path:
    return outbox.partition_directory(runtime_root, GOAL_ID, "todos")


def test_capture_records_prepared_then_committed_and_skips_prose_only_writes(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    original = state.read_text(encoding="utf-8")
    todo_id = _add_todo(registry, "Bind the shadow to the primary transaction.")
    new_text = state.read_text(encoding="utf-8")

    capture = _capture(registry, state, runtime_root, original_text=original)
    capture.prepare(new_text)
    names = sorted(path.name for path in _todo_dir(runtime_root).iterdir())
    assert len(names) == 1
    assert names[0].endswith(".prepared.json")
    assert capture.outcome.entry_id is not None
    assert capture.outcome.seq == 1
    assert capture.outcome.source_bytes_digest == text_digest(new_text)
    assert capture.outcome.entry_id == outbox.entry_identity(
        goal_id=GOAL_ID, partition="todos", seq=1, source_ref=text_digest(new_text)
    )

    capture.committed()
    entries = outbox.list_entries(_todo_dir(runtime_root))
    assert [entry.is_committed for entry in entries] == [True]
    entry = entries[0]
    assert entry.prepared["schema_version"] == outbox.OUTBOX_ENTRY_SCHEMA
    assert entry.committed is not None
    assert entry.committed["schema_version"] == outbox.OUTBOX_COMMIT_SCHEMA
    assert entry.prepared["source"] == {
        "kind": "markdown_active_state",
        "previous_bytes_digest": text_digest(original),
        "bytes_digest": text_digest(new_text),
        "lease": None,
        "event_id": None,
    }
    assert entry.prepared["writer"] == {
        "runtime": "python",
        "write_class": "todo_add",
        "operation_id": None,
    }
    projection = entry.projection()
    assert projection is not None
    assert projection["handoff_mode"] == "hard_lease"
    assert [item["todo_id"] for item in projection["todos"]] == [todo_id]
    assert entry.recorded_partition_digest() == partition_digest(projection)
    assert str(runtime_root) not in json.dumps(entry.prepared)

    prose_only = new_text + "\nOperator note that changes no coordination fact.\n"
    prose = _capture(registry, state, runtime_root, original_text=new_text, write_class="todo_update")
    prose.prepare(prose_only)
    prose.committed()
    assert prose.outcome.entry_id is None
    assert prose.outcome.skipped_reason == "partition_unchanged"
    assert len(outbox.list_entries(_todo_dir(runtime_root))) == 1

    _add_todo(registry, "Second coordination fact.")
    third = _capture(registry, state, runtime_root, original_text=new_text)
    third.prepare(state.read_text(encoding="utf-8"))
    third.committed()
    assert third.outcome.seq == 2
    assert [entry.seq for entry in outbox.list_entries(_todo_dir(runtime_root))] == [1, 2]


def test_disabled_capture_creates_nothing(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    capture = _capture(registry, state, runtime_root, original_text="", enabled=False)
    capture.prepare("# anything")
    capture.committed()
    assert capture.outcome.skipped_reason == "shadow_disabled"
    assert capture.outcome.failure is None
    assert not (runtime_root / "authority-shadow").exists()


def test_event_branch_records_projection_in_committed_marker(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    empty = state.read_text(encoding="utf-8")
    baseline_id = _add_todo(registry, "Baseline coordination fact.")
    original = state.read_text(encoding="utf-8")
    baseline = _capture(registry, state, runtime_root, original_text=empty)
    baseline.prepare(original)
    baseline.committed()
    assert baseline.outcome.seq == 1

    # An appended event that changes no compared field retires its own entry.
    unchanged = _capture(registry, state, runtime_root, original_text=original, write_class="todo_complete_event_projection")
    unchanged.prepare(original, event_id="evt-noop")
    assert unchanged.outcome.entry_id is not None
    unchanged.committed(projection_from_disk=True)
    assert unchanged.outcome.entry_id is None
    assert unchanged.outcome.skipped_reason == "partition_unchanged"
    assert [entry.seq for entry in outbox.list_entries(_todo_dir(runtime_root))] == [1]

    capture = _capture(registry, state, runtime_root, original_text=original, write_class="todo_complete_event_projection")
    capture.prepare(original, event_id="evt-1")
    [_baseline, entry] = outbox.list_entries(_todo_dir(runtime_root))
    assert entry.prepared["source"]["kind"] == "state_event_log"
    assert entry.prepared["source"]["event_id"] == "evt-1"
    assert entry.prepared["projection"] is None
    assert entry.prepared["writer"]["operation_id"] == "evt-1"
    assert entry.source_ref == "event:evt-1"
    assert not entry.is_committed

    todo_id = _add_todo(registry, "Landed by the event append.")
    capture.committed(projection_from_disk=True)
    [_baseline, entry] = outbox.list_entries(_todo_dir(runtime_root))
    assert entry.is_committed
    projection = entry.projection()
    assert projection is not None
    assert sorted(item["todo_id"] for item in projection["todos"]) == sorted([baseline_id, todo_id])
    assert entry.recorded_partition_digest() == partition_digest(projection)
    assert capture.outcome.partition_digest == partition_digest(projection)


def test_prepared_only_entries_resolve_from_source_probes(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    original = state.read_text(encoding="utf-8")
    _add_todo(registry, "Crash between write and marker.")
    new_text = state.read_text(encoding="utf-8")
    capture = _capture(registry, state, runtime_root, original_text=original)
    capture.prepare(new_text)
    [entry] = outbox.list_entries(_todo_dir(runtime_root))
    assert not entry.is_committed

    def resolve(text: str) -> str:
        return outbox.resolve_prepared_only_entry(
            entry,
            markdown_text_reader=lambda: text,
            lease_record_reader=None,
            event_presence_reader=None,
        )

    assert resolve(new_text) == "committed"
    assert resolve(original) == "abandoned"
    assert resolve(new_text + "\n- [ ] (agent) foreign edit\n") == "unproved"

    event_entry = outbox.OutboxEntry(
        partition="todos",
        seq=2,
        entry_id="local-shadow-tx-" + "0" * 64,
        prepared_path=tmp_path / "unused.prepared.json",
        committed_path=None,
        prepared={"source": {"kind": "state_event_log", "event_id": "evt-9"}},
        committed=None,
    )
    assert outbox.resolve_prepared_only_entry(
        event_entry, markdown_text_reader=None, lease_record_reader=None,
        event_presence_reader=lambda event_id: event_id == "evt-9",
    ) == "unproved"
    assert outbox.resolve_prepared_only_entry(
        event_entry, markdown_text_reader=None, lease_record_reader=None,
        event_presence_reader=lambda _event_id: False,
    ) == "abandoned"

    planned = {"todo_id": "todo-a", "version": 2, "lease_epoch": 1, "status": "active", "updated_at": "t2"}
    previous = {"todo_id": "todo-a", "version": 1, "lease_epoch": 1, "status": "active", "updated_at": "t1"}
    lease_entry = outbox.OutboxEntry(
        partition="leases",
        seq=1,
        entry_id="local-shadow-tx-" + "1" * 64,
        prepared_path=tmp_path / "unused.prepared.json",
        committed_path=None,
        prepared={"source": {"kind": "task_lease_record", "lease": planned, "previous_lease": previous}},
        committed=None,
    )

    def lease_resolve(current: dict[str, object] | None) -> str:
        return outbox.resolve_prepared_only_entry(
            lease_entry,
            markdown_text_reader=None,
            lease_record_reader=lambda _todo_id: current,
            event_presence_reader=None,
        )

    assert lease_resolve({**planned, "owner": "agent-a"}) == "committed"
    assert lease_resolve({**previous, "owner": "agent-a"}) == "abandoned"
    assert lease_resolve({**planned, "version": 9}) == "unproved"
    assert lease_resolve(None) == "unproved"


def test_sequence_advances_past_the_drain_cursor_and_lists_oldest_first(tmp_path: Path) -> None:
    _registry, _state, runtime_root = _fixture(tmp_path)
    directory = _todo_dir(runtime_root)
    directory.mkdir(parents=True)
    outbox.write_cursor(
        directory,
        partition="todos",
        last_seq=5,
        last_entry_id="local-shadow-tx-" + "a" * 64,
        last_partition_digest=None,
        last_cursor="5",
        last_provider_revision="rev-5",
    )
    assert outbox.next_seq(directory) == 6
    seed = outbox.SeedSource(partition="todos", projection={"handoff_mode": "hard_lease", "todos": []})
    first = outbox.write_seed_entry(runtime_root=runtime_root, goal_id=GOAL_ID, seed=seed)
    second = outbox.write_seed_entry(runtime_root=runtime_root, goal_id=GOAL_ID, seed=seed)
    assert (first.seq, second.seq) == (6, 7)
    assert [entry.seq for entry in outbox.list_entries(directory)] == [6, 7]
    assert all(entry.is_committed for entry in outbox.list_entries(directory))
    assert outbox.latest_partition_digest(directory) == partition_digest(seed.projection)
    summary = outbox.outbox_summary(runtime_root, GOAL_ID)
    assert summary["todos"]["committed_pending"] == 2
    assert summary["todos"]["cursor_last_seq"] == 5
    assert summary["leases"] == {
        "committed_pending": 0,
        "prepared_only": 0,
        "retired_residue": 0,
        "next_seq": 0,
        "cursor_last_seq": None,
        "cursor_last_entry_id": None,
        "invalid": None,
    }
    outbox.remove_entry_files(first)
    assert [entry.seq for entry in outbox.list_entries(directory)] == [7]


def test_canonical_projection_rejects_floats_and_bad_lease_identity() -> None:
    with pytest.raises(ProjectionValueError):
        canonical_bytes({"version": 1.0})
    with pytest.raises(ProjectionValueError):
        todo_partition_projection(handoff_mode="hard_lease", todos=[{"todo_id": "a", "status": 2.5}])
    assert canonical_bytes({"b": 1, "a": [True, None, "\u00e9"]}) == '{"a":[true,null,"\u00e9"],"b":1}'.encode("utf-8")
    assert sha256_digest({"b": [1, None], "a": "x"}) == sha256_digest({"a": "x", "b": [1, None]})
    with pytest.raises(ProjectionValueError):
        lease_partition_projection([("todo-a", {"goal_id": "other", "todo_id": "todo-a"})], goal_id=GOAL_ID)
    projection = lease_partition_projection(
        [("todo-b", {"goal_id": GOAL_ID, "todo_id": "todo-b", "version": 1, "extra": "retained"}),
         ("todo-a", {"goal_id": GOAL_ID, "todo_id": "todo-a", "version": 2, "status": "active"})],
        goal_id=GOAL_ID,
    )
    assert [lease["todo_id"] for lease in projection["leases"]] == ["todo-a", "todo-b"]
    assert projection["leases"][1]["extra"] == "retained"


def test_capture_failure_is_typed_and_never_raises(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    blocker = runtime_root / "authority-shadow"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("not a directory", encoding="utf-8")
    capture = _capture(registry, state, runtime_root, original_text="")
    capture.prepare("---\ngoal_id: goal-outbox\n---\n\n## Agent Todo\n\n- [ ] (agent) x <!-- todo_id: todo_000000000001 -->\n")
    capture.committed()
    assert capture.outcome.entry_id is None
    assert capture.outcome.failure is not None
    assert capture.outcome.failure["reason_code"] == "outbox_prepare_failed"


def test_primary_lock_probe_reports_held_locks(tmp_path: Path) -> None:
    target = tmp_path / "ACTIVE_GOAL_STATE.md"
    target.write_text("", encoding="utf-8")
    assert adapter.primary_lock_is_free(target) is True
    with exclusive_file_lock(target, timeout_seconds=1.0, operation="test_hold"):
        assert adapter.primary_lock_is_free(target) is False
    assert adapter.primary_lock_is_free(target) is True


def test_prepared_records_must_bind_their_directory_identity_and_source(tmp_path: Path) -> None:
    registry, state, runtime_root = _fixture(tmp_path)
    original = state.read_text(encoding="utf-8")
    _add_todo(registry, "Bound to this goal and partition.")
    capture = _capture(registry, state, runtime_root, original_text=original)
    capture.prepare(state.read_text(encoding="utf-8"))
    capture.committed()
    directory = _todo_dir(runtime_root)
    [entry] = outbox.list_entries(directory)
    assert entry.prepared["goal_id"] == GOAL_ID
    assert entry.prepared["partition"] == "todos"
    assert entry.prepared["source_root_digest"] == outbox.runtime_root_digest(runtime_root)
    assert outbox.record_source_ref(entry.prepared) == text_digest(state.read_text(encoding="utf-8"))

    def tampered(**changes: object) -> None:
        record = dict(entry.prepared)
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(record.get(key), dict):
                record[key] = {**record[key], **value}
            else:
                record[key] = value
        outbox.durable_write_json(entry.prepared_path, record)
        with pytest.raises(outbox.OutboxError) as raised:
            outbox.list_entries(directory)
        assert raised.value.reason_code == "outbox_file_invalid"

    tampered(goal_id="goal-other")
    tampered(partition="leases")
    tampered(source={"bytes_digest": text_digest("some other bytes")})
    tampered(source_root_digest="not-a-digest")
    tampered(writer={"runtime": "ruby"})
    tampered(source={"kind": "unknown_source"})
    outbox.durable_write_json(entry.prepared_path, entry.prepared)
    assert len(outbox.list_entries(directory)) == 1

    # Seed entries bind their identity through the partition digest instead.
    lease_seed = outbox.write_seed_entry(
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        seed=outbox.lease_seed_source(runtime_root, GOAL_ID),
    )
    assert outbox.record_source_ref(lease_seed.prepared) == f"seed:{lease_seed.recorded_partition_digest()}"
    lease_directory = outbox.partition_directory(runtime_root, GOAL_ID, "leases")
    assert [item.entry_id for item in outbox.list_entries(lease_directory)] == [lease_seed.entry_id]


def test_retired_residue_is_defined_by_the_cursor_watermark(tmp_path: Path) -> None:
    _registry, _state, runtime_root = _fixture(tmp_path)
    directory = _todo_dir(runtime_root)
    seed = outbox.SeedSource(partition="todos", projection={"handoff_mode": "hard_lease", "todos": []})
    first = outbox.write_seed_entry(runtime_root=runtime_root, goal_id=GOAL_ID, seed=seed)
    second = outbox.write_seed_entry(runtime_root=runtime_root, goal_id=GOAL_ID, seed=seed)
    assert outbox.retired_residue(directory) == []
    outbox.write_cursor(
        directory,
        partition="todos",
        last_seq=first.seq,
        last_entry_id=first.entry_id,
        last_partition_digest=first.recorded_partition_digest(),
        last_cursor="1",
        last_provider_revision="rev-1",
    )
    assert [path.name for path in outbox.retired_residue(directory)] == sorted(
        [first.committed_path.name, first.prepared_path.name]  # type: ignore[union-attr]
    )
    assert [entry.seq for entry in outbox.list_entries(directory)] == [second.seq]
    assert outbox.next_seq(directory) == 3
    assert outbox.reclaim_retired_residue(directory) == 2
    assert outbox.retired_residue(directory) == []
    assert [entry.seq for entry in outbox.list_entries(directory)] == [second.seq]

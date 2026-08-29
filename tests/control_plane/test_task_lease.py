from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane.work_items import task_lease
from loopx.control_plane.work_items.task_lease import (
    MAX_TASK_LEASE_TTL_SECONDS,
    TaskLeaseError,
    assert_expected_version,
    normalize_idempotency_key,
    normalize_ttl_seconds,
    release_task_lease,
    renew_task_lease,
    task_lease_owner_constraint,
    transfer_task_lease,
    write_scopes_overlap,
)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        (["docs/**"], ["docs/a.md"], True),
        (["docs/sub/**"], ["docs/sub/a.md"], True),
        (["docs/a*.md"], ["docs/ab.md"], True),
        (["docs/**"], ["docs/sub/**"], True),
        (["**"], ["loopx/cli.py"], True),
        (["docs/a.md"], ["docs/b.md"], False),
        ([], ["docs/a.md"], False),
    ],
)
def test_write_scopes_overlap(
    left: list[str],
    right: list[str],
    expected: bool,
) -> None:
    assert write_scopes_overlap(left, right) is expected


@pytest.mark.parametrize(
    ("todo", "owner", "registered_agents", "reason"),
    [
        (None, "agent-a", ["agent-a"], "todo_not_found"),
        ({"status": "done"}, "agent-a", ["agent-a"], "todo_not_open"),
        ({"status": "open"}, "", ["agent-a"], "invalid_owner"),
        ({"status": "open"}, "agent-b", ["agent-a"], "owner_not_registered"),
        (
            {"status": "open", "excluded_agents": ["agent-a"]},
            "agent-a",
            ["agent-a"],
            "owner_excluded_from_todo",
        ),
        (
            {"status": "open", "claimed_by": "agent-b"},
            "agent-a",
            ["agent-a", "agent-b"],
            "owner_conflicts_with_claim",
        ),
    ],
)
def test_task_lease_owner_constraint_rejects_ineligible_owner(
    todo: dict[str, Any] | None,
    owner: str,
    registered_agents: list[str],
    reason: str,
) -> None:
    constraint = task_lease_owner_constraint(
        todo,
        owner=owner,
        registered_agents=registered_agents,
    )

    assert constraint["effective"] is False
    assert constraint["reason"] == reason


def test_task_lease_owner_constraint_accepts_matching_claim() -> None:
    constraint = task_lease_owner_constraint(
        {
            "status": "open",
            "claimed_by": "agent-a",
            "excluded_agents": ["agent-b"],
        },
        owner="agent-a",
        registered_agents=["agent-a", "agent-b"],
    )

    assert constraint == {"effective": True}


@pytest.mark.parametrize("ttl", [0, -1, MAX_TASK_LEASE_TTL_SECONDS + 1])
def test_normalize_ttl_seconds_rejects_out_of_range(ttl: int) -> None:
    with pytest.raises(TaskLeaseError, match="ttl seconds") as error:
        normalize_ttl_seconds(ttl)

    assert error.value.code == "invalid_ttl"


@pytest.mark.parametrize("key", ["", "contains space", "bad$key"])
def test_normalize_idempotency_key_rejects_non_token(key: str) -> None:
    with pytest.raises(TaskLeaseError) as error:
        normalize_idempotency_key(key)

    assert error.value.code == "invalid_idempotency_key"


def test_expected_version_is_compare_and_swap_guard() -> None:
    with pytest.raises(TaskLeaseError) as error:
        assert_expected_version({"version": 3}, 2)

    assert error.value.code == "version_mismatch"
    assert error.value.payload == {"expected_version": 2, "actual_version": 3}


def test_lease_epoch_migrates_legacy_records_and_rejects_corruption() -> None:
    assert task_lease.lease_epoch(None) == 0
    assert (
        task_lease.lease_epoch({"schema_version": "task_lease_v0", "version": 7}) == 1
    )

    for raw_epoch in (0, -1, "not-an-epoch"):
        with pytest.raises(TaskLeaseError) as error:
            task_lease.lease_epoch({"lease_epoch": raw_epoch})
        assert error.value.code == "corrupt_lease"


def test_bool_disguised_lease_integers_fail_closed() -> None:
    """bool is an int subclass: a JSON ``true`` must not become epoch/version/
    TTL ``1`` silently.  The shared Stage 2 head codec already rejects bool
    (head._is_count); the local record codec is the migration source for
    ``last_lease_epoch`` seeding, so the same typed corrupt_lease applies
    before any local-to-shared migration."""

    for raw in (True, False):
        with pytest.raises(TaskLeaseError) as error:
            task_lease.lease_epoch({"lease_epoch": raw})
        assert error.value.code == "corrupt_lease"
        with pytest.raises(TaskLeaseError) as error:
            task_lease.lease_version({"version": raw})
        assert error.value.code == "corrupt_lease"
        with pytest.raises(TaskLeaseError) as error:
            task_lease.lease_acquire_ttl_seconds({"acquire_ttl_seconds": raw})
        assert error.value.code == "corrupt_lease"


def test_retained_task_lease_lifecycle_preserves_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(task_lease, "now_utc", lambda: now)
    monkeypatch.setattr(task_lease, "require_task_lease_owner_allowed", lambda **_: {})
    monkeypatch.setattr(
        task_lease,
        "require_registered_task_lease_owner",
        lambda **kwargs: kwargs["owner"],
    )
    monkeypatch.setattr(
        task_lease,
        "task_lease_owner_constraint",
        lambda *_args, **_kwargs: {"effective": True},
    )
    registry_path = tmp_path / "registry.json"
    runtime_root = tmp_path / "runtime"
    lease_path = task_lease.task_lease_path(
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_leasea",
    )
    task_lease.write_lease(
        lease_path,
        task_lease.build_lease(
            goal_id="goal-a",
            todo_id="todo_leasea",
            owner="agent-a",
            idempotency_key="turn-1",
            write_scopes=["loopx/**"],
            acquire_ttl_seconds=120,
            version=1,
            lease_epoch=1,
            acquired_at=now.isoformat().replace("+00:00", "Z"),
            updated_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(seconds=120))
            .isoformat()
            .replace("+00:00", "Z"),
        ),
    )

    with pytest.raises(TaskLeaseError) as renew_without_version:
        renew_task_lease(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id="goal-a",
            todo_id="todo_leasea",
            owner="agent-a",
            idempotency_key="turn-1",
        )
    assert renew_without_version.value.code == "version_required"

    with pytest.raises(TaskLeaseError) as transfer_without_version:
        transfer_task_lease(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id="goal-a",
            todo_id="todo_leasea",
            owner="agent-a",
            idempotency_key="turn-1",
            new_owner="agent-b",
            new_idempotency_key="turn-2",
        )
    assert transfer_without_version.value.code == "version_required"

    renewed = renew_task_lease(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_leasea",
        owner="agent-a",
        idempotency_key="turn-1",
        expected_version=1,
    )
    assert renewed["lease"]["version"] == 2
    assert renewed["lease"]["lease_epoch"] == 1

    transferred = transfer_task_lease(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_leasea",
        owner="agent-a",
        idempotency_key="turn-1",
        new_owner="agent-b",
        new_idempotency_key="turn-2",
        expected_version=2,
    )
    assert transferred["lease"]["owner"] == "agent-b"
    assert transferred["lease"]["version"] == 3
    assert transferred["lease"]["lease_epoch"] == 2

    released = release_task_lease(
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_leasea",
        owner="agent-b",
        idempotency_key="turn-2",
        expected_version=3,
    )
    assert released["released"] is True
    assert released["lease"]["status"] == "released"
    assert released["lease"]["released_at"] == now.isoformat().replace("+00:00", "Z")
    assert released["lease"]["updated_at"] == released["lease"]["released_at"]
    assert task_lease.lease_is_active(released["lease"], at=now) is False
    persisted_path = Path(str(released["lease_path"]))
    assert persisted_path.exists()
    assert task_lease.read_lease(persisted_path) == released["lease"]

    replayed_release = release_task_lease(
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_leasea",
        owner="agent-b",
        idempotency_key="turn-2",
        expected_version=3,
    )
    assert replayed_release["released"] is True
    assert replayed_release["idempotent"] is True
    assert replayed_release["lease"] == released["lease"]

    with pytest.raises(TaskLeaseError) as missing_version:
        release_task_lease(
            runtime_root=runtime_root,
            goal_id="goal-a",
            todo_id="todo_leasea",
            owner="agent-b",
            idempotency_key="turn-2",
        )
    assert missing_version.value.code == "version_required"


def test_legacy_generation_and_unrelated_ttl_do_not_block_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(task_lease, "now_utc", lambda: now)
    runtime_root = tmp_path / "runtime"
    lease_path = task_lease.task_lease_path(
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_legacy",
    )
    task_lease.write_lease(
        lease_path,
        {
            "schema_version": "task_lease_v0",
            "goal_id": "goal-a",
            "todo_id": "todo_legacy",
            "owner": "agent-a",
            "idempotency_key": "legacy-key",
            "write_scopes": [],
            "acquire_ttl_seconds": "unrelated-corrupt-legacy-field",
            "version": 7,
            "status": "active",
            "acquired_at": now.isoformat().replace("+00:00", "Z"),
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(seconds=120))
            .isoformat()
            .replace("+00:00", "Z"),
        },
    )

    released = release_task_lease(
        runtime_root=runtime_root,
        goal_id="goal-a",
        todo_id="todo_legacy",
        owner="agent-a",
        idempotency_key="legacy-key",
        expected_version=7,
    )
    assert released["lease"]["lease_epoch"] == 1

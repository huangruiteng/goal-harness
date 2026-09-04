from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from loopx.state_migration import migrate_legacy_state, render_state_migration_markdown


OLD_GOAL_ID = "legacy-goal"
NEW_GOAL_ID = "migrated-goal"
OLD_STORE_IDENTITY = "file:11111111111111111111111111111111"


def _migration_fixture(tmp_path: Path) -> dict[str, Path]:
    legacy_runtime = tmp_path / "legacy-runtime"
    target_runtime = tmp_path / "target-runtime"
    source_repo = tmp_path / "legacy-repo"
    target_repo = tmp_path / "target-repo"
    source_repo.mkdir()
    target_repo.mkdir()

    source_state = source_repo / "ACTIVE_GOAL_STATE.md"
    source_state.write_text(
        "---\n"
        f"goal_id: {OLD_GOAL_ID}\n"
        "handoff_mode: soft_claim\n"
        "updated_at: 2026-09-02T00:00:00+10:00\n"
        "---\n\n"
        "## Agent Todo\n\n"
        "- [ ] Preserve the new local authority only.\n",
        encoding="utf-8",
    )

    legacy_registry = tmp_path / "legacy-registry.json"
    legacy_registry.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "common_runtime_root": str(legacy_runtime),
                "goals": [
                    {
                        "id": OLD_GOAL_ID,
                        "status": "active",
                        "repo": str(source_repo),
                        "state_file": source_state.name,
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["agent-a", "agent-b"],
                            "authority_shadow": {
                                "schema_version": (
                                    "loopx_local_authority_shadow_config_v0"
                                ),
                                "mode": "file_one_way",
                            },
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    source_goal_runtime = legacy_runtime / "goals" / OLD_GOAL_ID
    (source_goal_runtime / "task-leases").mkdir(parents=True)
    (source_goal_runtime / "task-leases" / "safe-local.json").write_text(
        json.dumps(
            {
                "goal_id": OLD_GOAL_ID,
                "todo_id": "safe-local",
                "owner": "agent-a",
                "version": 1,
                "lease_epoch": 1,
                "status": "released",
            }
        ),
        encoding="utf-8",
    )
    source_shadow_store = (
        legacy_runtime / "authority-shadow" / "file" / OLD_GOAL_ID
    )
    source_shadow_store.mkdir(parents=True)
    (source_shadow_store / "store-identity").write_text(
        OLD_STORE_IDENTITY,
        encoding="utf-8",
    )
    (source_shadow_store / "authority-store-legacy.json").write_text(
        json.dumps(
            {
                "goal_id": OLD_GOAL_ID,
                "store_identity": OLD_STORE_IDENTITY,
                "provider_revision": "file:99:legacy-lineage",
                "cursor": "99",
                "private_provider_byte": "must-never-migrate",
                "source_path": str(source_repo),
            }
        ),
        encoding="utf-8",
    )

    return {
        "legacy_registry": legacy_registry,
        "target_registry": tmp_path / "target-registry.json",
        "legacy_runtime": legacy_runtime,
        "target_runtime": target_runtime,
        "source_repo": source_repo,
        "target_repo": target_repo,
    }


def _migrate(paths: dict[str, Path], *, execute: bool) -> dict[str, object]:
    return migrate_legacy_state(
        legacy_registry_path=paths["legacy_registry"],
        target_registry_path=paths["target_registry"],
        legacy_runtime_root=paths["legacy_runtime"],
        target_runtime_root=paths["target_runtime"],
        goal_ids=[OLD_GOAL_ID],
        goal_id_map={OLD_GOAL_ID: NEW_GOAL_ID},
        path_map={str(paths["source_repo"]): str(paths["target_repo"])},
        copy_active_state=True,
        copy_runtime=True,
        execute=execute,
    )


def test_execute_excludes_old_shadow_and_seeds_fresh_target_lineage(
    tmp_path: Path,
) -> None:
    paths = _migration_fixture(tmp_path)

    result = _migrate(paths, execute=True)

    assert result["ok"] is True
    runtime_result = result["runtime_goals"][0]  # type: ignore[index]
    assert runtime_result["copied"] is True

    target_goal_runtime = paths["target_runtime"] / "goals" / NEW_GOAL_ID
    copied_lease = json.loads(
        (target_goal_runtime / "task-leases" / "safe-local.json").read_text(
            encoding="utf-8"
        )
    )
    assert copied_lease["goal_id"] == NEW_GOAL_ID

    target_store_dir = (
        paths["target_runtime"] / "authority-shadow" / "file" / NEW_GOAL_ID
    )
    target_identity = (target_store_dir / "store-identity").read_text(encoding="utf-8")
    assert target_identity.startswith("file:")
    assert target_identity != OLD_STORE_IDENTITY

    store_paths = list(target_store_dir.glob("authority-store-*.json"))
    assert len(store_paths) == 1
    store_payload = json.loads(store_paths[0].read_text(encoding="utf-8"))
    assert store_payload["goal_id"] == NEW_GOAL_ID
    assert store_payload["store_identity"] == target_identity
    assert store_payload["cursor"] == "1"
    assert len(store_payload["committed"]) == 1
    serialized_store = json.dumps(store_payload, sort_keys=True)
    assert OLD_STORE_IDENTITY not in serialized_store
    assert "file:99:legacy-lineage" not in serialized_store
    assert str(paths["source_repo"]) not in serialized_store
    assert "must-never-migrate" not in serialized_store

    seed = result["authority_shadow_seeds"][0]  # type: ignore[index]
    assert seed["goal_id"] == NEW_GOAL_ID
    assert seed["attempted"] is True
    assert seed["outcome"] == "captured"


def test_dry_run_reports_exclusion_and_seed_plan_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _migration_fixture(tmp_path)
    sentinel = b'{"schema_version":"existing","goals":[]}\n'
    paths["target_registry"].write_bytes(sentinel)

    def forbidden_observer(**_kwargs: object) -> object:
        raise AssertionError("dry-run called the shadow observer")

    original_rglob = Path.rglob

    def guarded_rglob(path: Path, pattern: str) -> Iterator[Path]:
        if path.name == "authority-shadow":
            raise AssertionError("migration entered candidate-provider storage")
        return original_rglob(path, pattern)

    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority_shadow_adapter."
        "observe_local_authority_commit",
        forbidden_observer,
    )
    monkeypatch.setattr(Path, "rglob", guarded_rglob)

    result = _migrate(paths, execute=False)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert paths["target_registry"].read_bytes() == sentinel
    assert not paths["target_runtime"].exists()
    runtime_result = result["runtime_goals"][0]  # type: ignore[index]
    assert runtime_result["copied_file_count"] == 0
    seed = result["authority_shadow_seeds"][0]  # type: ignore[index]
    assert seed == {
        "schema_version": "loopx_state_migration_shadow_seed_evidence_v0",
        "goal_id": NEW_GOAL_ID,
        "attempted": False,
        "outcome": "planned",
        "reason_code": None,
    }
    rendered = render_state_migration_markdown(result)
    assert "Authority Shadow Seeds" in rendered
    assert "outcome=`planned`" in rendered
    assert "must-never-migrate" not in json.dumps(result, sort_keys=True)
    assert "must-never-migrate" not in rendered


def test_seed_failure_is_public_safe_evidence_and_does_not_reverse_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _migration_fixture(tmp_path)

    def fail_observer(**_kwargs: object) -> object:
        raise RuntimeError("credential=private-provider-value")

    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority_shadow_adapter."
        "observe_local_authority_commit",
        fail_observer,
    )

    result = _migrate(paths, execute=True)

    assert result["ok"] is True
    assert result["wrote_project_registry"] is True
    migrated_registry = json.loads(paths["target_registry"].read_text(encoding="utf-8"))
    assert migrated_registry["goals"][0]["id"] == NEW_GOAL_ID
    assert (
        paths["target_runtime"]
        / "goals"
        / NEW_GOAL_ID
        / "task-leases"
        / "safe-local.json"
    ).exists()

    seed = result["authority_shadow_seeds"][0]  # type: ignore[index]
    assert seed["outcome"] == "failed"
    assert seed["reason_code"] == "post_migration_shadow_seed_failed"
    assert seed["attempted"] is True
    assert "credential" not in json.dumps(result, sort_keys=True)
    assert "private-provider-value" not in json.dumps(result, sort_keys=True)
    assert not (
        paths["target_runtime"]
        / "authority-shadow"
        / "file"
        / NEW_GOAL_ID
        / "authority-store-legacy.json"
    ).exists()

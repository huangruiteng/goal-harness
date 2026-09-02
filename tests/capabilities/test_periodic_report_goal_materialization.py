from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from loopx.bootstrap import bootstrap_project
from loopx.capabilities.periodic_report.goal_materialization import (
    migrate_periodic_report_goal_materializations,
    plan_periodic_report_goal_materialization,
    plan_periodic_report_goal_materialization_rollback,
    rollback_periodic_report_goal_materializations,
)
from loopx.capabilities.periodic_report.machine_store import (
    machine_defaults_store_path,
)
from loopx.cli import main
from loopx.registry import atomic_write_json, read_json


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _defaults(*, route_ref: str = "loopx-concierge") -> dict:
    return {
        "schema_version": "loopx_machine_configuration_v0",
        "namespaces": {
            "periodic_report": {
                "schema_version": "periodic_report_machine_defaults_v0",
                "enabled": True,
                "inheritance": "materialize_on_goal_connect",
                "profile_preset": "weekly-progress",
                "route_ref": route_ref,
                "timezone": "Asia/Shanghai",
            },
        },
    }


def _write_defaults(runtime_root: Path, *, route_ref: str = "loopx-concierge") -> None:
    path = machine_defaults_store_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, _defaults(route_ref=route_ref))


def _write_source(
    root: Path,
    goal_id: str,
    *,
    periodic_report: dict | None = None,
    status: str = "active",
) -> Path:
    state_path = root / goal_id / "ACTIVE_GOAL_STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("# Goal\n", encoding="utf-8")
    goal = {
        "id": goal_id,
        "status": status,
        "repo": str(root),
        "state_file": str(state_path.relative_to(root)),
    }
    if periodic_report is not None:
        goal["control_plane"] = {"periodic_report": periodic_report}
    registry_path = root / f"{goal_id}.registry.json"
    atomic_write_json(
        registry_path,
        {
            "schema_version": "0.1",
            "registry_role": "project-local",
            "goals": [goal],
        },
    )
    return registry_path


def _global_goal(source_registry: Path, goal_id: str) -> dict:
    goal = read_json(source_registry)["goals"][0]
    return {**goal, "source_registry": str(source_registry)}


def test_new_goal_connect_materializes_machine_default(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    project = tmp_path / "project"
    project.mkdir()
    registry_path = project / ".loopx" / "registry.json"
    _write_defaults(runtime_root)

    result = bootstrap_project(
        project=project,
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="research",
        objective="Produce a verified research result.",
        domain="research",
        role="primary",
        parent_goal_id=None,
        state_file=None,
        goal_doc=None,
        adapter_kind="read_only_project_map_v0",
        adapter_status="connected",
        next_probe=None,
        spawn_allowed=False,
        max_children=0,
        allowed_domains=[],
        write_scope=[],
        onboarding_scan_enabled=False,
        force=False,
        dry_run=False,
        sync_global=False,
    )

    goal = read_json(registry_path)["goals"][0]
    assert result["periodic_report_default_materialized"] is True
    assert goal["control_plane"]["periodic_report"] == {
        "enabled": True,
        "profile_preset": "weekly-progress",
        "route_ref": "loopx-concierge",
        "source": "machine_default",
        "source_revision": goal["control_plane"]["periodic_report"]["source_revision"],
        "timezone": "Asia/Shanghai",
    }
    assert "agent_id" not in goal["control_plane"]["periodic_report"]


def test_forced_reconnect_preserves_existing_goal_override(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    project = tmp_path / "project"
    project.mkdir()
    registry_path = project / ".loopx" / "registry.json"
    _write_defaults(runtime_root)
    common = dict(
        project=project,
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="research",
        objective="Produce a verified research result.",
        domain="research",
        role="primary",
        parent_goal_id=None,
        state_file=None,
        goal_doc=None,
        adapter_kind="read_only_project_map_v0",
        adapter_status="connected",
        next_probe=None,
        spawn_allowed=False,
        max_children=0,
        allowed_domains=[],
        write_scope=[],
        onboarding_scan_enabled=False,
        dry_run=False,
        sync_global=False,
    )
    bootstrap_project(**common, force=False)
    registry = read_json(registry_path)
    registry["goals"][0]["control_plane"]["periodic_report"] = {
        "enabled": False,
        "route_ref": "research-room",
        "source": "goal_override",
    }
    atomic_write_json(registry_path, registry)

    bootstrap_project(**common, force=True)

    periodic = read_json(registry_path)["goals"][0]["control_plane"]["periodic_report"]
    assert periodic == {
        "enabled": False,
        "route_ref": "research-room",
        "source": "goal_override",
    }


def test_project_register_cli_materializes_machine_default(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    knowledge_root = tmp_path / "project"
    registry_path = tmp_path / "registry.json"
    _write_defaults(runtime_root)

    assert (
        main(
            [
                "--registry",
                str(registry_path),
                "--runtime-root",
                str(runtime_root),
                "--format",
                "json",
                "project",
                "register",
                "--project-id",
                "research-project",
                "--project-kind",
                "work",
                "--knowledge-root",
                str(knowledge_root),
                "--goal-id",
                "research",
                "--objective",
                "Produce a verified research result.",
                "--acceptance",
                "A reviewed result exists.",
                "--next-effect",
                "Inspect the evidence.",
                "--stop-condition",
                "Stop when evidence is unavailable.",
            ]
        )
        == 0
    )

    periodic = read_json(registry_path)["goals"][0]["control_plane"]["periodic_report"]
    assert periodic["source"] == "machine_default"
    assert periodic["route_ref"] == "loopx-concierge"


def test_migration_preserves_override_and_excludes_unavailable_goals(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    inherited = _write_source(tmp_path / "inherited", "inherited")
    overridden = _write_source(
        tmp_path / "overridden",
        "overridden",
        periodic_report={"enabled": False, "source": "goal_override"},
    )
    retired = _write_source(tmp_path / "retired", "retired", status="retired")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [
                _global_goal(inherited, "inherited"),
                _global_goal(overridden, "overridden"),
                _global_goal(retired, "retired"),
                {
                    "id": "missing",
                    "status": "active",
                    "repo": str(tmp_path / "missing"),
                    "state_file": "ACTIVE_GOAL_STATE.md",
                },
            ],
        },
    )

    plan = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )

    assert plan["rows"] == [
        {
            "goal_id": "inherited",
            "action": "materialize",
            "reason": "machine_default_missing",
        },
        {
            "goal_id": "overridden",
            "action": "preserve",
            "reason": "goal_override",
        },
        {"goal_id": "retired", "action": "excluded", "reason": "goal_not_active"},
        {
            "goal_id": "missing",
            "action": "excluded",
            "reason": "authoritative_registry_unavailable",
        },
    ]
    assert plan["writes_required"] == 1


def test_authoritative_terminal_state_beats_a_stale_global_projection(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research", status="retired")
    projected = _global_goal(source_path, "research")
    projected["status"] = "active"
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [projected],
        },
    )

    plan = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )

    assert plan["rows"] == [
        {"goal_id": "research", "action": "excluded", "reason": "goal_not_active"}
    ]
    assert plan["writes_required"] == 0


def test_apply_readback_and_rollback_cover_source_and_global_projection(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [_global_goal(source_path, "research")],
        },
    )
    source_before = read_json(source_path)
    global_before = read_json(global_path)
    preview = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )

    applied = migrate_periodic_report_goal_materializations(
        registry_path=global_path,
        runtime_root=runtime_root,
        execute=True,
        expected_plan_revision=preview["plan_revision"],
    )

    assert applied["status"] == "applied"
    assert applied["readback_verified"] is True
    assert applied["registries_written"] == 2
    source_goal = read_json(source_path)["goals"][0]
    global_goal = read_json(global_path)["goals"][0]
    assert source_goal["control_plane"]["periodic_report"]["source"] == (
        "machine_default"
    )
    assert (
        global_goal["control_plane"]["periodic_report"]
        == source_goal["control_plane"]["periodic_report"]
    )

    rollback_preview = plan_periodic_report_goal_materialization_rollback(
        registry_path=global_path,
        runtime_root=runtime_root,
        transaction_id=applied["transaction_id"],
    )
    rolled_back = rollback_periodic_report_goal_materializations(
        registry_path=global_path,
        runtime_root=runtime_root,
        transaction_id=applied["transaction_id"],
        execute=True,
        expected_plan_revision=rollback_preview["plan_revision"],
    )

    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["readback_verified"] is True
    assert read_json(source_path) == source_before
    assert read_json(global_path) == global_before


def test_apply_refuses_a_concurrent_source_registry_revision(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [_global_goal(source_path, "research")],
        },
    )
    preview = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )
    concurrent = read_json(source_path)
    concurrent["concurrent_revision"] = 1
    atomic_write_json(source_path, concurrent)

    with pytest.raises(ValueError, match="plan revision changed"):
        migrate_periodic_report_goal_materializations(
            registry_path=global_path,
            runtime_root=runtime_root,
            execute=True,
            expected_plan_revision=preview["plan_revision"],
        )

    assert "control_plane" not in read_json(source_path)["goals"][0]


def test_rollback_rejects_a_tampered_local_backup(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [_global_goal(source_path, "research")],
        },
    )
    preview = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )
    applied = migrate_periodic_report_goal_materializations(
        registry_path=global_path,
        runtime_root=runtime_root,
        execute=True,
        expected_plan_revision=preview["plan_revision"],
    )
    backup_path = (
        runtime_root
        / "machine"
        / "periodic-report"
        / "goal-materializations"
        / applied["transaction_id"]
        / "backup.json"
    )
    backup = read_json(backup_path)
    backup["registries"][0]["payload"]["tampered"] = True
    atomic_write_json(backup_path, backup)

    with pytest.raises(ValueError, match="transaction is invalid"):
        plan_periodic_report_goal_materialization_rollback(
            registry_path=global_path,
            runtime_root=runtime_root,
            transaction_id=applied["transaction_id"],
        )


def test_rollback_rejects_a_backup_path_outside_the_registry_allowlist(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [_global_goal(source_path, "research")],
        },
    )
    preview = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )
    applied = migrate_periodic_report_goal_materializations(
        registry_path=global_path,
        runtime_root=runtime_root,
        execute=True,
        expected_plan_revision=preview["plan_revision"],
    )
    transaction_dir = (
        runtime_root
        / "machine"
        / "periodic-report"
        / "goal-materializations"
        / applied["transaction_id"]
    )
    backup_path = transaction_dir / "backup.json"
    receipt_path = transaction_dir / "transaction.json"
    backup = read_json(backup_path)
    backup["registries"][0]["path"] = str(tmp_path / "outside.json")
    atomic_write_json(backup_path, backup)
    receipt = read_json(receipt_path)
    receipt["backup_revision"] = _digest(backup)
    receipt.pop("receipt_revision")
    receipt["receipt_revision"] = _digest(receipt)
    atomic_write_json(receipt_path, receipt)

    with pytest.raises(ValueError, match="backup registry entry is invalid"):
        plan_periodic_report_goal_materialization_rollback(
            registry_path=global_path,
            runtime_root=runtime_root,
            transaction_id=applied["transaction_id"],
        )


def test_failed_cross_registry_readback_restores_every_written_registry(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "goals": [_global_goal(source_path, "research")],
        },
    )
    source_before = read_json(source_path)
    global_before = read_json(global_path)
    preview = plan_periodic_report_goal_materialization(
        registry_path=global_path, runtime_root=runtime_root
    )
    corrupted_once = False

    def corrupt_global_once(path: Path, payload: dict) -> None:
        nonlocal corrupted_once
        atomic_write_json(path, payload)
        if path == global_path and not corrupted_once:
            corrupted_once = True
            changed = read_json(path)
            changed["corrupted"] = True
            atomic_write_json(path, changed)

    with pytest.raises(RuntimeError, match="prior registries were restored"):
        migrate_periodic_report_goal_materializations(
            registry_path=global_path,
            runtime_root=runtime_root,
            execute=True,
            expected_plan_revision=preview["plan_revision"],
            writer=corrupt_global_once,
        )

    assert read_json(source_path) == source_before
    assert read_json(global_path) == global_before


def test_goal_materialization_cli_previews_applies_and_rolls_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime_root = tmp_path / "runtime"
    _write_defaults(runtime_root)
    source_path = _write_source(tmp_path / "source", "research")
    global_path = runtime_root / "registry.global.json"
    atomic_write_json(
        global_path,
        {
            "schema_version": "0.1",
            "registry_role": "global-local",
            "common_runtime_root": str(runtime_root),
            "goals": [_global_goal(source_path, "research")],
        },
    )
    base = [
        "--registry",
        str(global_path),
        "--runtime-root",
        str(runtime_root),
        "--format",
        "json",
        "periodic-report",
    ]

    assert main([*base, "migrate-machine-defaults"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["writes_required"] == 1

    assert (
        main(
            [
                *base,
                "migrate-machine-defaults",
                "--execute",
                "--expected-plan-revision",
                preview["plan_revision"],
            ]
        )
        == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["status"] == "applied"

    assert (
        main(
            [
                *base,
                "rollback-goal-materialization",
                "--transaction-id",
                applied["transaction_id"],
            ]
        )
        == 0
    )
    rollback_preview = json.loads(capsys.readouterr().out)
    assert rollback_preview["rollback_allowed"] is True

    assert (
        main(
            [
                *base,
                "rollback-goal-materialization",
                "--transaction-id",
                applied["transaction_id"],
                "--execute",
                "--expected-plan-revision",
                rollback_preview["plan_revision"],
            ]
        )
        == 0
    )
    rolled_back = json.loads(capsys.readouterr().out)
    assert rolled_back["status"] == "rolled_back"

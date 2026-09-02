from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from loopx.capabilities.catalog import build_capability_detail_packet
from loopx.capabilities.local_synthetic_overlay.core import (
    ALLOWED_CAPABILITIES,
    doctor_local_synthetic_providers,
    issue_local_synthetic_overlay_receipt,
    validate_local_synthetic_overlay_receipt,
    verify_compose_cleanup,
)
from loopx.cli import build_parser


IMAGE = "postgres:17-test@sha256:" + "a" * 64
GOAL_ID = "goal-local-synthetic"
TODO_ID = "todo_local_synthetic"
COMPOSE_PROJECT = "loopx_synthetic_task"
NOW = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)


def _command(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def _doctor_ready(**_kwargs: object) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": "loopx_local_synthetic_overlay_provider_doctor_v0",
        "doctor_digest": "sha256:" + "d" * 64,
        "providers": {
            "local_container": {"ready": True},
            "synthetic_database": {"ready": True},
        },
    }


def _create_repository(repository: Path) -> tuple[str, str]:
    repository.mkdir()
    assert _command(["git", "init", "-q", str(repository)]).returncode == 0
    assert (
        _command(
            ["git", "-C", str(repository), "config", "user.name", "LoopX Test"]
        ).returncode
        == 0
    )
    assert (
        _command(
            [
                "git",
                "-C",
                str(repository),
                "config",
                "user.email",
                "loopx-test@example.invalid",
            ]
        ).returncode
        == 0
    )
    (repository / "candidate.txt").write_text("synthetic candidate\n", encoding="utf-8")
    assert (
        _command(["git", "-C", str(repository), "add", "candidate.txt"]).returncode == 0
    )
    assert (
        _command(
            ["git", "-C", str(repository), "commit", "-q", "-m", "fixture"]
        ).returncode
        == 0
    )
    head = _command(["git", "-C", str(repository), "rev-parse", "HEAD"]).stdout.strip()
    tree = _command(
        ["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"]
    ).stdout.strip()
    return head, tree


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    repository = tmp_path / "candidate"
    head, tree = _create_repository(repository)

    project = tmp_path / "project"
    state_file = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        """---
status: active
objective: local synthetic fixture
updated_at: 2026-09-02T08:00:00Z
---

# Fixture

## Agent Todo

- [ ] Run exact local synthetic validation.
  <!-- loopx:todo todo_id=todo_local_synthetic status=open task_class=advancement_task action_kind=local_validation -->
""",
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    registry_path = project / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "common_runtime_root": str(runtime_root),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(repository),
                        "state_file": str(state_file),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry_path, runtime_root, repository, head, tree


def _issue_fixture(
    fixture: tuple[Path, Path, Path, str, str],
    *,
    repository: Path | None = None,
    head: str | None = None,
    tree: str | None = None,
) -> dict[str, object]:
    (
        registry_path,
        _runtime_root,
        registered_repository,
        registered_head,
        registered_tree,
    ) = fixture
    return issue_local_synthetic_overlay_receipt(
        registry_path=registry_path,
        runtime_root_arg=None,
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        repository=repository or registered_repository,
        candidate_head=head or registered_head,
        candidate_tree=tree or registered_tree,
        capabilities=ALLOWED_CAPABILITIES,
        synthetic_database_image=IMAGE,
        compose_project=COMPOSE_PROJECT,
        product_write_scope="ZERO",
        ttl_seconds=600,
        execute=True,
        now=NOW,
        token_factory=lambda: "deterministic-system-token",
        doctor=_doctor_ready,
    )


def _linked_worktree(
    tmp_path: Path,
    fixture: tuple[Path, Path, Path, str, str],
) -> Path:
    _registry_path, _runtime_root, repository, head, _tree = fixture
    worktree = tmp_path / "candidate-worktree"
    assert (
        _command(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "add",
                "-q",
                "--detach",
                str(worktree),
                head,
            ]
        ).returncode
        == 0
    )
    return worktree


def _issue(
    tmp_path: Path,
) -> tuple[dict[str, object], tuple[Path, Path, Path, str, str]]:
    fixture = _fixture(tmp_path)
    return _issue_fixture(fixture), fixture


def _validate(
    packet: dict[str, object],
    fixture: tuple[Path, Path, Path, str, str],
    **overrides: object,
) -> dict[str, object]:
    registry_path, _runtime_root, repository, head, tree = fixture
    kwargs: dict[str, object] = {
        "registry_path": registry_path,
        "runtime_root_arg": None,
        "receipt_id": packet["receipt_id"],
        "goal_id": GOAL_ID,
        "todo_id": TODO_ID,
        "repository": repository,
        "candidate_head": head,
        "candidate_tree": tree,
        "capabilities": ALLOWED_CAPABILITIES,
        "synthetic_database_image": IMAGE,
        "compose_project": COMPOSE_PROJECT,
        "product_write_scope": "ZERO",
        "now": NOW + timedelta(seconds=1),
    }
    kwargs.update(overrides)
    return validate_local_synthetic_overlay_receipt(**kwargs)


def test_zero_write_receipt_is_system_managed_and_exactly_bound(tmp_path: Path) -> None:
    packet, fixture = _issue(tmp_path)
    validation = _validate(packet, fixture)
    receipt = packet["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["product_write_scope"] == "ZERO"
    assert receipt["capabilities"] == sorted(ALLOWED_CAPABILITIES)
    assert receipt["reusable_across_tasks"] is False
    assert set(receipt["restrictions"].values()) == {False}
    assert receipt["authority_path"] == "loopx_native"
    assert receipt["compose_project"] == COMPOSE_PROJECT
    assert packet["legacy_dispatcher_used"] is False
    assert validation["valid"] is True
    assert validation["receipt_digest"] == packet["receipt_digest"]

    receipt_path = Path(str(packet["receipt_path"]))
    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(receipt_path.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"todo_id": "todo_other"}, "Todo"),
        ({"candidate_head": "b" * 40}, "HEAD"),
        ({"candidate_tree": "c" * 40}, "tree"),
        (
            {"capabilities": [*ALLOWED_CAPABILITIES, "production_deploy"]},
            "exactly capabilities",
        ),
    ],
)
def test_task_candidate_and_capability_drift_invalidates_receipt(
    tmp_path: Path,
    override: dict[str, object],
    message: str,
) -> None:
    packet, fixture = _issue(tmp_path)
    with pytest.raises(ValueError, match=message):
        _validate(packet, fixture, **override)


def test_expiry_and_receipt_tamper_fail_closed(tmp_path: Path) -> None:
    packet, fixture = _issue(tmp_path)
    with pytest.raises(ValueError, match="expired"):
        _validate(packet, fixture, now=NOW + timedelta(seconds=601))

    receipt_path = Path(str(packet["receipt_path"]))
    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    stored["receipt"]["candidate"]["tree"] = "f" * 40
    receipt_path.write_text(json.dumps(stored), encoding="utf-8")
    os.chmod(receipt_path, 0o600)
    with pytest.raises(ValueError, match="digest"):
        _validate(packet, fixture)


def test_unrelated_repository_is_rejected_at_issue_and_validation(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated_head, unrelated_tree = _create_repository(unrelated)
    with pytest.raises(ValueError, match="Goal registry Git repository"):
        _issue_fixture(
            fixture,
            repository=unrelated,
            head=unrelated_head,
            tree=unrelated_tree,
        )

    packet = _issue_fixture(fixture)
    with pytest.raises(ValueError, match="Goal registry Git repository"):
        _validate(
            packet,
            fixture,
            repository=unrelated,
            candidate_head=unrelated_head,
            candidate_tree=unrelated_tree,
        )


def test_registered_repository_linked_worktree_is_valid(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    worktree = _linked_worktree(tmp_path, fixture)
    packet = _issue_fixture(fixture, repository=worktree)
    validation = _validate(packet, fixture, repository=worktree)
    receipt = packet["receipt"]
    assert isinstance(receipt, dict)
    assert receipt["candidate"]["repository"] == str(worktree.resolve())
    assert validation["valid"] is True


def test_receipt_stays_bound_to_exact_candidate_worktree(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    _registry_path, _runtime_root, repository, _head, _tree = fixture
    worktree = _linked_worktree(tmp_path, fixture)
    packet = _issue_fixture(fixture, repository=worktree)
    with pytest.raises(ValueError, match="candidate"):
        _validate(packet, fixture, repository=repository)


def test_compose_project_mismatch_and_tamper_are_rejected(tmp_path: Path) -> None:
    packet, fixture = _issue(tmp_path)
    with pytest.raises(ValueError, match="compose_project"):
        _validate(packet, fixture, compose_project="unrelated_empty_project")

    receipt_path = Path(str(packet["receipt_path"]))
    stored = json.loads(receipt_path.read_text(encoding="utf-8"))
    stored["receipt"]["compose_project"] = "unrelated_empty_project"
    receipt_path.write_text(json.dumps(stored), encoding="utf-8")
    os.chmod(receipt_path, 0o600)
    with pytest.raises(ValueError, match="digest"):
        _validate(packet, fixture)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"product_write_scope": "apps/web/app"},
        {"reusable_across_tasks": True},
        {"real_customer_data": True},
        {"real_child_data": True},
        {"real_audio": True},
        {"real_provider": True},
        {"production": True},
    ],
)
def test_real_production_reuse_and_nonzero_write_scope_are_rejected(
    tmp_path: Path, unsafe: dict[str, object]
) -> None:
    registry_path, _runtime_root, repository, head, tree = _fixture(tmp_path)
    kwargs: dict[str, object] = {
        "registry_path": registry_path,
        "runtime_root_arg": None,
        "goal_id": GOAL_ID,
        "todo_id": TODO_ID,
        "repository": repository,
        "candidate_head": head,
        "candidate_tree": tree,
        "capabilities": ALLOWED_CAPABILITIES,
        "synthetic_database_image": IMAGE,
        "compose_project": COMPOSE_PROJECT,
        "execute": True,
        "now": NOW,
        "doctor": _doctor_ready,
    }
    kwargs.update(unsafe)
    with pytest.raises(ValueError):
        issue_local_synthetic_overlay_receipt(**kwargs)


def test_doctor_is_truthful_and_never_pulls_or_creates() -> None:
    calls: list[list[str]] = []

    def ready_runner(
        argv: list[str], _timeout: float
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        stdout = '"27.0"\n' if argv[1] == "version" else '"sha256:image"\n'
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    ready = doctor_local_synthetic_providers(
        synthetic_database_image=IMAGE,
        runner=ready_runner,
        which=lambda name: f"/fixture/{name}" if name == "docker" else None,
        checked_at=NOW,
    )
    assert ready["ok"] is True
    assert ready["network_pull_attempted"] is False
    assert ready["resource_created"] is False
    assert all("pull" not in argv and "run" not in argv for argv in calls)

    def missing_image(
        argv: list[str], _timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            0 if argv[1] == "version" else 1,
            '"27.0"\n' if argv[1] == "version" else "",
            "",
        )

    unavailable = doctor_local_synthetic_providers(
        synthetic_database_image=IMAGE,
        runner=missing_image,
        which=lambda _name: "/fixture/docker",
        checked_at=NOW,
    )
    assert unavailable["ok"] is False
    assert unavailable["providers"]["synthetic_database"]["ready"] is False


def test_cleanup_readback_reports_clean_and_residue() -> None:
    validation = {
        "valid": True,
        "receipt_id": "overlay_" + "a" * 24,
        "compose_project": COMPOSE_PROJECT,
    }

    def clean_runner(
        argv: list[str], _timeout: float
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, "", "")

    clean = verify_compose_cleanup(
        validation=validation,
        compose_project=COMPOSE_PROJECT,
        runner=clean_runner,
        which=lambda _name: "/fixture/docker",
    )
    assert clean["clean"] is True
    assert clean["residual_counts"] == {
        "containers": 0,
        "volumes": 0,
        "networks": 0,
    }

    def residue_runner(
        argv: list[str], _timeout: float
    ) -> subprocess.CompletedProcess[str]:
        stdout = "container-id\n" if argv[1] == "ps" else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    residue = verify_compose_cleanup(
        validation=validation,
        compose_project=COMPOSE_PROJECT,
        runner=residue_runner,
        which=lambda _name: "/fixture/docker",
    )
    assert residue["ok"] is False
    assert residue["status"] == "residue_detected"


def test_cleanup_uses_only_receipt_bound_compose_project(tmp_path: Path) -> None:
    packet, fixture = _issue(tmp_path)
    validation = _validate(packet, fixture)
    calls: list[list[str]] = []

    def clean_runner(
        argv: list[str], _timeout: float
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    clean = verify_compose_cleanup(
        validation=validation,
        compose_project=COMPOSE_PROJECT,
        runner=clean_runner,
        which=lambda _name: "/fixture/docker",
    )
    assert clean["clean"] is True
    assert len(calls) == 3
    assert all(
        f"label=com.docker.compose.project={COMPOSE_PROJECT}" in argv for argv in calls
    )

    calls.clear()
    with pytest.raises(ValueError, match="does not match"):
        verify_compose_cleanup(
            validation=validation,
            compose_project="unrelated_empty_project",
            runner=clean_runner,
            which=lambda _name: "/fixture/docker",
        )
    assert calls == []


def test_cli_and_capability_catalog_expose_native_path() -> None:
    args = build_parser().parse_args(
        [
            "local-synthetic-overlay",
            "doctor",
            "--synthetic-database-image",
            IMAGE,
            "--format",
            "json",
        ]
    )
    assert args.command == "local-synthetic-overlay"
    assert args.local_synthetic_overlay_command == "doctor"
    detail = build_capability_detail_packet("local-synthetic-overlay")
    capability = detail["capability"]
    assert capability["provider_id"] == "loopx-core"
    assert any("Legacy Dispatcher" in boundary for boundary in capability["boundaries"])

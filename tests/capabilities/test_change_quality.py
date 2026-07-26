from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from loopx.agent_onboarding import _skill_delivery_contract
from loopx.canary.premerge import (
    apply_change_quality_verification,
    build_premerge_validation_gate,
)
from loopx.capabilities.change_quality.policy import change_quality_goal_policy
from loopx.capabilities.change_quality.receipt import (
    CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
    build_change_quality_prepare_packet,
    record_change_quality_receipt,
    verify_change_quality_receipt,
)
from loopx.cli import main
from loopx.configure_goal import configure_goal
from loopx.project_skill_delivery import (
    install_project_skill,
    inspect_project_skill,
)


GOAL_ID = "change-quality-fixture"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "change-quality@example.invalid")
    _git(repo, "config", "user.name", "Change Quality Fixture")
    (repo / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "fixture")
    runtime_root = tmp_path / "runtime"
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(runtime_root),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(repo),
                        "control_plane": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return repo, registry, runtime_root


def _enable(
    registry: Path,
    *,
    safe_fix: bool = True,
    strict_receipt: bool = True,
) -> None:
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        change_quality_enabled=True,
        change_quality_safe_fix=safe_fix,
        change_quality_strict_receipt=strict_receipt,
        execute=True,
    )


def _result(path: Path, fingerprint: str, **overrides: object) -> Path:
    payload = {
        "schema_version": CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
        "scope_fingerprint": fingerprint,
        "reviewed_final_scope": True,
        "summary": "Reviewed the exact final scope.",
        "findings": [],
        "safe_fix_applied": False,
        "safe_fix_passes": 0,
        "validations": ["fixture validation passed"],
        **overrides,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_policy_defaults_off_and_configures_independent_controls(
    tmp_path: Path,
) -> None:
    _repo, registry, _runtime = _fixture(tmp_path)
    stored = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert change_quality_goal_policy(stored) == {
        "schema_version": "change_quality_qualification_policy_v0",
        "enabled": False,
        "safe_fix": False,
        "strict_receipt": False,
    }

    preview = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        change_quality_enabled=True,
        change_quality_strict_receipt=True,
        execute=False,
    )

    assert preview["after"]["change_quality_qualification"] == {
        "enabled": True,
        "safe_fix": False,
        "strict_receipt": True,
    }


def test_exact_scope_receipt_becomes_stale_after_any_diff_change(
    tmp_path: Path,
) -> None:
    repo, registry, runtime_root = _fixture(tmp_path)
    _enable(registry)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    prepared = build_change_quality_prepare_packet(
        registry_path=registry,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    result_path = _result(
        tmp_path / "result.json",
        prepared["scope"]["scope_fingerprint"],
    )

    recorded = record_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=repo,
        result_path=result_path,
        base_ref="HEAD",
        execute=True,
    )
    verified = verify_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    assert recorded["decision"] == "pass"
    assert verified["status"] == "valid"
    assert verified["ok"] is True

    (repo / "app.py").write_text("value = 3\n", encoding="utf-8")
    stale = verify_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    assert stale["status"] == "stale_receipt"
    assert stale["ok"] is False


def test_receipt_identity_is_stable_from_repository_subdirectories(
    tmp_path: Path,
) -> None:
    repo, registry, runtime_root = _fixture(tmp_path)
    _enable(registry)
    nested = repo / "src"
    nested.mkdir()
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    prepared = build_change_quality_prepare_packet(
        registry_path=registry,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    result_path = _result(
        tmp_path / "result.json",
        prepared["scope"]["scope_fingerprint"],
    )
    record_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=repo,
        result_path=result_path,
        base_ref="HEAD",
        execute=True,
    )

    verified = verify_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=nested,
        base_ref="HEAD",
    )
    assert verified["status"] == "valid"
    assert verified["ok"] is True


def test_safe_fix_result_is_rejected_when_policy_forbids_mutation(
    tmp_path: Path,
) -> None:
    repo, registry, runtime_root = _fixture(tmp_path)
    _enable(registry, safe_fix=False, strict_receipt=False)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    prepared = build_change_quality_prepare_packet(
        registry_path=registry,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    result_path = _result(
        tmp_path / "result.json",
        prepared["scope"]["scope_fingerprint"],
        safe_fix_applied=True,
        safe_fix_passes=1,
    )

    with pytest.raises(ValueError, match="policy forbids safe fixes"):
        record_change_quality_receipt(
            registry_path=registry,
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            repo_path=repo,
            result_path=result_path,
            base_ref="HEAD",
            execute=False,
        )


def test_unresolved_blocker_cannot_produce_passing_receipt(
    tmp_path: Path,
) -> None:
    repo, registry, runtime_root = _fixture(tmp_path)
    _enable(registry)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    prepared = build_change_quality_prepare_packet(
        registry_path=registry,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    result_path = _result(
        tmp_path / "result.json",
        prepared["scope"]["scope_fingerprint"],
        findings=[
            {
                "severity": "blocker",
                "code": "required-validation-failed",
                "message": "The required fixture validation failed.",
                "resolved": False,
                "path": "app.py",
                "line": 1,
            }
        ],
    )

    recorded = record_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=repo,
        result_path=result_path,
        base_ref="HEAD",
        execute=True,
    )
    assert recorded["ok"] is False
    assert recorded["decision"] == "fail"
    assert recorded["unresolved_blockers"] == ["required-validation-failed"]


def test_strict_verification_failure_overrides_premerge_gate(
    tmp_path: Path,
) -> None:
    repo, registry, runtime_root = _fixture(tmp_path)
    _enable(registry)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    verification = verify_change_quality_receipt(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        repo_path=repo,
        base_ref="HEAD",
    )
    gate = build_premerge_validation_gate(
        changed_files=["app.py"],
        base_ref="HEAD",
        execute=False,
        repo_root=repo,
    )

    apply_change_quality_verification(gate, verification)

    assert gate["ok"] is False
    assert gate["gate"]["status"] == "quality_receipt_missing"
    assert gate["gate"]["merge_gate_passed"] is False
    assert gate["validation_summary"]["policy_failure_count"] == 1


def test_premerge_cli_enforces_goal_receipt_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, registry, runtime_root = _fixture(tmp_path)
    _enable(registry)
    (repo / "app.py").write_text("value = 2\n", encoding="utf-8")
    monkeypatch.chdir(repo)

    exit_code = main(
        [
            "--registry",
            str(registry),
            "--runtime-root",
            str(runtime_root),
            "--format",
            "json",
            "canary",
            "premerge",
            "--from-git-diff",
            "--git-diff-base",
            "HEAD",
            "--goal-id",
            GOAL_ID,
            "--no-execute",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["change_quality_qualification"]["status"] == "receipt_missing"
    assert payload["gate"]["merge_gate_passed"] is False
    assert payload["gate"]["self_merge_allowed"] is False


def test_quality_skill_delivery_is_policy_conditional_and_host_neutral(
    tmp_path: Path,
) -> None:
    inactive = _skill_delivery_contract("other-agent")
    assert inactive["required_skill_ids"] == [
        "loopx-project",
        "loopx-pr-review",
        "loopx-doc-registry",
        "loopx-self-repair",
    ]

    active_custom = _skill_delivery_contract(
        "other-agent",
        active_project_skill_ids=["loopx-change-quality"],
    )
    assert "loopx-change-quality" in active_custom["required_skill_ids"]
    assert "skills/loopx-change-quality" in active_custom["source_directories"]

    active_codex = _skill_delivery_contract(
        "codex-cli",
        project=str(tmp_path / "project"),
        active_project_skill_ids=["loopx-change-quality"],
    )
    commands = active_codex["project_skill_commands"][0]
    assert commands["status"].startswith("loopx project-skill status ")
    assert commands["preview_install"].startswith("loopx project-skill install ")
    assert commands["apply_install"].endswith(" --execute")


def test_quality_skill_uses_managed_project_delivery(tmp_path: Path) -> None:
    project = tmp_path / "project"
    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{}\n", encoding="utf-8")

    preview = install_project_skill(
        project,
        "loopx-change-quality",
        surfaces=("codex",),
        execute=False,
    )
    assert preview["status"] == "missing"
    assert preview["changed"] is True

    applied = install_project_skill(
        project,
        "loopx-change-quality",
        surfaces=("codex",),
        execute=True,
    )
    assert applied["status"] == "current"
    readback = inspect_project_skill(
        project,
        "loopx-change-quality",
        surfaces=("codex",),
    )
    assert readback["status"] == "current"
    assert readback["managed"] is True

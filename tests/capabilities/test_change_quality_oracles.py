from __future__ import annotations

from pathlib import Path

import pytest

from loopx.capabilities.change_quality.oracles import (
    VALIDATION_CATEGORIES,
    build_change_quality_validation_plan,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "change_quality" / "oracles"


@pytest.mark.parametrize(
    (
        "fixture_name",
        "manifest_refs",
        "expected_runner",
        "expected_languages",
        "task_body_marker",
    ),
    [
        (
            "python",
            ["pyproject.toml"],
            "poe_task",
            {"python"},
            "ruff format --check",
        ),
        (
            "rust",
            ["Cargo.toml", ".cargo/config.toml"],
            "cargo_alias",
            {"rust"},
            "clippy --all-targets",
        ),
        (
            "typescript",
            ["package.json", "tsconfig.json"],
            "package_script",
            {"javascript", "typescript"},
            "prettier --check",
        ),
    ],
)
def test_repository_native_oracle_matrix_covers_core_categories(
    fixture_name: str,
    manifest_refs: list[str],
    expected_runner: str,
    expected_languages: set[str],
    task_body_marker: str,
) -> None:
    fixture = FIXTURE_ROOT / fixture_name

    plan = build_change_quality_validation_plan(
        repo_root=fixture,
        instruction_refs=["AGENTS.md"],
        manifest_refs=manifest_refs,
    )

    assert plan["selection_policy"] == "repository_declared_only"
    assert plan["required_reads"] == ["AGENTS.md"]
    assert plan["unresolved_categories"] == []
    assert plan["ignored_manifest_refs"] == []
    assert plan["discovery_warnings"] == []
    assert plan["auto_execute"] is False
    assert plan["task_bodies_included"] is False
    assert {item["category"] for item in plan["candidates"]} == set(
        VALIDATION_CATEGORIES
    )
    assert {item["runner"] for item in plan["candidates"]} == {expected_runner}
    assert {
        language for item in plan["candidates"] for language in item["language_hints"]
    } == expected_languages
    assert all(item["execution_mode"] == "host_resolved" for item in plan["candidates"])
    assert all(" " not in item["task"] for item in plan["candidates"])
    assert task_body_marker not in str(plan)


def test_oracle_discovery_does_not_infer_commands_from_language_alone(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'no-quality-tasks'\nversion = '0.0.0'\n",
        encoding="utf-8",
    )

    plan = build_change_quality_validation_plan(
        repo_root=tmp_path,
        instruction_refs=[],
        manifest_refs=["pyproject.toml"],
    )

    assert plan["candidates"] == []
    assert plan["unresolved_categories"] == list(VALIDATION_CATEGORIES)


def test_oracle_discovery_reports_malformed_manifest_without_copying_content(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        '{"scripts": {"lint": "secret command"',
        encoding="utf-8",
    )

    plan = build_change_quality_validation_plan(
        repo_root=tmp_path,
        instruction_refs=[],
        manifest_refs=["package.json"],
    )

    assert plan["candidates"] == []
    assert plan["discovery_warnings"] == [
        {"source_ref": "package.json", "code": "manifest_unreadable"}
    ]
    assert "secret command" not in str(plan)


def test_oracle_discovery_does_not_promote_fixture_manifest_tasks(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "tests" / "fixtures" / "nested"
    fixture.mkdir(parents=True)
    (fixture / "package.json").write_text(
        '{"scripts": {"lint": "must not become a project oracle"}}',
        encoding="utf-8",
    )

    plan = build_change_quality_validation_plan(
        repo_root=tmp_path,
        instruction_refs=[],
        manifest_refs=["tests/fixtures/nested/package.json"],
    )

    assert plan["candidates"] == []
    assert plan["ignored_manifest_refs"] == ["tests/fixtures/nested/package.json"]
    assert "must not become a project oracle" not in str(plan)

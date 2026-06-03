#!/usr/bin/env python3
"""Smoke-test a sanitized platform-migration authority/material registry."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GOAL_ID = "platform-migration-material-registry"


def write_platform_migration_fixture(root: Path) -> Path:
    project = root / "project"
    runtime = root / "runtime"
    state_file = f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    registry_path = project / ".goal-harness" / "registry.json"

    (project / Path(state_file).parent).mkdir(parents=True, exist_ok=True)
    (project / "docs" / "meta").mkdir(parents=True, exist_ok=True)
    for rel, text in {
        "README.md": "# Sanitized Platform Migration\n",
        "docs/MIGRATION_GOAL.md": "# Migration Goal\n",
        "docs/OWNER_REVIEW.md": "# Owner Review\n",
        "docs/VALIDATION.md": "# Validation\n",
        "docs/meta/DOC_REGISTRY.yaml": "topics: {}\n",
    }.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    (project / state_file).write_text(
        "---\n"
        "status: active\n"
        "updated_at: 2026-01-01T00:00:00+00:00\n"
        "---\n\n"
        "# Platform Migration Material Registry\n\n"
        "## User Todo\n\n"
        "- [ ] Confirm whether owner review is fresh enough to resume delivery.\n\n"
        "## Agent Todo\n\n"
        "- [ ] Run read-only map and report material freshness without internal links.\n\n"
        "## Next Action\n\n"
        "- Refresh the public-safe material registry summary.\n",
        encoding="utf-8",
    )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-01-01T00:00:00+00:00",
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "complex-migration",
                        "status": "active",
                        "repo": str(project),
                        "state_file": state_file,
                        "requires_authority_registry": True,
                        "authority_sources": [
                            {"kind": "doc", "role": "primary", "path": "docs/MIGRATION_GOAL.md"}
                        ],
                        "authority_registry": {
                            "path": "docs/meta/DOC_REGISTRY.yaml",
                            "read_status": "read",
                            "default_entry_docs": [
                                "docs/MIGRATION_GOAL.md",
                                "docs/OWNER_REVIEW.md",
                                "docs/VALIDATION.md",
                            ],
                            "topic_authority": {
                                "goal": "docs/MIGRATION_GOAL.md",
                                "owner_review": "docs/OWNER_REVIEW.md",
                                "validation": "docs/VALIDATION.md",
                            },
                            "project_materials": {
                                "migration_strategy": {
                                    "role": "current_authority",
                                    "source_kind": "external_doc",
                                    "freshness": "current",
                                },
                                "source_repo": {
                                    "role": "source_surface",
                                    "source_kind": "repository",
                                    "freshness": "read_only_status_ok",
                                },
                                "target_repo": {
                                    "role": "implementation_surface",
                                    "source_kind": "repository",
                                    "freshness": "read_only_status_ok",
                                },
                                "owner_review_packet": {
                                    "role": "owner_review_surface",
                                    "source_kind": "review_doc",
                                    "freshness": "owner_review_required",
                                },
                                "legacy_decision_note": {
                                    "role": "historical_reference",
                                    "source_kind": "external_doc",
                                    "freshness": "stale",
                                },
                                "validation_snapshot": {
                                    "role": "validation_evidence",
                                    "source_kind": "report",
                                    "freshness": "current",
                                },
                            },
                            "deprecated_source_count": 1,
                            "conflict_risk": "medium",
                        },
                        "adapter": {
                            "kind": "complex_project_read_only_map_v0",
                            "status": "connected-read-only",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return registry_path


def run_cli(root: Path, registry_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(root / "runtime"),
            *args,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def assert_public_safe(text: str) -> None:
    forbidden = [
        "byte" + "dance",
        "lark" + "office",
        "company-internal",
        "token",
        "AKIA",
        "/" + "Users/",
    ]
    lowered = text.lower()
    for marker in forbidden:
        assert marker.lower() not in lowered, (marker, text)


def assert_material_counts(
    registry: dict[str, object],
    *,
    expect_required: bool = True,
    expect_deprecated_count: bool = True,
    expected_default_entries_present: int = 3,
) -> None:
    assert registry["declared"] is True, registry
    if expect_required:
        assert registry["required"] is True, registry
    assert registry["default_entry_count"] == 3, registry
    assert registry["default_entries_present"] == expected_default_entries_present, registry
    assert registry["topic_authority_count"] == 3, registry
    assert registry["project_material_count"] == 6, registry
    assert registry["project_material_repository_count"] == 2, registry
    assert registry["project_material_owner_review_required_count"] == 1, registry
    assert registry["project_material_stale_count"] == 1, registry
    assert registry["project_material_current_authority_count"] == 1, registry
    if expect_deprecated_count:
        assert registry["deprecated_source_count"] == 1, registry
    assert registry["conflict_risk"] == "medium", registry


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="goal-harness-platform-migration-") as tmp:
        root = Path(tmp)
        registry_path = write_platform_migration_fixture(root)

        mapped = json.loads(
            run_cli(root, registry_path, "--format", "json", "read-only-map", "--goal-id", GOAL_ID).stdout
        )
        assert mapped["ok"] is True, mapped
        assert mapped["appended"] is True, mapped
        assert_material_counts(
            {
                key.removeprefix("authority_registry_"): value
                for key, value in mapped["project_map"].items()
                if key.startswith("authority_registry_")
            }
            | {
                key: mapped["project_map"][key]
                for key in mapped["project_map"]
                if key == "topic_authority_count" or key.startswith("project_material_")
            },
            expect_required=False,
            expect_deprecated_count=False,
        )

        status = json.loads(run_cli(root, registry_path, "--format", "json", "status", "--limit", "20").stdout)
        assert status["ok"] is True, status
        goal = next(goal for goal in status["run_history"]["goals"] if goal["id"] == GOAL_ID)
        assert_material_counts(goal["authority_registry"], expected_default_entries_present=0)
        queue_item = next(item for item in status["attention_queue"]["items"] if item["goal_id"] == GOAL_ID)
        assert queue_item["project_asset"]["owner"] == "codex", queue_item
        assert queue_item["project_asset"]["agent_todos"]["open"] == 1, queue_item

        status_markdown = run_cli(root, registry_path, "status", "--limit", "20").stdout
        assert "authority_material: entries=0/3 topics=3 materials=6 repositories=2" in status_markdown, status_markdown
        assert "owner_review_required=1 stale=1 current_authority=1 risk=medium" in status_markdown, status_markdown
        assert_public_safe(status_markdown)

        packet = run_cli(root, registry_path, "review-packet", "--goal-id", GOAL_ID).stdout
        assert "authority/material: topics=3, materials=6, repositories=2" in packet, packet
        assert "owner_review_required=1" in packet, packet
        assert "stale=1" in packet, packet
        assert "risk=medium" in packet, packet
        assert "不含内部链接、路径或正文" in packet, packet
        assert_public_safe(packet)

        status_path = root / "status.json"
        html_path = root / "status.html"
        status_path.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        subprocess.run(
            [sys.executable, "examples/render-status-dashboard.py", str(status_path), str(html_path)],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        html = html_path.read_text(encoding="utf-8")
        assert "Authority" in html, html
        assert "materials 6; repos 2; owner review 1; stale 1; risk medium" in html, html
        assert "Public-safe counts only; no source links or raw material text." in html, html
        assert_public_safe(html)

    print("platform-migration-material-registry-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

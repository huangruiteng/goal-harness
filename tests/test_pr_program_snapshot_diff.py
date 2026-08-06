from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "loopx-pr-program" / "scripts" / "diff_snapshot.py"
SKILL_PATH = REPO_ROOT / "skills" / "loopx-pr-program" / "SKILL.md"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loopx_pr_program_diff", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(*, complete: bool, generated_at: str) -> dict[str, object]:
    return {
        "schema_version": "loopx_pr_program_snapshot_v0",
        "program_id": "public-runtime-program",
        "generated_at": generated_at,
        "result_completeness": {
            "complete": complete,
            "scope": {
                "repositories": ["example/runtime"],
                "states": ["open"],
                "authors": [],
                "time_window": {"since": None, "until": None},
            },
        },
        "requirements": [
            {
                "id": "runtime-controls",
                "title": "Expose runtime controls",
                "priority": "P0",
                "coverage": "partial",
            }
        ],
        "change_requests": [
            {
                "ref": "example/runtime#42",
                "title": "feat(runtime): expose quality control",
                "state": "open",
                "draft": True,
                "target_branch": "main",
                "head_sha": "a" * 40,
                "updated_at": generated_at,
                "checks": "passed",
                "review": "pending",
                "work_item": "action_required",
                "theme": "runtime controls",
                "priority": "P0",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [],
                "supersedes": [],
                "description_digest": "sha256:description",
                "review_digest": "sha256:review",
            },
            {
                "ref": "example/runtime#41",
                "title": "refactor(runtime): isolate role parameters",
                "state": "open",
                "draft": False,
                "target_branch": "main",
                "head_sha": "b" * 40,
                "updated_at": generated_at,
                "checks": "passed",
                "review": "approved",
                "work_item": "passed",
                "theme": "runtime controls",
                "priority": "P1",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [],
                "supersedes": [],
                "description_digest": "sha256:description-41",
                "review_digest": "sha256:review-41",
            },
        ],
    }


def test_incomplete_snapshot_does_not_treat_absent_row_as_removed() -> None:
    module = _load_module()
    previous = _snapshot(complete=True, generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(complete=False, generated_at="2026-08-06T10:00:00Z")
    current["change_requests"] = current["change_requests"][:1]
    current["requirements"] = []

    delta = module.build_delta(previous, current)

    assert delta["material_change"] is False
    assert delta["baseline_advance_allowed"] is False
    assert delta["result_hash"] is None
    assert delta["observed_result_hash"]
    assert delta["removed"] == []
    assert delta["omitted_previous"] == ["example/runtime#41"]
    assert delta["omitted_previous_requirements"] == ["runtime-controls"]
    assert delta["observation_only"] == ["example/runtime#42"]


def test_complete_snapshot_reports_material_gate_and_removal_changes() -> None:
    module = _load_module()
    previous = _snapshot(complete=True, generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(complete=True, generated_at="2026-08-06T10:00:00Z")
    current["change_requests"] = current["change_requests"][:1]
    current["change_requests"][0]["checks"] = "failed"

    delta = module.build_delta(previous, current)

    assert delta["material_change"] is True
    assert delta["baseline_advance_allowed"] is True
    assert delta["result_hash"] == delta["observed_result_hash"]
    assert delta["removed"] == ["example/runtime#41"]
    assert delta["changed"] == [
        {
            "ref": "example/runtime#42",
            "changed_fields": ["checks"],
            "before": {"checks": "passed"},
            "after": {"checks": "failed"},
        }
    ]


def test_complete_snapshot_scope_mismatch_fails_closed() -> None:
    module = _load_module()
    previous = _snapshot(complete=True, generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(complete=True, generated_at="2026-08-06T10:00:00Z")
    current["result_completeness"]["scope"]["repositories"] = ["example/other"]
    current["change_requests"] = current["change_requests"][:1]
    current["requirements"] = []

    delta = module.build_delta(previous, current)

    assert delta["scope_matches_previous"] is False
    assert delta["baseline_advance_allowed"] is False
    assert delta["baseline_block_reason"] == "scope_mismatch"
    assert delta["result_hash"] is None
    assert delta["removed"] == []
    assert delta["omitted_previous"] == ["example/runtime#41"]
    assert delta["omitted_previous_requirements"] == ["runtime-controls"]
    assert delta["material_change"] is False


def test_skill_composes_read_only_monitoring_with_integration_branch() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "integration-branch-reconcile" in skill
    assert "verify that each selected ref resolves to the observed `head_sha`" in skill
    assert "must not run `sync --execute` by itself" in skill

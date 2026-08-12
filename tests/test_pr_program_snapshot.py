"""Thin pytest: PR program snapshot diff — baseline, material gate detection,
scope mismatch, observation-only, requirement changes, digest-based content.

Covers GH-C81 core assertions.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Load diff_snapshot module from skills
SCRIPT_PATH = REPO_ROOT / "skills" / "loopx-pr-program" / "scripts" / "diff_snapshot.py"
spec = importlib.util.spec_from_file_location("loopx_pr_program_diff", SCRIPT_PATH)
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)
build_delta = _module.build_delta

_PRIVATE_RE = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def _public_safe(obj: object) -> bool:
    text = json.dumps(obj, sort_keys=True) if not isinstance(obj, str) else obj
    return not any(p.search(text) for p in _PRIVATE_RE)


def _snapshot(program_id="public-runtime-program", generated_at="2026-08-06T09:00:00Z",
              complete=True, repositories=None, change_requests=None, requirements=None):
    if change_requests is None:
        change_requests = [{
            "ref": "example/runtime#42", "title": "feat: expose quality control",
            "state": "open", "draft": True, "target_branch": "main",
            "head_sha": "a" * 40, "updated_at": generated_at,
            "checks": "passed", "review": "pending", "work_item": "action_required",
            "theme": "runtime controls", "priority": "P0",
            "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
            "description_digest": "sha256:description", "review_digest": "sha256:review",
        }]
    if requirements is None:
        requirements = [{"id": "runtime-controls", "title": "Expose runtime controls",
                         "priority": "P0", "coverage": "partial"}]
    return {
        "schema_version": "loopx_pr_program_snapshot_v0",
        "program_id": program_id, "generated_at": generated_at,
        "result_completeness": {
            "complete": complete,
            "scope": {
                "repositories": repositories or ["example/runtime"],
                "states": ["open"], "authors": [],
                "time_window": {"since": None, "until": None},
            },
        },
        "requirements": requirements,
        "change_requests": change_requests,
    }


class TestBaseline:
    def test_first_snapshot_establishes_baseline(self):
        snap = _snapshot()
        delta = build_delta(None, snap)
        assert delta["baseline"] is True
        assert delta["baseline_advance_allowed"] is True
        assert delta["result_hash"] is not None
        assert delta["scope_matches_previous"] is True
        assert delta["added"] == ["example/runtime#42"]
        assert _public_safe(delta)

    def test_duplicate_refs_rejected(self):
        snap = _snapshot()
        snap["change_requests"].append(snap["change_requests"][0].copy())
        with __import__("pytest").raises(ValueError, match="duplicate"):
            build_delta(None, snap)


class TestIncompleteSnapshot:
    def test_observation_only_no_removal_semantics(self):
        previous = _snapshot(complete=True, change_requests=[
            {"ref": "example/runtime#42", "title": "feat: quality", "state": "open",
             "draft": True, "target_branch": "main", "head_sha": "a" * 40,
             "updated_at": "2026-08-06T09:00:00Z", "checks": "passed", "review": "pending",
             "work_item": "action_required", "theme": "rt", "priority": "P0",
             "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
             "description_digest": "sha256:desc", "review_digest": "sha256:review"},
            {"ref": "example/runtime#41", "title": "refactor: isolate", "state": "open",
             "draft": False, "target_branch": "main", "head_sha": "b" * 40,
             "updated_at": "2026-08-06T09:00:00Z", "checks": "passed", "review": "approved",
             "work_item": "passed", "theme": "rt", "priority": "P1",
             "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
             "description_digest": "sha256:desc-41", "review_digest": "sha256:review-41"},
        ])
        current = _snapshot(complete=False, generated_at="2026-08-06T10:00:00Z",
                            change_requests=[{**previous["change_requests"][0],
                                              "updated_at": "2026-08-06T10:00:00Z"}],
                            requirements=[])
        delta = build_delta(previous, current)
        assert delta["material_change"] is False
        assert delta["baseline_advance_allowed"] is False
        assert delta["baseline_block_reason"] == "incomplete_result"
        assert delta["result_hash"] is None
        assert delta["removed"] == []
        assert delta["omitted_previous"] == ["example/runtime#41"]
        assert delta["observation_only"] == ["example/runtime#42"]


class TestMaterialGateChanges:
    def test_checks_and_review_changes_material(self):
        previous = _snapshot()
        current = _snapshot(generated_at="2026-08-06T10:00:00Z")
        current["change_requests"][0]["checks"] = "failed"
        current["change_requests"][0]["review"] = "changes_requested"
        delta = build_delta(previous, current)
        assert delta["material_change"] is True
        assert delta["baseline_advance_allowed"] is True
        assert len(delta["changed"]) == 1
        changed = delta["changed"][0]
        assert set(changed["changed_fields"]) == {"checks", "review"}
        assert changed["before"]["checks"] == "passed"
        assert changed["after"]["checks"] == "failed"

    def test_updated_at_only_is_observation(self):
        previous = _snapshot()
        current = _snapshot(generated_at="2026-08-06T10:00:00Z")
        delta = build_delta(previous, current)
        assert delta["material_change"] is False
        assert delta["changed"] == []
        assert delta["observation_only"] == ["example/runtime#42"]

    def test_unknown_state_is_material_change(self):
        previous = _snapshot()
        current = _snapshot(generated_at="2026-08-06T10:00:00Z", change_requests=[{
            "ref": "example/runtime#42", "title": "feat: quality", "state": "unknown",
            "draft": True, "target_branch": "main", "head_sha": "a" * 40,
            "updated_at": "2026-08-06T10:00:00Z", "checks": "unknown", "review": "unknown",
            "work_item": "unknown", "theme": "rt", "priority": "unclassified",
            "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
            "description_digest": "sha256:desc", "review_digest": "sha256:review"}])
        delta = build_delta(previous, current)
        assert delta["material_change"] is True
        assert "state" in delta["changed"][0]["changed_fields"]


class TestRemovalAndScope:
    def test_complete_snapshot_removal_tracked(self):
        previous = _snapshot(change_requests=[
            {"ref": "example/runtime#42", "title": "feat: quality", "state": "merged",
             "draft": False, "target_branch": "main", "head_sha": "a" * 40,
             "updated_at": "2026-08-06T09:00:00Z", "checks": "passed", "review": "approved",
             "work_item": "passed", "theme": "rt", "priority": "P0",
             "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
             "description_digest": "sha256:desc", "review_digest": "sha256:review"},
            {"ref": "example/runtime#41", "title": "refactor: isolate", "state": "merged",
             "draft": False, "target_branch": "main", "head_sha": "b" * 40,
             "updated_at": "2026-08-06T09:00:00Z", "checks": "passed", "review": "approved",
             "work_item": "passed", "theme": "rt", "priority": "P1",
             "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
             "description_digest": "sha256:desc-41", "review_digest": "sha256:review-41"},
        ])
        current = _snapshot(generated_at="2026-08-06T10:00:00Z",
                            change_requests=[previous["change_requests"][0]])
        delta = build_delta(previous, current)
        assert delta["material_change"] is True
        assert delta["removed"] == ["example/runtime#41"]
        assert delta["summary"]["removed"] == 1

    def test_scope_mismatch_blocks_baseline(self):
        previous = _snapshot(change_requests=[
            {"ref": "example/runtime#42", "title": "feat: quality", "state": "open",
             "draft": True, "target_branch": "main", "head_sha": "a" * 40,
             "updated_at": "2026-08-06T09:00:00Z", "checks": "passed", "review": "pending",
             "work_item": "action_required", "theme": "rt", "priority": "P0",
             "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
             "description_digest": "sha256:desc", "review_digest": "sha256:review"},
            {"ref": "example/runtime#41", "title": "refactor: isolate", "state": "merged",
             "draft": False, "target_branch": "main", "head_sha": "b" * 40,
             "updated_at": "2026-08-06T09:00:00Z", "checks": "passed", "review": "approved",
             "work_item": "passed", "theme": "rt", "priority": "P1",
             "requirement_ids": ["runtime-controls"], "depends_on": [], "supersedes": [],
             "description_digest": "sha256:desc-41", "review_digest": "sha256:review-41"},
        ])
        current = _snapshot(generated_at="2026-08-06T10:00:00Z",
                            repositories=["example/other"],
                            change_requests=[previous["change_requests"][0]],
                            requirements=[])
        delta = build_delta(previous, current)
        assert delta["scope_matches_previous"] is False
        assert delta["baseline_advance_allowed"] is False
        assert delta["baseline_block_reason"] == "scope_mismatch"
        assert delta["removed"] == []
        assert delta["material_change"] is False


class TestRequirementChanges:
    def test_added_and_updated_tracked(self):
        previous = _snapshot()
        current = _snapshot(generated_at="2026-08-06T10:00:00Z", requirements=[
            {"id": "runtime-controls", "title": "Updated title", "priority": "P1", "coverage": "complete"},
            {"id": "new-req", "title": "New requirement", "priority": "P0", "coverage": "none"}])
        delta = build_delta(previous, current)
        assert delta["material_change"] is True
        req_changes = delta["requirement_changes"]
        assert len(req_changes) == 2
        updated = [c for c in req_changes if c["id"] == "runtime-controls"][0]
        assert updated["change"] == "updated"
        added = [c for c in req_changes if c["id"] == "new-req"][0]
        assert added["change"] == "added"


class TestDigestContent:
    def test_digest_changes_tracked_without_raw_body(self):
        previous = _snapshot()
        current = _snapshot(generated_at="2026-08-06T10:00:00Z")
        current["change_requests"][0]["description_digest"] = "sha256:updated-desc"
        current["change_requests"][0]["review_digest"] = "sha256:updated-review"
        delta = build_delta(previous, current)
        assert delta["material_change"] is True
        assert set(delta["changed"][0]["changed_fields"]) == {"description_digest", "review_digest"}
        serialized = json.dumps(delta, ensure_ascii=False)
        assert "review body" not in serialized.lower()


class TestPublicSafety:
    def test_snapshot_and_delta_public_safe(self):
        snap = _snapshot()
        previous = _snapshot()
        current = _snapshot(generated_at="2026-08-06T10:00:00Z")
        delta = build_delta(previous, current)
        for label, p in [("snapshot", snap), ("delta", delta)]:
            assert _public_safe(p), label
        assert "bearer" not in json.dumps(delta, ensure_ascii=False).lower()

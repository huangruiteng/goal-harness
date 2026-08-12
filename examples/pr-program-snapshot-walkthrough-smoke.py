#!/usr/bin/env python3
"""Contributor-facing walkthrough: PR program snapshot diff.

Covers stable program identity, head snapshots, compact diff classification,
review/CI transition lineage, and fail-closed unknown state — without
provider payloads, review bodies, credentials, local paths, or merge authority.

1. **Stable program identity** — program_id, schema_version, generated_at
2. **Scope fingerprint** — structured inventory identity with repositories,
   states, authors, and time_window
3. **Complete snapshot → baseline** — first complete snapshot establishes
   the durable baseline; baseline_advance_allowed=True
4. **Incomplete snapshot** — observation-only; removed/omitted split;
   baseline_advance_allowed=False; material_change=False
5. **Material gate changes** — checks/review/state/title changes are material
6. **Complete-snapshot removals** — rows absent from a complete same-scope
   snapshot are reported as removed
7. **Scope mismatch fails closed** — scope_matches_previous=False blocks
   baseline advance and prevents removal semantics
8. **Observation-only updates** — updated_at changes alone are classified as
   observation_only, not material
9. **Requirement changes** — added, removed, and updated requirements tracked
10. **Digest-based content movement** — description_digest and review_digest
    prove content changes without raw bodies
11. **CLI path** — --current and --previous flags produce delta JSON
12. **Integration-branch composition** — SKILL.md guards prevent auto-sync
13. **Public safety** — no credentials, provider payloads, private paths

No provider payloads, raw sessions, credentials, private locators, or external sinks.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT_PATH = REPO_ROOT / "skills" / "loopx-pr-program" / "scripts" / "diff_snapshot.py"
SKILL_PATH = REPO_ROOT / "skills" / "loopx-pr-program" / "SKILL.md"

spec = importlib.util.spec_from_file_location("loopx_pr_program_diff", SCRIPT_PATH)
assert spec and spec.loader
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)
build_delta = _module.build_delta  # type: ignore[attr-defined]

FORBIDDEN = [
    "/" + "Users/", "/" + "private/", "/" + "tmp/",
    "api" + "_key", "pass" + "word", "sec" + "ret",
    "C:\\", "C:/",
]


def _assert_public_safe(payload: Any, *, label: str = "") -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [n for n in FORBIDDEN if n.lower() in text.lower()]
    assert not leaked, f"{label}: public-boundary leak: {leaked}"


# ── Fixtures ─────────────────────────────────────────────────────────


def _snapshot(
    *,
    program_id: str = "public-runtime-program",
    generated_at: str = "2026-08-06T09:00:00Z",
    complete: bool = True,
    repositories: list[str] | None = None,
    change_requests: list[dict[str, Any]] | None = None,
    requirements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "loopx_pr_program_snapshot_v0",
        "program_id": program_id,
        "generated_at": generated_at,
        "result_completeness": {
            "complete": complete,
            "scope": {
                "repositories": repositories if repositories is not None else ["example/runtime"],
                "states": ["open"],
                "authors": [],
                "time_window": {"since": None, "until": None},
            },
        },
        "requirements": requirements if requirements is not None else [
            {
                "id": "runtime-controls",
                "title": "Expose runtime controls",
                "priority": "P0",
                "coverage": "partial",
            },
        ],
        "change_requests": change_requests if change_requests is not None else [
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
        ],
    }


# ── Scenario 1: Stable program identity ──


def test_stable_program_identity() -> None:
    """A snapshot carries a stable program_id, schema_version, and generated_at.
    The scope defines the inventory identity."""
    snap = _snapshot()
    assert snap["schema_version"] == "loopx_pr_program_snapshot_v0"
    assert snap["program_id"] == "public-runtime-program"
    assert snap["generated_at"] == "2026-08-06T09:00:00Z"
    scope = snap["result_completeness"]["scope"]
    assert scope["repositories"] == ["example/runtime"]
    assert scope["states"] == ["open"]
    assert scope["time_window"] == {"since": None, "until": None}
    assert snap["result_completeness"]["complete"] is True
    _assert_public_safe(snap, label="identity")


# ── Scenario 2: First complete snapshot establishes baseline ──


def test_first_complete_snapshot_establishes_baseline() -> None:
    """The first snapshot (previous=None) establishes the durable baseline.
    baseline=True, baseline_advance_allowed=True."""
    snap = _snapshot()
    delta = build_delta(None, snap)
    assert delta["baseline"] is True
    assert delta["baseline_advance_allowed"] is True
    assert delta["result_hash"] is not None
    assert delta["observed_result_hash"] is not None
    assert delta["scope_matches_previous"] is True
    # First snapshot: items are reported as added; material_change reflects that.
    assert delta["added"] == ["example/runtime#42"]
    _assert_public_safe(delta, label="baseline")


# ── Scenario 3: Incomplete snapshot is observation-only ──


def test_incomplete_snapshot_observation_only() -> None:
    """An incomplete snapshot does not treat absent rows as removed.
    baseline_advance_allowed=False, material_change=False."""
    previous = _snapshot(
        complete=True,
        generated_at="2026-08-06T09:00:00Z",
        change_requests=[
            {
                "ref": "example/runtime#42",
                "title": "feat(runtime): expose quality control",
                "state": "open", "draft": True,
                "target_branch": "main",
                "head_sha": "a" * 40,
                "updated_at": "2026-08-06T09:00:00Z",
                "checks": "passed", "review": "pending",
                "work_item": "action_required",
                "theme": "runtime controls", "priority": "P0",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [], "supersedes": [],
                "description_digest": "sha256:desc",
                "review_digest": "sha256:review",
            },
            {
                "ref": "example/runtime#41",
                "title": "refactor(runtime): isolate role parameters",
                "state": "open", "draft": False,
                "target_branch": "main",
                "head_sha": "b" * 40,
                "updated_at": "2026-08-06T09:00:00Z",
                "checks": "passed", "review": "approved",
                "work_item": "passed",
                "theme": "runtime controls", "priority": "P1",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [], "supersedes": [],
                "description_digest": "sha256:desc-41",
                "review_digest": "sha256:review-41",
            },
        ],
    )
    # Current: incomplete, only one PR with a bumped updated_at (observation-only).
    current = _snapshot(
        complete=False,
        generated_at="2026-08-06T10:00:00Z",
        change_requests=[{
            **previous["change_requests"][0],
            "updated_at": "2026-08-06T10:00:00Z",
        }],
        requirements=[],
    )
    delta = build_delta(previous, current)
    assert delta["material_change"] is False
    assert delta["baseline_advance_allowed"] is False
    assert delta["baseline_block_reason"] == "incomplete_result"
    assert delta["result_hash"] is None
    assert delta["observed_result_hash"] is not None
    assert delta["removed"] == []
    assert delta["omitted_previous"] == ["example/runtime#41"]
    assert delta["omitted_previous_requirements"] == ["runtime-controls"]
    assert delta["observation_only"] == ["example/runtime#42"]
    _assert_public_safe(delta, label="incomplete")


# ── Scenario 4: Material gate changes detected ──


def test_material_gate_changes_detected() -> None:
    """When checks transitions from passed→failed, or review changes,
    the delta reports material_change=True with changed_fields."""
    previous = _snapshot(generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(generated_at="2026-08-06T10:00:00Z")
    current["change_requests"][0]["checks"] = "failed"
    current["change_requests"][0]["review"] = "changes_requested"

    delta = build_delta(previous, current)
    assert delta["material_change"] is True
    assert delta["baseline_advance_allowed"] is True
    assert len(delta["changed"]) == 1
    changed = delta["changed"][0]
    assert changed["ref"] == "example/runtime#42"
    assert set(changed["changed_fields"]) == {"checks", "review"}
    assert changed["before"]["checks"] == "passed"
    assert changed["after"]["checks"] == "failed"
    assert changed["after"]["review"] == "changes_requested"
    _assert_public_safe(delta, label="material-gate")


# ── Scenario 5: Complete-snapshot removal tracked ──


def test_complete_snapshot_removal_tracked() -> None:
    """Rows absent from a complete same-scope snapshot are reported as removed."""
    previous = _snapshot(
        generated_at="2026-08-06T09:00:00Z",
        change_requests=[
            {
                "ref": "example/runtime#42",
                "title": "feat(runtime): expose quality control",
                "state": "merged", "draft": False,
                "target_branch": "main",
                "head_sha": "a" * 40,
                "updated_at": "2026-08-06T09:00:00Z",
                "checks": "passed", "review": "approved",
                "work_item": "passed",
                "theme": "runtime controls", "priority": "P0",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [], "supersedes": [],
                "description_digest": "sha256:desc",
                "review_digest": "sha256:review",
            },
            {
                "ref": "example/runtime#41",
                "title": "refactor(runtime): isolate roles",
                "state": "merged", "draft": False,
                "target_branch": "main",
                "head_sha": "b" * 40,
                "updated_at": "2026-08-06T09:00:00Z",
                "checks": "passed", "review": "approved",
                "work_item": "passed",
                "theme": "runtime controls", "priority": "P1",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [], "supersedes": [],
                "description_digest": "sha256:desc-41",
                "review_digest": "sha256:review-41",
            },
        ],
    )
    current = _snapshot(
        generated_at="2026-08-06T10:00:00Z",
        change_requests=[previous["change_requests"][0]],
    )
    delta = build_delta(previous, current)
    assert delta["material_change"] is True
    assert delta["removed"] == ["example/runtime#41"]
    assert delta["summary"]["removed"] == 1
    _assert_public_safe(delta, label="removal")


# ── Scenario 6: Scope mismatch fails closed ──


def test_scope_mismatch_fails_closed() -> None:
    """When the current scope differs from the previous scope, the delta
    blocks baseline advance and refuses removal semantics."""
    previous = _snapshot(
        generated_at="2026-08-06T09:00:00Z",
        change_requests=[
            {
                "ref": "example/runtime#42",
                "title": "feat(runtime): expose quality control",
                "state": "open", "draft": True,
                "target_branch": "main",
                "head_sha": "a" * 40,
                "updated_at": "2026-08-06T09:00:00Z",
                "checks": "passed", "review": "pending",
                "work_item": "action_required",
                "theme": "runtime controls", "priority": "P0",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [], "supersedes": [],
                "description_digest": "sha256:desc",
                "review_digest": "sha256:review",
            },
            {
                "ref": "example/runtime#41",
                "title": "refactor(runtime): isolate roles",
                "state": "merged", "draft": False,
                "target_branch": "main",
                "head_sha": "b" * 40,
                "updated_at": "2026-08-06T09:00:00Z",
                "checks": "passed", "review": "approved",
                "work_item": "passed",
                "theme": "runtime controls", "priority": "P1",
                "requirement_ids": ["runtime-controls"],
                "depends_on": [], "supersedes": [],
                "description_digest": "sha256:desc-41",
                "review_digest": "sha256:review-41",
            },
        ],
    )
    # Current: different scope → scope_mismatch. Only one PR retained.
    current = _snapshot(
        generated_at="2026-08-06T10:00:00Z",
        repositories=["example/other"],
        change_requests=[previous["change_requests"][0]],
        requirements=[],
    )
    delta = build_delta(previous, current)
    assert delta["scope_matches_previous"] is False
    assert delta["baseline_advance_allowed"] is False
    assert delta["baseline_block_reason"] == "scope_mismatch"
    assert delta["result_hash"] is None
    assert delta["removed"] == []
    assert delta["material_change"] is False
    # Absent rows become omitted_previous, not removed.
    assert delta["omitted_previous"] == ["example/runtime#41"]
    assert delta["omitted_previous_requirements"] == ["runtime-controls"]
    _assert_public_safe(delta, label="scope-mismatch")


# ── Scenario 7: Observation-only updates ──


def test_observation_only_updates() -> None:
    """updated_at changes alone are classified as observation_only,
    not material changes."""
    previous = _snapshot(generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(generated_at="2026-08-06T10:00:00Z")
    # Only the timestamp differs — no material field changed.
    assert current["change_requests"][0]["updated_at"] != previous["change_requests"][0]["updated_at"]

    delta = build_delta(previous, current)
    assert delta["material_change"] is False
    assert delta["changed"] == []
    assert delta["observation_only"] == ["example/runtime#42"]
    _assert_public_safe(delta, label="observation-only")


# ── Scenario 8: Requirement changes tracked ──


def test_requirement_changes_tracked() -> None:
    """Requirement additions, removals, and material-field updates
    are tracked in requirement_changes."""
    previous = _snapshot(generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(
        generated_at="2026-08-06T10:00:00Z",
        requirements=[
            {"id": "runtime-controls", "title": "Updated title",
             "priority": "P1", "coverage": "complete"},
            {"id": "new-req", "title": "New requirement",
             "priority": "P0", "coverage": "none"},
        ],
    )
    delta = build_delta(previous, current)
    assert delta["material_change"] is True
    req_changes = delta["requirement_changes"]
    assert len(req_changes) == 2
    updated_req = [c for c in req_changes if c["id"] == "runtime-controls"][0]
    assert updated_req["change"] == "updated"
    assert "title" in updated_req["changed_fields"]
    added_req = [c for c in req_changes if c["id"] == "new-req"][0]
    assert added_req["change"] == "added"
    _assert_public_safe(delta, label="req-changes")


# ── Scenario 9: Digest-based content movement ──


def test_digest_based_content_movement() -> None:
    """description_digest and review_digest prove content changes
    without storing raw descriptions or review bodies."""
    previous = _snapshot(generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(generated_at="2026-08-06T10:00:00Z")
    current["change_requests"][0]["description_digest"] = "sha256:updated-desc"
    current["change_requests"][0]["review_digest"] = "sha256:updated-review"

    delta = build_delta(previous, current)
    assert delta["material_change"] is True
    assert set(delta["changed"][0]["changed_fields"]) == {
        "description_digest", "review_digest",
    }
    # Raw body text is never present.
    serialized = json.dumps(delta, ensure_ascii=False)
    assert "review body" not in serialized.lower()
    assert "description text" not in serialized.lower()
    _assert_public_safe(delta, label="digest-content")


# ── Scenario 10: Transition lineage through CI states ──


def test_transition_lineage_through_ci_states() -> None:
    """A PR moving through checks (pending→passed→failed) and review
    (pending→approved) forms a transition lineage the delta captures."""
    before = _snapshot(
        generated_at="2026-08-06T09:00:00Z",
        change_requests=[{
            "ref": "example/runtime#42",
            "title": "feat(runtime): expose quality control",
            "state": "open", "draft": False,
            "target_branch": "main",
            "head_sha": "a" * 40,
            "updated_at": "2026-08-06T09:00:00Z",
            "checks": "pending", "review": "pending",
            "work_item": "action_required",
            "theme": "runtime controls", "priority": "P0",
            "requirement_ids": ["runtime-controls"],
            "depends_on": [], "supersedes": [],
            "description_digest": "sha256:desc",
            "review_digest": "sha256:review",
        }],
    )
    after = _snapshot(
        generated_at="2026-08-06T12:00:00Z",
        change_requests=[{
            "ref": "example/runtime#42",
            "title": "feat(runtime): expose quality control",
            "state": "open", "draft": False,
            "target_branch": "main",
            "head_sha": "c" * 40,
            "updated_at": "2026-08-06T12:00:00Z",
            "checks": "passed", "review": "approved",
            "work_item": "passed",
            "theme": "runtime controls", "priority": "P0",
            "requirement_ids": ["runtime-controls"],
            "depends_on": [], "supersedes": [],
            "description_digest": "sha256:desc",
            "review_digest": "sha256:review",
        }],
    )
    delta = build_delta(before, after)
    assert delta["material_change"] is True
    changed = delta["changed"][0]
    assert set(changed["changed_fields"]) == {"head_sha", "checks", "review", "work_item"}
    assert changed["before"] == {
        "head_sha": "a" * 40, "checks": "pending",
        "review": "pending", "work_item": "action_required",
    }
    assert changed["after"] == {
        "head_sha": "c" * 40, "checks": "passed",
        "review": "approved", "work_item": "passed",
    }
    _assert_public_safe(delta, label="ci-lineage")


# ── Scenario 11: Unknown state passes through ──


def test_unknown_state_passes_through() -> None:
    """The snapshot contract allows 'unknown' for state/checks/review/work_item.
    The diff treats unknown→anything as a material change."""
    previous = _snapshot(generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(
        generated_at="2026-08-06T10:00:00Z",
        change_requests=[{
            "ref": "example/runtime#42",
            "title": "feat(runtime): expose quality control",
            "state": "unknown", "draft": True,
            "target_branch": "main",
            "head_sha": "a" * 40,
            "updated_at": "2026-08-06T10:00:00Z",
            "checks": "unknown", "review": "unknown",
            "work_item": "unknown",
            "theme": "runtime controls", "priority": "unclassified",
            "requirement_ids": ["runtime-controls"],
            "depends_on": [], "supersedes": [],
            "description_digest": "sha256:desc",
            "review_digest": "sha256:review",
        }],
    )
    delta = build_delta(previous, current)
    # state, checks, review, work_item, priority all changed to 'unknown'
    assert delta["material_change"] is True
    changed_fields = delta["changed"][0]["changed_fields"]
    assert "state" in changed_fields
    assert "checks" in changed_fields
    _assert_public_safe(delta, label="unknown-state")


# ── Scenario 12: CLI path produces delta ──


def test_cli_path_produces_delta() -> None:
    """The diff_snapshot.py CLI accepts --current and --previous
    paths and writes a delta JSON file."""
    snap = _snapshot()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        current_path = tmp_path / "current.json"
        current_path.write_text(json.dumps(snap), encoding="utf-8")

        # Baseline run (no --previous).
        baseline = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                "--current", str(current_path),
            ],
            cwd=REPO_ROOT,
            check=True, text=True,
            stdout=subprocess.PIPE,
        )
        delta = json.loads(baseline.stdout)
        assert delta["baseline"] is True
        assert delta["baseline_advance_allowed"] is True

        # Second run with --previous.
        previous_path = current_path
        current2 = _snapshot(generated_at="2026-08-06T10:00:00Z")
        current2["change_requests"][0]["checks"] = "failed"
        current_path2 = tmp_path / "current2.json"
        current_path2.write_text(json.dumps(current2), encoding="utf-8")

        output_path = tmp_path / "delta.json"
        subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                "--previous", str(previous_path),
                "--current", str(current_path2),
                "--output", str(output_path),
            ],
            cwd=REPO_ROOT,
            check=True, text=True,
            stdout=subprocess.PIPE,
        )
        delta2 = json.loads(output_path.read_text(encoding="utf-8"))
        assert delta2["material_change"] is True
        assert delta2["changed"][0]["after"]["checks"] == "failed"

        _assert_public_safe(delta2, label="cli-delta")


# ── Scenario 13: Integration-branch composition guard ──


def test_integration_branch_composition_guard() -> None:
    """The SKILL.md documents integration-branch composition rules:
    it references integration-branch-reconcile, verifies head_sha
    resolution, and forbids auto-sync."""
    skill = SKILL_PATH.read_text(encoding="utf-8")
    assert "integration-branch-reconcile" in skill
    assert "verify that each selected ref resolves to the observed `head_sha`" in skill
    assert "must not run `sync --execute` by itself" in skill
    _assert_public_safe(skill, label="skill-md")


# ── Scenario 14: Duplicate refs rejected ──


def test_duplicate_refs_rejected() -> None:
    """Snapshots with duplicate 'ref' values in change_requests are rejected."""
    snap = _snapshot()
    dup = snap["change_requests"][0].copy()
    snap["change_requests"].append(dup)
    try:
        build_delta(None, snap)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()

    _assert_public_safe(snap, label="duplicate-reject")


# ── Scenario 15: Public safety — no provider payloads ──


def test_public_safety_no_provider_payloads() -> None:
    """The snapshot and delta never contain credentials, provider payloads,
    raw review bodies, absolute paths, or external sinks."""
    snap = _snapshot()
    previous = _snapshot(generated_at="2026-08-06T09:00:00Z")
    current = _snapshot(
        generated_at="2026-08-06T10:00:00Z",
        change_requests=[{
            "ref": "example/runtime#42",
            "title": "feat(runtime): expose quality control",
            "state": "merged", "draft": False,
            "target_branch": "main",
            "head_sha": "d" * 40,
            "updated_at": "2026-08-06T10:00:00Z",
            "checks": "passed", "review": "approved",
            "work_item": "passed",
            "theme": "runtime controls", "priority": "P0",
            "requirement_ids": ["runtime-controls"],
            "depends_on": [], "supersedes": [],
            "description_digest": "sha256:desc",
            "review_digest": "sha256:review",
        }],
    )
    delta = build_delta(previous, current)

    for label, payload in [
        ("snapshot", snap),
        ("delta", delta),
    ]:
        _assert_public_safe(payload, label=label)

    # No raw content leaked.
    serialized = json.dumps(delta, ensure_ascii=False).lower()
    assert "bearer" not in serialized
    assert "token" not in serialized
    assert "http" + "://" not in json.dumps(snap, ensure_ascii=False).lower()


def main() -> int:
    tests: list[tuple[str, Any]] = [
        ("stable program identity", test_stable_program_identity),
        ("first complete snapshot establishes baseline", test_first_complete_snapshot_establishes_baseline),
        ("incomplete snapshot observation only", test_incomplete_snapshot_observation_only),
        ("material gate changes detected", test_material_gate_changes_detected),
        ("complete-snapshot removal tracked", test_complete_snapshot_removal_tracked),
        ("scope mismatch fails closed", test_scope_mismatch_fails_closed),
        ("observation-only updates", test_observation_only_updates),
        ("requirement changes tracked", test_requirement_changes_tracked),
        ("digest-based content movement", test_digest_based_content_movement),
        ("transition lineage through CI states", test_transition_lineage_through_ci_states),
        ("unknown state passes through", test_unknown_state_passes_through),
        ("CLI path produces delta", test_cli_path_produces_delta),
        ("integration-branch composition guard", test_integration_branch_composition_guard),
        ("duplicate refs rejected", test_duplicate_refs_rejected),
        ("public safety no provider payloads", test_public_safety_no_provider_payloads),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ok  {label}")
        except Exception as exc:
            print(f"  FAIL  {label}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed} walkthrough scenario(s) failed")
        return 1
    print("pr-program-snapshot-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

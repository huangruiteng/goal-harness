"""Tests for the Goal Acceptance / Evidence Verification layer (plan §5.10).

Closure is NOT just "no work left": a goal must be *actually realized* with
sufficient evidence. This verifies that:
* every acceptance criterion requires satisfying evidence,
* unsatisfied criteria block goal closure (WAIT / pending),
* satisfying all criteria permits closure,
* `goal_acceptance_pending` is emitted when evidence is insufficient.
"""

from __future__ import annotations

from pathlib import Path

from loopx.control_plane.goals.goal_acceptance import (
    acceptance_blocker,
    build_grep_evidence,
    build_manual_evidence,
    evaluate_goal_acceptance,
    emit_goal_acceptance_pending,
    emit_goal_acceptance_satisfied,
    normalize_acceptance_criteria,
    normalize_evidence,
    verify_criterion,
    verify_grep_evidence,
)
from loopx.control_plane.goals.goal_closure import (
    build_goal_closure_state,
    evaluate_goal_closure,
    is_goal_closable,
    maybe_close_goal,
)
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path


def _criteria() -> list[dict]:
    return [
        {"criterion_id": "color_green", "description": "theme color is #22c55e"},
        {"criterion_id": "font_poppins", "description": "font is Poppins"},
    ]


def test_acceptance_satisfied_when_all_criteria_have_evidence() -> None:
    evidence = [
        build_grep_evidence(ref="index.html", pattern="#22c55e", match=True, criterion_ids=["color_green"]),
        build_manual_evidence(ref="index.html", content="font-family:Poppins", ok=True, criterion_ids=["font_poppins"]),
    ]
    result = evaluate_goal_acceptance(acceptance_criteria=_criteria(), evidence=evidence)
    assert result["satisfied"] is True
    assert result["acceptance_gaps"] == []
    assert result["criteria_count"] == 2
    assert result["evidence_count"] == 2


def test_acceptance_gap_when_criterion_missing_evidence() -> None:
    evidence = [
        build_grep_evidence(ref="index.html", pattern="#22c55e", match=True, criterion_ids=["color_green"]),
    ]
    result = evaluate_goal_acceptance(acceptance_criteria=_criteria(), evidence=evidence)
    assert result["satisfied"] is False
    assert [g["criterion_id"] for g in result["acceptance_gaps"]] == ["font_poppins"]


def test_acceptance_gap_when_evidence_ok_false() -> None:
    # A failed grep (match=False -> ok=False) must NOT satisfy the criterion.
    evidence = [
        build_grep_evidence(ref="index.html", pattern="#22c55e", match=False, criterion_ids=["color_green"]),
    ]
    result = evaluate_goal_acceptance(acceptance_criteria=_criteria(), evidence=evidence)
    assert result["satisfied"] is False
    assert len(result["acceptance_gaps"]) == 2


def test_acceptance_no_criteria_is_satisfied() -> None:
    result = evaluate_goal_acceptance(acceptance_criteria=None, evidence=[])
    assert result["satisfied"] is True
    assert result["acceptance_gaps"] == []


def test_verify_criterion_returns_evidence_refs() -> None:
    evidence = [
        build_grep_evidence(ref="index.html", pattern="#22c55e", match=True, criterion_ids=["color_green"]),
    ]
    result = verify_criterion(_criteria()[0], evidence)
    assert result["satisfied"] is True
    assert result["evidence_refs"] == ["grep:#22c55e"]


def test_acceptance_blocker() -> None:
    satisfied = evaluate_goal_acceptance(acceptance_criteria=_criteria(), evidence=[])
    assert satisfied["satisfied"] is False
    assert acceptance_blocker(satisfied) == "acceptance_gaps_remaining"
    full = evaluate_goal_acceptance(
        acceptance_criteria=_criteria(),
        evidence=[
            build_grep_evidence(ref="i", pattern="a", match=True, criterion_ids=["color_green"]),
            build_grep_evidence(ref="i", pattern="b", match=True, criterion_ids=["font_poppins"]),
        ],
    )
    assert full["satisfied"] is True
    assert acceptance_blocker(full) is None


def test_unsatisfied_acceptance_blocks_goal_closure() -> None:
    acceptance = evaluate_goal_acceptance(
        acceptance_criteria=_criteria(),
        evidence=[build_grep_evidence(ref="index.html", pattern="#22c55e", match=True, criterion_ids=["color_green"])],
    )
    state = build_goal_closure_state(acceptance=acceptance)
    assert is_goal_closable(state) is False
    evaluation = evaluate_goal_closure(state)
    assert evaluation["reason"] == "acceptance_gaps_remaining"
    assert evaluation["tri_state"] == "WAIT"
    assert evaluation["evidence"]["acceptance_satisfied"] is False
    assert evaluation["evidence"]["acceptance_gap_count"] == 1


def test_satisfied_acceptance_allows_goal_closure() -> None:
    acceptance = evaluate_goal_acceptance(
        acceptance_criteria=_criteria(),
        evidence=[
            build_grep_evidence(ref="index.html", pattern="#22c55e", match=True, criterion_ids=["color_green"]),
            build_manual_evidence(ref="index.html", content="Poppins", ok=True, criterion_ids=["font_poppins"]),
        ],
    )
    state = build_goal_closure_state(acceptance=acceptance)
    assert is_goal_closable(state) is True


def test_maybe_close_goal_with_gap_emits_pending_not_closed(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    acceptance = evaluate_goal_acceptance(
        acceptance_criteria=_criteria(),
        evidence=[build_grep_evidence(ref="i", pattern="a", match=True, criterion_ids=["color_green"])],
    )
    state = build_goal_closure_state(acceptance=acceptance)
    result = maybe_close_goal(log_path=log_path, goal_id="g1", state=state)
    assert result["ready"] is False
    assert result.get("closed") is not True
    kinds = [e["event_kind"] for e in load_rollout_events(log_path, limit=10)]
    assert kinds == ["goal_acceptance_pending"]
    assert "goal_closed" not in kinds


def test_maybe_close_goal_with_satisfied_acceptance_closes(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    acceptance = evaluate_goal_acceptance(
        acceptance_criteria=_criteria(),
        evidence=[
            build_grep_evidence(ref="i", pattern="a", match=True, criterion_ids=["color_green"]),
            build_manual_evidence(ref="i", content="Poppins", ok=True, criterion_ids=["font_poppins"]),
        ],
    )
    state = build_goal_closure_state(acceptance=acceptance)
    result = maybe_close_goal(log_path=log_path, goal_id="g1", state=state)
    assert result["ready"] is True
    assert result.get("closed") is True
    kinds = [e["event_kind"] for e in load_rollout_events(log_path, limit=10)]
    assert kinds == ["goal_closure_ready", "goal_closed"]


def test_emit_acceptance_events_idempotent(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    emit_goal_acceptance_pending(log_path=log_path, goal_id="g1", acceptance_gaps=[{"criterion_id": "x"}])
    emit_goal_acceptance_pending(log_path=log_path, goal_id="g1", acceptance_gaps=[{"criterion_id": "x"}])
    emit_goal_acceptance_satisfied(log_path=log_path, goal_id="g1", criteria_results=[])
    emit_goal_acceptance_satisfied(log_path=log_path, goal_id="g1", criteria_results=[])
    events = load_rollout_events(log_path, limit=10)
    kinds = [e["event_kind"] for e in events]
    assert kinds.count("goal_acceptance_pending") == 1
    assert kinds.count("goal_acceptance_satisfied") == 1


def test_normalize_evidence_caps_unknown_kind() -> None:
    evidence = [{"evidence_id": "e1", "kind": "weird", "ref": "r", "ok": True}]
    normalized = normalize_evidence(evidence)
    assert normalized[0]["kind"] == "manual"
    assert normalize_acceptance_criteria([{"description": "desc only"}])[0]["criterion_id"]


def test_grep_evidence_independently_verified(tmp_path: Path) -> None:
    """kind=grep evidence is verified against the real file when base_dir is set:
    the framework recomputes `ok` from an actual match, overriding the caller flag."""
    target = tmp_path / "index.html"
    target.write_text('<body style="background:#f9d616"></body>', encoding="utf-8")
    criteria = [{"criterion_id": "c1", "description": "背景为黄色"}]

    # Honest match -> satisfied, independently verified.
    ev_match = build_grep_evidence(
        ref="index.html", pattern="f9d616", match=True, criterion_ids=["c1"]
    )
    r1 = evaluate_goal_acceptance(
        acceptance_criteria=criteria, evidence=[ev_match], base_dir=tmp_path
    )
    assert r1["satisfied"] is True
    assert r1["verified_count"] == 1

    # Self-reported ok=True but the pattern does NOT exist in the file ->
    # the framework must override `ok` to False (no false "goal_closed").
    ev_lie = build_grep_evidence(
        ref="index.html", pattern="00ff00", match=True, criterion_ids=["c1"]
    )
    r2 = evaluate_goal_acceptance(
        acceptance_criteria=criteria, evidence=[ev_lie], base_dir=tmp_path
    )
    assert r2["satisfied"] is False
    assert r2["acceptance_gaps"][0]["criterion_id"] == "c1"

    # Missing target file is a genuine negative finding.
    ev_missing = build_grep_evidence(
        ref="nope.html", pattern="x", match=True, criterion_ids=["c1"]
    )
    r3 = evaluate_goal_acceptance(
        acceptance_criteria=criteria, evidence=[ev_missing], base_dir=tmp_path
    )
    assert r3["satisfied"] is False

    # Without base_dir, grep evidence degrades to the caller's ok (back-compat).
    r4 = evaluate_goal_acceptance(acceptance_criteria=criteria, evidence=[ev_match])
    assert r4["satisfied"] is True
    assert r4["verified_count"] == 0


def test_verify_grep_evidence_overrides_caller_ok(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("COLOR = '#f9d616'", encoding="utf-8")
    # Caller claims ok, pattern absent -> framework returns not ok + verified.
    verified = verify_grep_evidence(
        {"kind": "grep", "ref": "app.py", "pattern": "nope", "ok": True},
        base_dir=tmp_path,
    )
    assert verified["ok"] is False
    assert verified["verified"] is True
    assert verified["matched_lines"] == 0
    # Non-grep evidence untouched.
    manual = verify_grep_evidence(
        {"kind": "manual", "ref": "app.py", "ok": True}, base_dir=tmp_path
    )
    assert manual["ok"] is True
    assert manual.get("verified") is not True

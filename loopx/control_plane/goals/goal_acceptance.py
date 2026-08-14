"""Goal Acceptance / Evidence Verification (plan §5.10).

Closure is NOT just "no work left" — a goal must also be *actually realized* with
sufficient evidence. This module answers: "was the goal truly achieved, and is
the evidence adequate to prove it?".

The evaluation runs BEFORE the Closure Evaluator's `is_goal_closable`:

    last todo done -> Scheduler (ready = [])
        -> Goal Acceptance Evaluator (evidence sufficient?)
              -> satisfied   -> Closure Evaluator -> goal_closed
              -> insufficient -> emit goal_acceptance_pending (not close)

An acceptance criterion is a declarative check, e.g. "theme color is green
(#22c55e)". Evidence is a collection of artifacts (grep hit, test pass, file
snapshot, ...). A criterion is *satisfied* when there is at least one
``satisfying`` evidence ref for it; otherwise it becomes an ``acceptance_gap``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...rollout_event_log import append_rollout_event_once, build_rollout_event

GOAL_ACCEPTANCE_EVALUATION_SCHEMA_VERSION = "goal_acceptance_evaluation_v0"
GOAL_ACCEPTANCE_CRITERIA_SCHEMA_VERSION = "goal_acceptance_criteria_v0"

# Evidence kinds understood by the evaluator.
EVIDENCE_KIND_GREP = "grep"
EVIDENCE_KIND_SNAPSHOT = "snapshot"
EVIDENCE_KIND_TEST = "test"
EVIDENCE_KIND_FILE = "file"
EVIDENCE_KIND_MANUAL = "manual"
EVIDENCE_KINDS = {
    EVIDENCE_KIND_GREP,
    EVIDENCE_KIND_SNAPSHOT,
    EVIDENCE_KIND_TEST,
    EVIDENCE_KIND_FILE,
    EVIDENCE_KIND_MANUAL,
}


def normalize_acceptance_criteria(
    criteria: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize acceptance criteria into ``{criterion_id, description, kind}``."""
    result: list[dict[str, Any]] = []
    for item in criteria or ():
        if not isinstance(item, dict):
            continue
        criterion_id = str(item.get("criterion_id") or item.get("id") or "").strip()
        description = str(item.get("description") or "").strip()
        if not criterion_id:
            # Derive an id from the description hash when absent.
            criterion_id = _slug(description)
        kind = str(item.get("kind") or "assert").strip() or "assert"
        result.append(
            {
                "criterion_id": criterion_id,
                "description": description,
                "kind": kind,
            }
        )
    return result


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text)[:64] or "criterion"


def normalize_evidence(
    evidence: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize evidence into ``{evidence_id, kind, ref, content, ok}``."""
    result: list[dict[str, Any]] = []
    for item in evidence or ():
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or item.get("id") or "").strip()
        if not evidence_id:
            evidence_id = f"ev:{len(result)}"
        kind = str(item.get("kind") or EVIDENCE_KIND_MANUAL).strip()
        if kind not in EVIDENCE_KINDS:
            kind = EVIDENCE_KIND_MANUAL
        result.append(
            {
                "evidence_id": evidence_id,
                "kind": kind,
                "ref": str(item.get("ref") or ""),
                "pattern": str(item.get("pattern") or ""),
                "content": str(item.get("content") or ""),
                "ok": bool(item.get("ok", True)),
                "expect": str(item.get("expect") or "present").strip() or "present",
                "criterion_ids": [
                    str(c) for c in (item.get("criterion_ids") or []) if str(c)
                ],
            }
        )
    return result


def verify_criterion(
    criterion: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify a single criterion against the evidence list.

    A criterion is *satisfied* when at least one piece of ``ok`` evidence
    references it (by ``criterion_id``) or, if the criterion declares no specific
    evidence requirement, when there is at least one ``ok`` manual/snapshot
    evidence. Returns ``{criterion_id, satisfied, evidence_refs}``.
    """
    criterion_id = str(criterion.get("criterion_id") or "").strip()
    description = str(criterion.get("description") or "").strip()
    matching: list[str] = []
    for ev in evidence:
        if not ev.get("ok"):
            continue
        ref_ids = ev.get("criterion_ids") or []
        if criterion_id in ref_ids:
            matching.append(str(ev.get("evidence_id") or ""))
    satisfied = bool(matching)
    return {
        "criterion_id": criterion_id,
        "description": description,
        "satisfied": satisfied,
        "evidence_refs": matching,
    }


def evaluate_goal_acceptance(
    *,
    acceptance_criteria: Sequence[Mapping[str, Any]] | None,
    evidence: Sequence[Mapping[str, Any]] | None,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run the Acceptance Evaluator.

    Args:
      base_dir : when provided, ``grep``-kind evidence is *independently verified*
                 against the real file (framework reads the file + regex-matches),
                 instead of trusting the caller-supplied ``ok`` flag. This is the
                 "self-reported -> verified" step. Relative ``ref`` paths resolve
                 under ``base_dir``.

    Returns:
      satisfied        : every criterion has satisfying evidence
      acceptance_gaps  : list of unsatisfied criteria
      criteria_results : per-criterion verification
      evidence_count   : number of ok evidence items
      verified_count   : number of evidence items independently re-verified
    """
    criteria = normalize_acceptance_criteria(acceptance_criteria)
    evidence_list = normalize_evidence(evidence)
    # Independent verification first: recompute ``ok`` for grep evidence from the
    # actual file when a base_dir is available. The caller's self-reported flag is
    # only a fallback when the target/pattern is absent or kind is not grep.
    if base_dir is not None:
        evidence_list = [
            verify_grep_evidence(e, base_dir=Path(base_dir)) for e in evidence_list
        ]
    ok_evidence = [e for e in evidence_list if e.get("ok")]
    verified_count = sum(1 for e in evidence_list if e.get("verified"))

    # When no criteria are declared, treat acceptance as satisfied (nothing to
    # prove) unless the caller explicitly marks acceptance required.
    if not criteria:
        return {
            "schema_version": GOAL_ACCEPTANCE_EVALUATION_SCHEMA_VERSION,
            "satisfied": True,
            "acceptance_gaps": [],
            "criteria_results": [],
            "evidence_count": len(ok_evidence),
            "verified_count": verified_count,
            "criteria_count": 0,
        }

    results = [verify_criterion(c, evidence_list) for c in criteria]
    gaps = [r for r in results if not r["satisfied"]]
    return {
        "schema_version": GOAL_ACCEPTANCE_EVALUATION_SCHEMA_VERSION,
        "satisfied": len(gaps) == 0,
        "acceptance_gaps": gaps,
        "criteria_results": results,
        "evidence_count": len(ok_evidence),
        "verified_count": verified_count,
        "criteria_count": len(criteria),
    }


def build_grep_evidence(
    *,
    ref: str,
    pattern: str,
    match: bool,
    content: str = "",
    criterion_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Convenience builder for a grep-based evidence item."""
    return {
        "evidence_id": f"grep:{pattern}",
        "kind": EVIDENCE_KIND_GREP,
        "ref": ref,
        "pattern": pattern,
        "content": content or pattern,
        "ok": match,
        "criterion_ids": list(criterion_ids),
    }


def build_manual_evidence(
    *,
    ref: str,
    content: str,
    ok: bool = True,
    criterion_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Convenience builder for a manual/operator-confirmed evidence item."""
    return {
        "evidence_id": f"manual:{ref}",
        "kind": EVIDENCE_KIND_MANUAL,
        "ref": ref,
        "content": content,
        "ok": ok,
        "criterion_ids": list(criterion_ids),
    }


def verify_grep_evidence(
    evidence: dict[str, Any],
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Independently verify a ``grep`` evidence item against the actual file.

    This is the step that moves acceptance from *self-reported* to *verified*:
    instead of trusting a caller-supplied ``ok`` flag, the framework reads the
    target file and checks whether the regex pattern actually matches. The
    evidence's ``ok`` is recomputed from the real result.

    Resolution rules for the target file:
      * if ``ref`` is an absolute path, it is used directly;
      * otherwise ``base_dir / ref`` (when ``base_dir`` is provided) or ``cwd / ref``.

    Returns a copy of ``evidence`` with ``ok``/``content``/``verified`` updated.
    ``verified=True`` means the framework actually performed the check; when the
    file is unreadable the evidence is treated as *not ok* but still ``verified``
    (the mismatch is the finding). Evidence lacking a regex ``pattern`` is left
    untouched (``verified=False``) so it degrades to the prior manual path.
    """
    if evidence.get("kind") != EVIDENCE_KIND_GREP:
        return dict(evidence)
    ref = str(evidence.get("ref") or "").strip()
    pattern = str(evidence.get("pattern") or evidence.get("content") or "").strip()
    if not ref or not pattern:
        return dict(evidence)  # not enough info to verify — keep caller's ok

    candidate: Path
    p = Path(ref)
    if p.is_absolute():
        candidate = p
    elif base_dir is not None:
        candidate = Path(base_dir) / p
    else:
        candidate = p
    candidate = candidate.resolve()

    result = dict(evidence)
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except Exception:
        # Unreadable target is a genuine negative finding.
        result["ok"] = False
        result["verified"] = True
        result["verification_error"] = f"unreadable target: {candidate}"
        return result

    try:
        hit = re.search(pattern, text) is not None
    except re.error as exc:
        result["ok"] = False
        result["verified"] = True
        result["verification_error"] = f"invalid regex {pattern!r}: {exc}"
        return result

    # Expectation semantics: ``expect="absent"`` means the criterion is an
    # absence check ("X must NOT be present"), so a *miss* is the passing
    # outcome. ``present`` (default) keeps the positive match semantics.
    expect = str(result.get("expect") or "present").strip().lower()
    result["ok"] = (not hit) if expect == "absent" else hit
    result["verified"] = True
    result["matched_lines"] = _count_matches(text, pattern) if hit else 0
    return result


def _count_matches(text: str, pattern: str) -> int:
    try:
        return len(re.findall(pattern, text))
    except re.error:
        return 0


def emit_goal_acceptance_pending(
    *,
    log_path: Path,
    goal_id: str,
    acceptance_gaps: Sequence[Mapping[str, Any]],
    agent_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Emit a ``goal_acceptance_pending`` audit event (idempotent by goal+kind).

    The goal is NOT closable until the acceptance gaps are resolved.
    """
    event = build_rollout_event(
        goal_id=goal_id,
        event_kind="goal_acceptance_pending",
        agent_id=agent_id,
        recorded_at=recorded_at,
    )
    event["acceptance_gaps"] = list(acceptance_gaps)
    appended, _is_new = append_rollout_event_once(
        Path(log_path),
        event,
        identity_fields=("goal_id", "event_kind"),
    )
    return appended


def emit_goal_acceptance_satisfied(
    *,
    log_path: Path,
    goal_id: str,
    criteria_results: Sequence[Mapping[str, Any]],
    agent_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Emit a ``goal_acceptance_satisfied`` audit event (idempotent by goal+kind)."""
    event = build_rollout_event(
        goal_id=goal_id,
        event_kind="goal_acceptance_satisfied",
        agent_id=agent_id,
        recorded_at=recorded_at,
    )
    event["criteria_results"] = list(criteria_results)
    appended, _is_new = append_rollout_event_once(
        Path(log_path),
        event,
        identity_fields=("goal_id", "event_kind"),
    )
    return appended


def acceptance_blocker(
    acceptance: Mapping[str, Any] | None,
) -> str | None:
    """Return a closure-blocker reason when acceptance is not satisfied, else None.

    Designed to be folded into ``is_goal_closable`` / ``goal_closure_reason`` so
    a goal with unsatisfied acceptance criteria is treated as NOT closable.
    """
    if not isinstance(acceptance, dict):
        return None
    if acceptance.get("satisfied") is True:
        return None
    gaps = acceptance.get("acceptance_gaps") or []
    return "acceptance_gaps_remaining" if gaps else "acceptance_not_verified"


__all__ = [
    "GOAL_ACCEPTANCE_EVALUATION_SCHEMA_VERSION",
    "GOAL_ACCEPTANCE_CRITERIA_SCHEMA_VERSION",
    "EVIDENCE_KIND_GREP",
    "EVIDENCE_KIND_SNAPSHOT",
    "EVIDENCE_KIND_TEST",
    "EVIDENCE_KIND_FILE",
    "EVIDENCE_KIND_MANUAL",
    "EVIDENCE_KINDS",
    "normalize_acceptance_criteria",
    "normalize_evidence",
    "verify_criterion",
    "evaluate_goal_acceptance",
    "build_grep_evidence",
    "build_manual_evidence",
    "emit_goal_acceptance_pending",
    "emit_goal_acceptance_satisfied",
    "acceptance_blocker",
]

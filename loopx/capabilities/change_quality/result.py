from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from ...feedback import validate_public_safe_text


CHANGE_QUALITY_RESULT_SCHEMA_VERSION = "change_quality_agent_result_v1"
FINDING_SEVERITIES = frozenset({"blocker", "warning", "advisory"})
LENS_STATUSES = frozenset({"checked", "finding", "not_applicable"})
SIMPLIFICATION_OUTCOMES = frozenset({"fixed", "retained", "deferred", "not_applicable"})
VALIDATION_STATUSES = frozenset({"passed", "failed", "skipped"})
EVIDENCE_REF_KINDS = frozenset(
    {"path", "instruction", "finding", "validator", "decision"}
)
REVIEW_LENSES = (
    {
        "lens_id": "reuse",
        "question": (
            "Does the change reuse established helpers and durable knowledge "
            "instead of duplicating them?"
        ),
    },
    {
        "lens_id": "type_api_boundary",
        "question": (
            "Are types, schemas, compatibility windows, and caller-facing "
            "contracts explicit and coherent?"
        ),
    },
    {
        "lens_id": "configuration",
        "question": (
            "Does configuration stay single-sourced, validated, and free of "
            "hidden mode coupling?"
        ),
    },
    {
        "lens_id": "runtime_ownership",
        "question": (
            "Are lifecycle, concurrency, state, and side-effect ownership "
            "placed in the correct runtime boundary?"
        ),
    },
    {
        "lens_id": "quality_simplification",
        "question": (
            "Can the final behavior be expressed with less indirection, "
            "branching, duplication, or speculative abstraction?"
        ),
    },
    {
        "lens_id": "efficiency",
        "question": (
            "Does the change avoid unnecessary work, unbounded growth, and "
            "avoidable hot-path cost?"
        ),
    },
    {
        "lens_id": "error_supervision",
        "question": (
            "Are failures observable, actionable, and supervised without "
            "silent fallback or broad exception plumbing?"
        ),
    },
    {
        "lens_id": "test_validation",
        "question": (
            "Do tests and repository-native validators prove the intended "
            "semantics, including important negative paths?"
        ),
    },
    {
        "lens_id": "documentation_comments",
        "question": (
            "Do names, comments, and docs explain the current contract without "
            "stale narration or duplicated truth?"
        ),
    },
    {
        "lens_id": "security_release",
        "question": (
            "Are security, privacy, permissions, migrations, and release "
            "compatibility handled at the changed boundaries?"
        ),
    },
)
REVIEW_LENS_IDS = tuple(item["lens_id"] for item in REVIEW_LENSES)


def _bounded_text(value: Any, *, field: str, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    validate_public_safe_text(field, text)
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _relative_path(value: Any, *, field: str) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a repo-relative path")
    validate_public_safe_text(field, text)
    return path.as_posix()


def _normalize_finding(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"findings[{index}] must be an object")
    severity = str(value.get("severity") or "").strip().lower()
    if severity not in FINDING_SEVERITIES:
        raise ValueError(
            f"findings[{index}].severity must be one of {sorted(FINDING_SEVERITIES)}"
        )
    code = _bounded_text(
        value.get("code"),
        field=f"findings[{index}].code",
        limit=80,
    )
    message = _bounded_text(
        value.get("message"),
        field=f"findings[{index}].message",
        limit=320,
    )
    if not code or not message:
        raise ValueError(f"findings[{index}] requires code and message")
    finding = {
        "severity": severity,
        "code": code,
        "message": message,
        "resolved": value.get("resolved") is True,
    }
    path = _relative_path(value.get("path"), field=f"findings[{index}].path")
    if path:
        finding["path"] = path
    line = value.get("line")
    if line is not None:
        if not isinstance(line, int) or line < 1:
            raise ValueError(f"findings[{index}].line must be a positive integer")
        finding["line"] = line
    return finding


def _bounded_text_list(
    value: Any,
    *,
    field: str,
    item_limit: int,
    count_limit: int,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    if len(value) > count_limit:
        raise ValueError(f"{field} supports at most {count_limit} items")
    result = [
        _bounded_text(item, field=f"{field}[]", limit=item_limit) for item in value
    ]
    if any(not item for item in result):
        raise ValueError(f"{field} cannot contain empty values")
    return result


def _normalize_evidence_ref(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field, limit=400)
    kind, separator, target = text.partition(":")
    if not separator or kind not in EVIDENCE_REF_KINDS:
        raise ValueError(
            f"{field} must use one of "
            f"{[f'{item}:<ref>' for item in sorted(EVIDENCE_REF_KINDS)]}"
        )
    if kind in {"path", "instruction"}:
        normalized_target = _relative_path(target, field=field)
    else:
        normalized_target = _bounded_text(target, field=field, limit=160)
    if not normalized_target:
        raise ValueError(f"{field} requires a non-empty reference target")
    return f"{kind}:{normalized_target}"


def _normalize_repository_principle(value: Any, *, index: int) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"repository_principles[{index}] must be an object")
    source = _relative_path(
        value.get("source"),
        field=f"repository_principles[{index}].source",
    )
    principle = _bounded_text(
        value.get("principle"),
        field=f"repository_principles[{index}].principle",
        limit=320,
    )
    if not source or not principle:
        raise ValueError(
            f"repository_principles[{index}] requires source and principle"
        )
    return {"source": source, "principle": principle}


def _normalize_lens_review(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"lens_reviews[{index}] must be an object")
    lens_id = str(value.get("lens_id") or "").strip()
    if lens_id not in REVIEW_LENS_IDS:
        raise ValueError(f"lens_reviews[{index}].lens_id is not a required lens")
    status = str(value.get("status") or "").strip().lower()
    if status not in LENS_STATUSES:
        raise ValueError(
            f"lens_reviews[{index}].status must be one of {sorted(LENS_STATUSES)}"
        )
    summary = _bounded_text(
        value.get("summary"),
        field=f"lens_reviews[{index}].summary",
        limit=320,
    )
    if not summary:
        raise ValueError(f"lens_reviews[{index}].summary is required")
    finding_codes = _bounded_text_list(
        value.get("finding_codes"),
        field=f"lens_reviews[{index}].finding_codes",
        item_limit=80,
        count_limit=10,
    )
    if status == "finding" and not finding_codes:
        raise ValueError(
            f"lens_reviews[{index}] with status=finding requires finding_codes"
        )
    if status != "finding" and finding_codes:
        raise ValueError(
            f"lens_reviews[{index}] may reference findings only with status=finding"
        )
    evidence_refs = [
        _normalize_evidence_ref(
            item,
            field=f"lens_reviews[{index}].evidence_refs[]",
        )
        for item in _bounded_text_list(
            value.get("evidence_refs"),
            field=f"lens_reviews[{index}].evidence_refs",
            item_limit=400,
            count_limit=20,
        )
    ]
    if status == "not_applicable" and evidence_refs:
        raise ValueError(
            f"lens_reviews[{index}] with status=not_applicable cannot cite evidence"
        )
    if status != "not_applicable" and not evidence_refs:
        raise ValueError(
            f"lens_reviews[{index}] with status={status} requires evidence_refs"
        )
    return {
        "lens_id": lens_id,
        "status": status,
        "summary": summary,
        "finding_codes": finding_codes,
        "evidence_refs": evidence_refs,
    }


def _normalize_simplification_decision(
    value: Any,
    *,
    index: int,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"simplification_decisions[{index}] must be an object")
    decision_id = _bounded_text(
        value.get("decision_id"),
        field=f"simplification_decisions[{index}].decision_id",
        limit=80,
    )
    outcome = str(value.get("outcome") or "").strip().lower()
    if outcome not in SIMPLIFICATION_OUTCOMES:
        raise ValueError(
            "simplification_decisions"
            f"[{index}].outcome must be one of {sorted(SIMPLIFICATION_OUTCOMES)}"
        )
    subject = _bounded_text(
        value.get("subject"),
        field=f"simplification_decisions[{index}].subject",
        limit=160,
    )
    reason = _bounded_text(
        value.get("reason"),
        field=f"simplification_decisions[{index}].reason",
        limit=320,
    )
    if not decision_id or not subject or not reason:
        raise ValueError(
            f"simplification_decisions[{index}] requires decision_id, subject, and reason"
        )
    decision = {
        "decision_id": decision_id,
        "subject": subject,
        "outcome": outcome,
        "reason": reason,
    }
    path = _relative_path(
        value.get("path"),
        field=f"simplification_decisions[{index}].path",
    )
    if path:
        decision["path"] = path
    line = value.get("line")
    if line is not None:
        if not isinstance(line, int) or line < 1:
            raise ValueError(
                f"simplification_decisions[{index}].line must be a positive integer"
            )
        decision["line"] = line
    return decision


def _normalize_validation_evidence(value: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"validation_evidence[{index}] must be an object")
    status = str(value.get("status") or "").strip().lower()
    if status not in VALIDATION_STATUSES:
        raise ValueError(
            f"validation_evidence[{index}].status must be one of "
            f"{sorted(VALIDATION_STATUSES)}"
        )
    validator = _bounded_text(
        value.get("validator"),
        field=f"validation_evidence[{index}].validator",
        limit=120,
    )
    scope = _bounded_text(
        value.get("scope"),
        field=f"validation_evidence[{index}].scope",
        limit=240,
    )
    if not validator or not scope:
        raise ValueError(f"validation_evidence[{index}] requires validator and scope")
    evidence = {"validator": validator, "status": status, "scope": scope}
    command = _bounded_text(
        value.get("command"),
        field=f"validation_evidence[{index}].command",
        limit=320,
    )
    reason = _bounded_text(
        value.get("reason"),
        field=f"validation_evidence[{index}].reason",
        limit=320,
    )
    if command:
        evidence["command"] = command
    if reason:
        evidence["reason"] = reason
    if status in {"failed", "skipped"} and not reason:
        raise ValueError(
            f"validation_evidence[{index}] with status={status} requires reason"
        )
    return evidence


def normalize_change_quality_result(
    value: Any,
    *,
    expected_fingerprint: str,
    safe_fix_allowed: bool,
    expected_changed_files: list[str] | None = None,
    expected_instruction_refs: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("result JSON root must be an object")
    if value.get("schema_version") != CHANGE_QUALITY_RESULT_SCHEMA_VERSION:
        raise ValueError(
            f"result schema_version must be {CHANGE_QUALITY_RESULT_SCHEMA_VERSION}"
        )
    fingerprint = str(value.get("scope_fingerprint") or "").strip()
    if fingerprint != expected_fingerprint:
        raise ValueError(
            "result scope_fingerprint does not match the current exact diff; "
            "rerun prepare after every safe fix"
        )
    if value.get("reviewed_final_scope") is not True:
        raise ValueError("result must set reviewed_final_scope=true")
    safe_fix_applied = value.get("safe_fix_applied") is True
    if safe_fix_applied and not safe_fix_allowed:
        raise ValueError(
            "result reports safe_fix_applied but goal policy forbids safe fixes"
        )
    safe_fix_passes = value.get("safe_fix_passes", 0)
    if not isinstance(safe_fix_passes, int) or safe_fix_passes not in {0, 1}:
        raise ValueError("safe_fix_passes must be 0 or 1")
    if safe_fix_applied and safe_fix_passes != 1:
        raise ValueError("safe_fix_applied=true requires safe_fix_passes=1")
    if not safe_fix_applied and safe_fix_passes != 0:
        raise ValueError("safe_fix_passes=1 requires safe_fix_applied=true")
    raw_principles = value.get("repository_principles")
    if not isinstance(raw_principles, list):
        raise ValueError("repository_principles must be an array")
    if len(raw_principles) > 20:
        raise ValueError("repository_principles supports at most 20 items")
    repository_principles = [
        _normalize_repository_principle(item, index=index)
        for index, item in enumerate(raw_principles)
    ]
    principle_sources = [item["source"] for item in repository_principles]
    if len(set(principle_sources)) != len(principle_sources):
        raise ValueError("repository_principles must not repeat a source")
    if expected_instruction_refs is not None:
        expected_sources = set(expected_instruction_refs)
        actual_sources = set(principle_sources)
        if actual_sources != expected_sources:
            missing_sources = sorted(expected_sources - actual_sources)
            unknown_sources = sorted(actual_sources - expected_sources)
            raise ValueError(
                "repository_principles must cover the projected instruction refs; "
                f"missing={missing_sources} unknown={unknown_sources}"
            )
    findings = [
        _normalize_finding(item, index=index)
        for index, item in enumerate(value.get("findings") or [])
    ]
    if len(findings) > 20:
        raise ValueError("result supports at most 20 findings")
    finding_codes = [str(item["code"]) for item in findings]
    if len(set(finding_codes)) != len(finding_codes):
        raise ValueError("finding codes must be unique")

    lens_values = value.get("lens_reviews")
    if not isinstance(lens_values, list):
        raise ValueError("lens_reviews must be an array")
    lens_reviews = [
        _normalize_lens_review(item, index=index)
        for index, item in enumerate(lens_values)
    ]
    lens_map = {item["lens_id"]: item for item in lens_reviews}
    if len(lens_map) != len(lens_reviews):
        raise ValueError("lens_reviews must not contain duplicate lens_id values")
    missing_lenses = [lens_id for lens_id in REVIEW_LENS_IDS if lens_id not in lens_map]
    if missing_lenses:
        raise ValueError(f"lens_reviews missing required lenses: {missing_lenses}")
    summaries = [item["summary"] for item in lens_reviews]
    if len(set(summaries)) != len(summaries):
        raise ValueError(
            "lens_reviews must contain lens-specific summaries, not a repeated generic all-clear"
        )
    if not any(item["status"] != "not_applicable" for item in lens_reviews):
        raise ValueError("at least one review lens must be applicable")
    referenced_codes = {code for lens in lens_reviews for code in lens["finding_codes"]}
    unknown_codes = sorted(referenced_codes - set(finding_codes))
    if unknown_codes:
        raise ValueError(
            f"lens_reviews reference unknown finding codes: {unknown_codes}"
        )
    unclassified_codes = sorted(set(finding_codes) - referenced_codes)
    if unclassified_codes:
        raise ValueError(
            f"findings must be classified by at least one lens: {unclassified_codes}"
        )

    raw_decisions = value.get("simplification_decisions")
    if not isinstance(raw_decisions, list) or not raw_decisions:
        raise ValueError("simplification_decisions must contain at least one item")
    if len(raw_decisions) > 20:
        raise ValueError("simplification_decisions supports at most 20 items")
    simplification_decisions = [
        _normalize_simplification_decision(item, index=index)
        for index, item in enumerate(raw_decisions)
    ]
    decision_ids = [item["decision_id"] for item in simplification_decisions]
    if len(set(decision_ids)) != len(decision_ids):
        raise ValueError("simplification decision ids must be unique")
    fixed_decisions = [
        item for item in simplification_decisions if item["outcome"] == "fixed"
    ]
    if safe_fix_applied and not fixed_decisions:
        raise ValueError(
            "safe_fix_applied=true requires a simplification decision with outcome=fixed"
        )
    if fixed_decisions and not safe_fix_applied:
        raise ValueError(
            "simplification decision outcome=fixed requires safe_fix_applied=true"
        )

    raw_validation = value.get("validation_evidence")
    if not isinstance(raw_validation, list) or not raw_validation:
        raise ValueError("validation_evidence must contain at least one item")
    if len(raw_validation) > 20:
        raise ValueError("validation_evidence supports at most 20 items")
    validation_evidence = [
        _normalize_validation_evidence(item, index=index)
        for index, item in enumerate(raw_validation)
    ]
    validator_ids = [item["validator"] for item in validation_evidence]
    if len(set(validator_ids)) != len(validator_ids):
        raise ValueError("validation_evidence validator ids must be unique")
    evidence_targets = {
        "path": set(expected_changed_files or []),
        "instruction": set(principle_sources),
        "finding": set(finding_codes),
        "validator": set(validator_ids),
        "decision": set(decision_ids),
    }
    for lens in lens_reviews:
        refs_by_kind: dict[str, set[str]] = {}
        for evidence_ref in lens["evidence_refs"]:
            kind, target = evidence_ref.split(":", 1)
            refs_by_kind.setdefault(kind, set()).add(target)
            if kind != "path" and target not in evidence_targets[kind]:
                raise ValueError(
                    f"lens {lens['lens_id']} references unknown evidence: {evidence_ref}"
                )
            if (
                kind == "path"
                and expected_changed_files is not None
                and target not in evidence_targets["path"]
            ):
                raise ValueError(
                    f"lens {lens['lens_id']} references unchanged path: {target}"
                )
        if lens["status"] == "finding" and not set(lens["finding_codes"]).issubset(
            refs_by_kind.get("finding", set())
        ):
            raise ValueError(
                f"lens {lens['lens_id']} must anchor each finding_code with finding:<code>"
            )
        if (
            lens["lens_id"] == "quality_simplification"
            and lens["status"] != "not_applicable"
            and not refs_by_kind.get("decision")
        ):
            raise ValueError(
                "quality_simplification lens requires a decision:<decision_id> reference"
            )
        if (
            lens["lens_id"] == "test_validation"
            and lens["status"] != "not_applicable"
            and not refs_by_kind.get("validator")
        ):
            raise ValueError(
                "test_validation lens requires a validator:<validator> reference"
            )
    summary = _bounded_text(value.get("summary"), field="summary", limit=500)
    if not summary:
        raise ValueError("summary is required")
    return {
        "schema_version": CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
        "scope_fingerprint": fingerprint,
        "reviewed_final_scope": True,
        "summary": summary,
        "repository_principles": repository_principles,
        "findings": findings,
        "lens_reviews": [lens_map[lens_id] for lens_id in REVIEW_LENS_IDS],
        "simplification_decisions": simplification_decisions,
        "safe_fix_applied": safe_fix_applied,
        "safe_fix_passes": safe_fix_passes,
        "validation_evidence": validation_evidence,
    }


def change_quality_result_decision(
    result: dict[str, Any],
) -> tuple[str, list[str]]:
    unresolved_blockers = [
        str(item["code"])
        for item in result["findings"]
        if item["severity"] == "blocker" and item["resolved"] is not True
    ]
    failed_validators = [
        f"validator:{item['validator']}"
        for item in result["validation_evidence"]
        if item["status"] == "failed"
    ]
    unresolved = [*unresolved_blockers, *failed_validators]
    return ("fail", unresolved) if unresolved else ("pass", [])

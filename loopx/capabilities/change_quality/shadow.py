from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from ...feedback import validate_public_safe_text
from .result import (
    REVIEW_LENSES,
    SIMPLIFY_GUARDRAIL_LENS_IDS,
    SIMPLIFY_PRIMARY_LENS_IDS,
)


CHANGE_QUALITY_SHADOW_MATRIX_SCHEMA_VERSION = "change_quality_shadow_matrix_v0"
CHANGE_QUALITY_SHADOW_RESULT_SCHEMA_VERSION = "change_quality_shadow_result_v0"
CHANGE_QUALITY_SHADOW_RECEIPT_SCHEMA_VERSION = "change_quality_shadow_receipt_v0"
CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS = ("v0", "v1")
CHANGE_QUALITY_SHADOW_CASE_KINDS = (
    "real_pr_clean",
    "real_pr_adversarial",
    "synthetic_simplification",
)
CHANGE_QUALITY_SHADOW_FINDING_CLASSES = (
    "correctness",
    "security_privacy",
    "api_contract",
    "validation",
    "complexity",
    "efficiency",
    "error_supervision",
    "documentation",
    "release_compatibility",
)
CHANGE_QUALITY_SHADOW_SAFE_FIX_ACTIONS = ("none", "bounded", "manual")
CHANGE_QUALITY_SHADOW_SIMPLIFICATION_OUTCOMES = ("retain", "simplify", "hold")

_V0_REVIEW_RULES = (
    "correctness and behavioral regressions",
    "security, privacy, authority, and public/private boundaries",
    "caller contracts, schemas, migrations, and state transitions",
    "validation required by the changed surface",
    "unnecessary complexity, duplicated knowledge, and speculative abstraction",
    "language- and framework-specific issues exposed by repository tools",
)


def _bounded_text(value: Any, *, field: str, limit: int) -> str:
    text = " ".join(str(value or "").strip().split())
    validate_public_safe_text(field, text)
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return text


def _token(value: Any, *, field: str, allowed: tuple[str, ...] | None = None) -> str:
    token = _bounded_text(value, field=field, limit=80)
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in token
    ):
        raise ValueError(f"{field} must be a compact lowercase token")
    if allowed is not None and token not in allowed:
        raise ValueError(f"{field} must be one of {list(allowed)}")
    return token


def _relative_path(value: Any, *, field: str) -> str:
    text = _bounded_text(value, field=field, limit=240).replace("\\", "/")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field} must be a repo-relative path")
    return path.as_posix()


def _text_list(
    value: Any,
    *,
    field: str,
    count_limit: int,
    item_limit: int,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    if len(value) > count_limit:
        raise ValueError(f"{field} supports at most {count_limit} items")
    return [_bounded_text(item, field=f"{field}[]", limit=item_limit) for item in value]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def load_change_quality_shadow_matrix(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("shadow matrix root must be an object")
    if raw.get("schema_version") != CHANGE_QUALITY_SHADOW_MATRIX_SCHEMA_VERSION:
        raise ValueError("shadow matrix must use change_quality_shadow_matrix_v0")
    raw_cases = raw.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("shadow matrix cases must be a non-empty array")
    if len(raw_cases) > 16:
        raise ValueError("shadow matrix supports at most 16 cases")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, Mapping):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = _token(raw_case.get("case_id"), field=f"cases[{index}].case_id")
        if case_id in seen_ids:
            raise ValueError(f"duplicate shadow case id: {case_id}")
        seen_ids.add(case_id)
        kind = _token(
            raw_case.get("kind"),
            field=f"cases[{index}].kind",
            allowed=CHANGE_QUALITY_SHADOW_CASE_KINDS,
        )
        language = _token(
            raw_case.get("language"),
            field=f"cases[{index}].language",
        )
        changed_files = [
            _relative_path(item, field=f"cases[{index}].changed_files[]")
            for item in _text_list(
                raw_case.get("changed_files"),
                field=f"cases[{index}].changed_files",
                count_limit=40,
                item_limit=240,
            )
        ]
        if not changed_files:
            raise ValueError(f"cases[{index}].changed_files cannot be empty")
        source = raw_case.get("source")
        if not isinstance(source, Mapping):
            raise ValueError(f"cases[{index}].source must be an object")
        normalized_source: dict[str, Any]
        if kind.startswith("real_pr_"):
            pull_request = source.get("pull_request")
            if not isinstance(pull_request, int) or pull_request < 1:
                raise ValueError(f"cases[{index}].source.pull_request must be positive")
            normalized_source = {
                "pull_request": pull_request,
                "base_ref": _bounded_text(
                    source.get("base_ref"),
                    field=f"cases[{index}].source.base_ref",
                    limit=64,
                ),
                "head_ref": _bounded_text(
                    source.get("head_ref"),
                    field=f"cases[{index}].source.head_ref",
                    limit=64,
                ),
            }
        else:
            normalized_source = {
                "fixture_root": _relative_path(
                    source.get("fixture_root"),
                    field=f"cases[{index}].source.fixture_root",
                ),
                "validator": _bounded_text(
                    source.get("validator"),
                    field=f"cases[{index}].source.validator",
                    limit=240,
                ),
            }
        gold = raw_case.get("gold")
        if not isinstance(gold, Mapping):
            raise ValueError(f"cases[{index}].gold must be an object")
        expected_findings: list[dict[str, str]] = []
        raw_findings = gold.get("findings")
        if not isinstance(raw_findings, list) or len(raw_findings) > 8:
            raise ValueError(f"cases[{index}].gold.findings must be an array")
        for finding_index, finding in enumerate(raw_findings):
            if not isinstance(finding, Mapping):
                raise ValueError(
                    f"cases[{index}].gold.findings[{finding_index}] must be an object"
                )
            expected_findings.append(
                {
                    "finding_class": _token(
                        finding.get("finding_class"),
                        field=(
                            f"cases[{index}].gold.findings[{finding_index}]"
                            ".finding_class"
                        ),
                        allowed=CHANGE_QUALITY_SHADOW_FINDING_CLASSES,
                    ),
                    "path": _relative_path(
                        finding.get("path"),
                        field=f"cases[{index}].gold.findings[{finding_index}].path",
                    ),
                }
            )
        cases.append(
            {
                "case_id": case_id,
                "kind": kind,
                "language": language,
                "changed_files": changed_files,
                "source": normalized_source,
                "gold": {
                    "findings": expected_findings,
                    "safe_fix_action": _token(
                        gold.get("safe_fix_action"),
                        field=f"cases[{index}].gold.safe_fix_action",
                        allowed=CHANGE_QUALITY_SHADOW_SAFE_FIX_ACTIONS,
                    ),
                    "simplification_outcome": _token(
                        gold.get("simplification_outcome"),
                        field=f"cases[{index}].gold.simplification_outcome",
                        allowed=CHANGE_QUALITY_SHADOW_SIMPLIFICATION_OUTCOMES,
                    ),
                },
            }
        )
    return {
        "schema_version": CHANGE_QUALITY_SHADOW_MATRIX_SCHEMA_VERSION,
        "cases": cases,
    }


def change_quality_shadow_output_schema() -> dict[str, Any]:
    finding_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "finding_class",
            "severity",
            "code",
            "path",
            "line",
            "message",
        ],
        "properties": {
            "finding_class": {
                "type": "string",
                "enum": list(CHANGE_QUALITY_SHADOW_FINDING_CLASSES),
            },
            "severity": {
                "type": "string",
                "enum": ["blocker", "warning", "advisory"],
            },
            "code": {
                "type": "string",
                "pattern": "^[a-z0-9][a-z0-9_-]{0,79}$",
            },
            "path": {"type": "string", "maxLength": 240},
            "line": {
                "anyOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "null"},
                ]
            },
            "message": {"type": "string", "maxLength": 320},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "case_id",
            "contract_version",
            "summary",
            "findings",
            "reviewed_lenses",
            "simplification",
            "safe_fix",
            "validation_commands",
        ],
        "properties": {
            "schema_version": {
                "type": "string",
                "const": CHANGE_QUALITY_SHADOW_RESULT_SCHEMA_VERSION,
            },
            "case_id": {"type": "string", "maxLength": 80},
            "contract_version": {
                "type": "string",
                "enum": list(CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS),
            },
            "summary": {"type": "string", "maxLength": 500},
            "findings": {
                "type": "array",
                "maxItems": 12,
                "items": finding_schema,
            },
            "reviewed_lenses": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "maxLength": 80},
            },
            "simplification": {
                "type": "object",
                "additionalProperties": False,
                "required": ["outcome", "reason"],
                "properties": {
                    "outcome": {
                        "type": "string",
                        "enum": list(CHANGE_QUALITY_SHADOW_SIMPLIFICATION_OUTCOMES),
                    },
                    "reason": {"type": "string", "maxLength": 320},
                },
            },
            "safe_fix": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "reason"],
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": list(CHANGE_QUALITY_SHADOW_SAFE_FIX_ACTIONS),
                    },
                    "reason": {"type": "string", "maxLength": 320},
                },
            },
            "validation_commands": {
                "type": "array",
                "maxItems": 12,
                "items": {"type": "string", "maxLength": 240},
            },
        },
    }


def build_change_quality_shadow_prompt(
    case: Mapping[str, Any],
    *,
    contract_version: str,
) -> str:
    if contract_version not in CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS:
        raise ValueError("unknown change-quality shadow contract version")
    source = dict(case["source"])
    if case["kind"].startswith("real_pr_"):
        scope = (
            f"Review commit range {source['base_ref']}..{source['head_ref']}. "
            "Use git diff and repository files to inspect the exact change."
        )
    else:
        scope = (
            "Review the current HEAD against HEAD^. This is an isolated public "
            "fixture repository; repository-native validators may be run."
        )
    if contract_version == "v0":
        review_contract = (
            "Apply the v0 review contract. Check: "
            + "; ".join(_V0_REVIEW_RULES)
            + ". In reviewed_lenses, list concise lowercase tokens for only "
            "the dimensions you actually checked; no canonical lens list is supplied."
        )
    else:
        primary_lenses = [
            item
            for item in REVIEW_LENSES
            if item["lens_id"] in SIMPLIFY_PRIMARY_LENS_IDS
        ]
        rendered_lenses = "; ".join(
            f"{item['lens_id']}: {item['question']}" for item in primary_lenses
        )
        review_contract = (
            "Apply the v1 simplify-first contract. Spend the review budget on the "
            "two primary lenses and return both exact lens_id values in "
            f"reviewed_lenses: {rendered_lenses}. Other guardrail lenses are "
            f"{', '.join(SIMPLIFY_GUARDRAIL_LENS_IDS)}; include one only when "
            "the changed surface, repository instructions, validator evidence, "
            "or proposed simplification raises a concrete risk."
        )
    return "\n".join(
        [
            "You are a no-delivery code-quality shadow evaluator.",
            scope,
            f"Case id: {case['case_id']}.",
            f"Changed files: {', '.join(case['changed_files'])}.",
            review_contract,
            "Read applicable AGENTS.md or repository instructions before judging.",
            "Do not modify tracked files, create commits, push, comment, or merge.",
            (
                "Findings must be concrete and grounded in the changed scope. "
                "A clean refactor must not receive speculative findings."
            ),
            (
                "safe_fix.action=bounded only when one behavior-preserving repair "
                "inside the exact scope is clear; use manual for intent, authority, "
                "migration, or risky changes; otherwise use none."
            ),
            (
                "simplification.outcome=retain when the final shape is already "
                "cohesive, simplify when a concrete smaller expression is warranted, "
                "and hold when owner judgment is required."
            ),
            "Return only the requested JSON object.",
        ]
    )


def normalize_change_quality_shadow_result(
    value: Any,
    *,
    case: Mapping[str, Any],
    contract_version: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("shadow result must be an object")
    if value.get("schema_version") != CHANGE_QUALITY_SHADOW_RESULT_SCHEMA_VERSION:
        raise ValueError("shadow result schema_version is invalid")
    if value.get("case_id") != case["case_id"]:
        raise ValueError("shadow result case_id does not match")
    if value.get("contract_version") != contract_version:
        raise ValueError("shadow result contract_version does not match")
    findings: list[dict[str, Any]] = []
    raw_findings = value.get("findings")
    if not isinstance(raw_findings, list) or len(raw_findings) > 12:
        raise ValueError("shadow result findings must be a bounded array")
    finding_codes: set[str] = set()
    for index, raw_finding in enumerate(raw_findings):
        if not isinstance(raw_finding, Mapping):
            raise ValueError(f"findings[{index}] must be an object")
        code = _token(raw_finding.get("code"), field=f"findings[{index}].code")
        if code in finding_codes:
            raise ValueError("finding codes must be unique")
        finding_codes.add(code)
        line = raw_finding.get("line")
        if line is not None and (not isinstance(line, int) or line < 1):
            raise ValueError(f"findings[{index}].line must be positive or null")
        findings.append(
            {
                "finding_class": _token(
                    raw_finding.get("finding_class"),
                    field=f"findings[{index}].finding_class",
                    allowed=CHANGE_QUALITY_SHADOW_FINDING_CLASSES,
                ),
                "severity": _token(
                    raw_finding.get("severity"),
                    field=f"findings[{index}].severity",
                    allowed=("blocker", "warning", "advisory"),
                ),
                "code": code,
                "path": _relative_path(
                    raw_finding.get("path"),
                    field=f"findings[{index}].path",
                ),
                "line": line,
                "message": _bounded_text(
                    raw_finding.get("message"),
                    field=f"findings[{index}].message",
                    limit=320,
                ),
            }
        )
    reviewed_lenses = []
    for item in _text_list(
        value.get("reviewed_lenses"),
        field="reviewed_lenses",
        count_limit=20,
        item_limit=80,
    ):
        lens = item.strip().lower().replace("-", "_").replace(" ", "_")
        if lens not in reviewed_lenses:
            reviewed_lenses.append(lens)
    simplification = value.get("simplification")
    safe_fix = value.get("safe_fix")
    if not isinstance(simplification, Mapping) or not isinstance(safe_fix, Mapping):
        raise ValueError("simplification and safe_fix must be objects")
    validation_commands = _text_list(
        value.get("validation_commands"),
        field="validation_commands",
        count_limit=12,
        item_limit=240,
    )
    return {
        "schema_version": CHANGE_QUALITY_SHADOW_RESULT_SCHEMA_VERSION,
        "case_id": case["case_id"],
        "contract_version": contract_version,
        "summary": _bounded_text(value.get("summary"), field="summary", limit=500),
        "findings": findings,
        "reviewed_lenses": reviewed_lenses,
        "simplification": {
            "outcome": _token(
                simplification.get("outcome"),
                field="simplification.outcome",
                allowed=CHANGE_QUALITY_SHADOW_SIMPLIFICATION_OUTCOMES,
            ),
            "reason": _bounded_text(
                simplification.get("reason"),
                field="simplification.reason",
                limit=320,
            ),
        },
        "safe_fix": {
            "action": _token(
                safe_fix.get("action"),
                field="safe_fix.action",
                allowed=CHANGE_QUALITY_SHADOW_SAFE_FIX_ACTIONS,
            ),
            "reason": _bounded_text(
                safe_fix.get("reason"),
                field="safe_fix.reason",
                limit=320,
            ),
        },
        "validation_commands": validation_commands,
    }


def grade_change_quality_shadow_result(
    result: Mapping[str, Any],
    *,
    case: Mapping[str, Any],
    tracked_files_modified: bool = False,
) -> dict[str, Any]:
    expected = {
        (item["finding_class"], item["path"]) for item in case["gold"]["findings"]
    }
    predicted = {(item["finding_class"], item["path"]) for item in result["findings"]}
    matched = expected & predicted
    false_positives = predicted - expected
    false_negatives = expected - predicted
    reviewed = set(result["reviewed_lenses"])
    required_lenses = set(SIMPLIFY_PRIMARY_LENS_IDS)
    return {
        "case_id": case["case_id"],
        "contract_version": result["contract_version"],
        "result_digest": _digest(dict(result)),
        "expected_finding_count": len(expected),
        "predicted_finding_count": len(predicted),
        "matched_finding_count": len(matched),
        "false_positive_count": len(false_positives),
        "false_negative_count": len(false_negatives),
        "lens_coverage_count": len(reviewed & required_lenses),
        "lens_required_count": len(required_lenses),
        "safe_fix_match": (
            result["safe_fix"]["action"] == case["gold"]["safe_fix_action"]
        ),
        "simplification_match": (
            result["simplification"]["outcome"]
            == case["gold"]["simplification_outcome"]
        ),
        "tracked_files_modified": tracked_files_modified,
    }


def build_change_quality_shadow_receipt(
    *,
    matrix: Mapping[str, Any],
    declared_matrix: Mapping[str, Any],
    runs: Sequence[Mapping[str, Any]],
    model_ref: str,
    source_commit: str,
) -> dict[str, Any]:
    case_count = len(matrix["cases"])
    expected_case_ids = sorted(case["case_id"] for case in matrix["cases"])
    matrix_digest = _digest(dict(matrix))
    declared_matrix_digest = _digest(dict(declared_matrix))
    arms: dict[str, dict[str, Any]] = {}
    for version in CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS:
        selected = [dict(item) for item in runs if item["contract_version"] == version]
        valid = [item for item in selected if item.get("valid") is True]
        matched = sum(int(item.get("matched_finding_count") or 0) for item in valid)
        predicted = sum(int(item.get("predicted_finding_count") or 0) for item in valid)
        expected = sum(int(item.get("expected_finding_count") or 0) for item in valid)
        false_positives = sum(
            int(item.get("false_positive_count") or 0) for item in valid
        )
        false_negatives = sum(
            int(item.get("false_negative_count") or 0) for item in valid
        )
        lens_covered = sum(int(item.get("lens_coverage_count") or 0) for item in valid)
        lens_required = sum(int(item.get("lens_required_count") or 0) for item in valid)
        input_tokens = sum(int(item.get("input_tokens") or 0) for item in selected)
        output_tokens = sum(int(item.get("output_tokens") or 0) for item in selected)
        latency_ms = sum(int(item.get("latency_ms") or 0) for item in selected)
        arms[version] = {
            "run_count": len(selected),
            "valid_count": len(valid),
            "precision": round(matched / predicted, 4) if predicted else 1.0,
            "recall": round(matched / expected, 4) if expected else 1.0,
            "false_positive_count": false_positives,
            "false_negative_count": false_negatives,
            "primary_lens_completeness": (
                round(lens_covered / lens_required, 4) if lens_required else 0.0
            ),
            "safe_fix_accuracy": (
                round(
                    sum(item.get("safe_fix_match") is True for item in valid)
                    / case_count,
                    4,
                )
                if case_count
                else 0.0
            ),
            "simplification_accuracy": (
                round(
                    sum(item.get("simplification_match") is True for item in valid)
                    / case_count,
                    4,
                )
                if case_count
                else 0.0
            ),
            "boundary_violation_count": sum(
                item.get("tracked_files_modified") is True for item in selected
            ),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        }
    v1 = arms["v1"]
    v0 = arms["v0"]
    token_ratio = (
        round(v1["output_tokens"] / v0["output_tokens"], 4)
        if v0["output_tokens"]
        else None
    )
    latency_ratio = (
        round(v1["latency_ms"] / v0["latency_ms"], 4) if v0["latency_ms"] else None
    )
    exact_valid_arms = {
        version: sorted(
            item["case_id"]
            for item in runs
            if item["contract_version"] == version and item.get("valid") is True
        )
        == expected_case_ids
        for version in CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS
    }
    acceptance = {
        "full_declared_matrix_evaluated": matrix_digest == declared_matrix_digest,
        "all_v0_runs_valid": exact_valid_arms["v0"],
        "all_v1_runs_valid": exact_valid_arms["v1"],
        "v1_primary_lenses_complete": v1["primary_lens_completeness"] == 1.0,
        "v1_simplify_precision_at_least_0_8": v1["precision"] >= 0.8,
        "v1_simplify_recall_at_least_0_8": v1["recall"] >= 0.8,
        "v1_safe_fix_accuracy_complete": v1["safe_fix_accuracy"] == 1.0,
        "v1_simplification_accuracy_at_least_0_8": (
            v1["simplification_accuracy"] >= 0.8
        ),
        "v1_boundary_clean": v1["boundary_violation_count"] == 0,
        "output_token_ratio_at_most_1_25": (
            token_ratio is not None and token_ratio <= 1.25
        ),
        "latency_ratio_at_most_1_25": (
            latency_ratio is not None and latency_ratio <= 1.25
        ),
    }
    return {
        "schema_version": CHANGE_QUALITY_SHADOW_RECEIPT_SCHEMA_VERSION,
        "model_ref": _bounded_text(model_ref, field="model_ref", limit=120),
        "source_commit": _bounded_text(
            source_commit,
            field="source_commit",
            limit=64,
        ),
        "matrix_digest": matrix_digest,
        "declared_matrix_digest": declared_matrix_digest,
        "evaluation_focus": "simplify_first",
        "case_count": case_count,
        "declared_case_count": len(declared_matrix["cases"]),
        "arms": arms,
        "budget_comparison": {
            "v1_to_v0_output_token_ratio": token_ratio,
            "v1_to_v0_latency_ratio": latency_ratio,
        },
        "acceptance": acceptance,
        "strict_receipt_promotion_recommended": all(acceptance.values()),
        "automatic_policy_mutation_allowed": False,
        "runs": [dict(item) for item in runs],
        "persistence_boundary": {
            "raw_prompts_persisted": False,
            "raw_model_responses_persisted": False,
            "stderr_persisted": False,
        },
    }

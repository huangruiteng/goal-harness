from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ...history import validate_goal_id_path_segment
from ...registry import read_json, registry_goals
from .context import build_change_quality_repository_context
from .policy import change_quality_goal_policy
from .result import (
    CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
    REVIEW_LENSES,
    REVIEW_LENS_IDS,
    SIMPLIFY_GUARDRAIL_LENS_IDS,
    SIMPLIFY_PRIMARY_LENS_IDS,
    change_quality_result_decision,
    normalize_change_quality_result,
)
from .scope import build_change_quality_scope, resolve_git_root


CHANGE_QUALITY_PREPARE_SCHEMA_VERSION = "change_quality_prepare_packet_v1"
CHANGE_QUALITY_RECEIPT_SCHEMA_VERSION = "change_quality_receipt_v1"
CHANGE_QUALITY_VERIFY_SCHEMA_VERSION = "change_quality_receipt_verification_v1"


def _goal_from_registry(registry_path: Path, goal_id: str) -> dict[str, Any]:
    registry = read_json(registry_path)
    goal = next(
        (
            item
            for item in registry_goals(registry)
            if str(item.get("id") or "") == goal_id
        ),
        None,
    )
    if goal is None:
        raise ValueError(f"goal_id not found in registry: {goal_id}")
    return goal


def _receipt_root(runtime_root: Path, goal_id: str) -> Path:
    validated_goal_id = validate_goal_id_path_segment(goal_id)
    return (
        runtime_root.expanduser()
        / "goals"
        / validated_goal_id
        / "change-quality"
        / "receipts"
    )


def _repo_key(repo_path: Path) -> str:
    repo_root = resolve_git_root(repo_path)
    return hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:16]


def _receipt_path(
    *,
    runtime_root: Path,
    goal_id: str,
    repo_path: Path,
    scope_fingerprint: str,
) -> Path:
    return _receipt_root(runtime_root, goal_id) / (
        f"{_repo_key(repo_path)}-{scope_fingerprint}.json"
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def build_change_quality_prepare_packet(
    *,
    registry_path: Path,
    goal_id: str,
    repo_path: Path,
    base_ref: str = "origin/main",
) -> dict[str, Any]:
    goal = _goal_from_registry(registry_path, goal_id)
    policy = change_quality_goal_policy(goal)
    scope = build_change_quality_scope(repo_path=repo_path, base_ref=base_ref)
    repository_context = build_change_quality_repository_context(
        repo_path=repo_path,
        changed_files=list(scope["changed_files"]),
    )
    if not policy["enabled"]:
        status = "disabled"
    elif not scope["changed_files"]:
        status = "no_changes"
    else:
        status = "review_required"
    return {
        "ok": True,
        "schema_version": CHANGE_QUALITY_PREPARE_SCHEMA_VERSION,
        "goal_id": goal_id,
        "status": status,
        "review_required": status == "review_required",
        "policy": policy,
        "scope": scope,
        "repository_context": repository_context,
        "agent_contract": {
            "provider_neutral": True,
            "max_safe_fix_passes": 1,
            "review_lenses": [dict(item) for item in REVIEW_LENSES],
            "primary_review_lenses": list(SIMPLIFY_PRIMARY_LENS_IDS),
            "guardrail_review_lenses": list(SIMPLIFY_GUARDRAIL_LENS_IDS),
            "instructions": [
                "Review only the exact changed scope and resolve the projected repository instruction and ownership references.",
                "Spend review effort first on reuse and quality_simplification; record distinct, evidence-backed conclusions for both.",
                "Prefer deletion, reuse, direct control flow, and established language idioms over redundant state, parameters, branches, wrappers, or speculative abstraction.",
                "Treat the remaining lenses as guardrails: expand them only when the changed surface, a repository instruction, a native validator, or a simplify proposal raises a concrete risk; otherwise mark them not_applicable concisely.",
                "Use blocker only for concrete correctness, security, privacy, contract, or required-validation failures.",
                "Use repository-native tests, linters, type checkers, and build tools as language-specific oracles.",
                (
                    "One bounded safe-fix pass is allowed; rerun prepare after edits and review the final scope."
                    if policy["safe_fix"]
                    else "Do not modify files; report findings only."
                ),
                "Record a result only after reviewing the final scope fingerprint.",
            ],
            "result_schema_version": CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
            "result_template": {
                "schema_version": CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
                "scope_fingerprint": scope["scope_fingerprint"],
                "reviewed_final_scope": True,
                "summary": "",
                "repository_principles": [
                    {"source": path, "principle": ""}
                    for path in repository_context["instruction_refs"]
                ],
                "findings": [],
                "lens_reviews": [
                    {
                        "lens_id": lens_id,
                        "status": "checked",
                        "summary": "",
                        "finding_codes": [],
                        "evidence_refs": [],
                    }
                    for lens_id in REVIEW_LENS_IDS
                ],
                "simplification_decisions": [
                    {
                        "decision_id": "",
                        "subject": "",
                        "outcome": "retained",
                        "reason": "",
                    }
                ],
                "safe_fix_applied": False,
                "safe_fix_passes": 0,
                "validation_evidence": [
                    {
                        "validator": "",
                        "status": "passed",
                        "scope": "",
                    }
                ],
            },
        },
        "turn_boundary": {
            "role": "transport_only",
            "rule": (
                "Turn may carry this packet or a receipt reference, but canary "
                "premerge remains the enforcement authority."
            ),
        },
    }


def record_change_quality_receipt(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    repo_path: Path,
    result_path: Path,
    base_ref: str = "origin/main",
    execute: bool = False,
) -> dict[str, Any]:
    goal = _goal_from_registry(registry_path, goal_id)
    policy = change_quality_goal_policy(goal)
    if not policy["enabled"]:
        raise ValueError("change-quality qualification is disabled for this goal")
    scope = build_change_quality_scope(repo_path=repo_path, base_ref=base_ref)
    if not scope["changed_files"]:
        raise ValueError("current scope has no changes and does not need a receipt")
    repository_context = build_change_quality_repository_context(
        repo_path=repo_path,
        changed_files=list(scope["changed_files"]),
    )
    result = normalize_change_quality_result(
        json.loads(result_path.expanduser().read_text(encoding="utf-8")),
        expected_fingerprint=str(scope["scope_fingerprint"]),
        safe_fix_allowed=bool(policy["safe_fix"]),
        expected_changed_files=list(scope["changed_files"]),
        expected_instruction_refs=list(repository_context["instruction_refs"]),
    )
    decision, unresolved_blockers = change_quality_result_decision(result)
    receipt_id = f"cqr_{str(scope['scope_fingerprint'])[:20]}"
    receipt = {
        "schema_version": CHANGE_QUALITY_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "goal_id": goal_id,
        "recorded_at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "policy": policy,
        "scope": scope,
        "result": result,
        "decision": decision,
        "unresolved_blockers": unresolved_blockers,
    }
    path = _receipt_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
        repo_path=repo_path,
        scope_fingerprint=str(scope["scope_fingerprint"]),
    )
    if execute:
        _atomic_write_json(path, receipt)
    return {
        "ok": decision == "pass",
        "schema_version": CHANGE_QUALITY_RECEIPT_SCHEMA_VERSION,
        "dry_run": not execute,
        "written": execute,
        "receipt_id": receipt_id,
        "decision": decision,
        "unresolved_blockers": unresolved_blockers,
        "receipt_path": str(path),
        "scope_fingerprint": scope["scope_fingerprint"],
        "receipt": receipt,
    }


def _stored_receipt_is_valid(
    receipt: dict[str, Any] | None,
    *,
    scope_fingerprint: str,
    safe_fix_allowed: bool,
    changed_files: list[str],
    instruction_refs: list[str],
) -> bool:
    if not (
        receipt
        and receipt.get("schema_version") == CHANGE_QUALITY_RECEIPT_SCHEMA_VERSION
        and receipt.get("decision") == "pass"
        and isinstance(receipt.get("result"), dict)
        and isinstance(receipt.get("scope"), dict)
        and receipt["scope"].get("scope_fingerprint") == scope_fingerprint
    ):
        return False
    try:
        normalized = normalize_change_quality_result(
            receipt["result"],
            expected_fingerprint=scope_fingerprint,
            safe_fix_allowed=safe_fix_allowed,
            expected_changed_files=changed_files,
            expected_instruction_refs=instruction_refs,
        )
    except (TypeError, ValueError):
        return False
    decision, unresolved = change_quality_result_decision(normalized)
    return decision == "pass" and receipt.get("unresolved_blockers") == unresolved


def verify_change_quality_receipt(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    repo_path: Path,
    base_ref: str = "origin/main",
) -> dict[str, Any]:
    goal = _goal_from_registry(registry_path, goal_id)
    policy = change_quality_goal_policy(goal)
    scope = build_change_quality_scope(repo_path=repo_path, base_ref=base_ref)
    if not policy["enabled"]:
        return {
            "ok": True,
            "schema_version": CHANGE_QUALITY_VERIFY_SCHEMA_VERSION,
            "goal_id": goal_id,
            "status": "disabled",
            "enforcement_applied": False,
            "policy": policy,
            "scope": scope,
        }
    if not scope["changed_files"]:
        return {
            "ok": True,
            "schema_version": CHANGE_QUALITY_VERIFY_SCHEMA_VERSION,
            "goal_id": goal_id,
            "status": "no_changes",
            "enforcement_applied": bool(policy["strict_receipt"]),
            "policy": policy,
            "scope": scope,
        }
    path = _receipt_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
        repo_path=repo_path,
        scope_fingerprint=str(scope["scope_fingerprint"]),
    )
    receipt = None
    repository_context = build_change_quality_repository_context(
        repo_path=repo_path,
        changed_files=list(scope["changed_files"]),
    )
    if path.exists():
        try:
            receipt = read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            receipt = None
    receipt_valid = _stored_receipt_is_valid(
        receipt,
        scope_fingerprint=str(scope["scope_fingerprint"]),
        safe_fix_allowed=bool(policy["safe_fix"]),
        changed_files=list(scope["changed_files"]),
        instruction_refs=list(repository_context["instruction_refs"]),
    )
    if receipt_valid:
        status = "valid"
    elif path.exists():
        status = "invalid_receipt"
    else:
        repo_receipts = sorted(
            path.parent.glob(f"{_repo_key(repo_path)}-*.json"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        status = "stale_receipt" if repo_receipts else "receipt_missing"
    strict = bool(policy["strict_receipt"])
    return {
        "ok": receipt_valid or not strict,
        "schema_version": CHANGE_QUALITY_VERIFY_SCHEMA_VERSION,
        "goal_id": goal_id,
        "status": status,
        "enforcement_applied": strict,
        "policy": policy,
        "scope": scope,
        "receipt_id": receipt.get("receipt_id") if receipt else None,
        "receipt_path": str(path),
        "receipt_valid": receipt_valid,
        "required_action": (
            "run change-quality prepare, review the exact scope, and record a passing receipt"
            if strict and not receipt_valid
            else None
        ),
    }

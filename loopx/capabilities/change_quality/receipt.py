from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ...feedback import validate_public_safe_text
from ...history import validate_goal_id_path_segment
from ...registry import read_json, registry_goals
from .policy import change_quality_goal_policy
from .scope import build_change_quality_scope, resolve_git_root


CHANGE_QUALITY_PREPARE_SCHEMA_VERSION = "change_quality_prepare_packet_v0"
CHANGE_QUALITY_RESULT_SCHEMA_VERSION = "change_quality_agent_result_v0"
CHANGE_QUALITY_RECEIPT_SCHEMA_VERSION = "change_quality_receipt_v0"
CHANGE_QUALITY_VERIFY_SCHEMA_VERSION = "change_quality_receipt_verification_v0"
FINDING_SEVERITIES = frozenset({"blocker", "warning", "advisory"})


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
    return runtime_root.expanduser() / "goals" / validated_goal_id / "change-quality" / "receipts"


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


def _normalize_result(
    value: Any,
    *,
    expected_fingerprint: str,
    safe_fix_allowed: bool,
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
        raise ValueError("result reports safe_fix_applied but goal policy forbids safe fixes")
    safe_fix_passes = value.get("safe_fix_passes", 0)
    if not isinstance(safe_fix_passes, int) or safe_fix_passes not in {0, 1}:
        raise ValueError("safe_fix_passes must be 0 or 1")
    if safe_fix_applied and safe_fix_passes != 1:
        raise ValueError("safe_fix_applied=true requires safe_fix_passes=1")
    if not safe_fix_applied and safe_fix_passes != 0:
        raise ValueError("safe_fix_passes=1 requires safe_fix_applied=true")
    findings = [
        _normalize_finding(item, index=index)
        for index, item in enumerate(value.get("findings") or [])
    ]
    if len(findings) > 20:
        raise ValueError("result supports at most 20 findings")
    validations = [
        _bounded_text(item, field="validations[]", limit=180)
        for item in (value.get("validations") or [])[:20]
    ]
    validations = [item for item in validations if item]
    return {
        "schema_version": CHANGE_QUALITY_RESULT_SCHEMA_VERSION,
        "scope_fingerprint": fingerprint,
        "reviewed_final_scope": True,
        "summary": _bounded_text(value.get("summary"), field="summary", limit=500),
        "findings": findings,
        "safe_fix_applied": safe_fix_applied,
        "safe_fix_passes": safe_fix_passes,
        "validations": validations,
    }


def _decision(result: dict[str, Any]) -> tuple[str, list[str]]:
    unresolved_blockers = [
        str(item["code"])
        for item in result["findings"]
        if item["severity"] == "blocker" and item["resolved"] is not True
    ]
    return (
        ("fail", unresolved_blockers)
        if unresolved_blockers
        else ("pass", [])
    )


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
        "agent_contract": {
            "provider_neutral": True,
            "max_safe_fix_passes": 1,
            "instructions": [
                "Review only the exact changed scope and obey repository-local instructions.",
                "Preserve intended behavior; prefer deletion, clarity, and established language idioms over new abstraction.",
                "Use blocker only for concrete correctness, security, privacy, contract, or required-validation failures.",
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
                "findings": [],
                "safe_fix_applied": False,
                "safe_fix_passes": 0,
                "validations": [],
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
    result = _normalize_result(
        json.loads(result_path.expanduser().read_text(encoding="utf-8")),
        expected_fingerprint=str(scope["scope_fingerprint"]),
        safe_fix_allowed=bool(policy["safe_fix"]),
    )
    decision, unresolved_blockers = _decision(result)
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
    if path.exists():
        try:
            receipt = read_json(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            receipt = None
    receipt_valid = bool(
        receipt
        and receipt.get("schema_version") == CHANGE_QUALITY_RECEIPT_SCHEMA_VERSION
        and receipt.get("decision") == "pass"
        and isinstance(receipt.get("scope"), dict)
        and receipt["scope"].get("scope_fingerprint") == scope["scope_fingerprint"]
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

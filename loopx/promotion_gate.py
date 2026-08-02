from __future__ import annotations

from pathlib import Path
from typing import Any

from .control_plane.runtime.promotion_readiness import (
    PROMOTION_READINESS_CLASSIFICATION,
    PROMOTION_READINESS_DELIVERY_BATCH_SCALE,
    PROMOTION_READINESS_DELIVERY_OUTCOME,
    PROMOTION_READINESS_RECOMMENDED_ACTION,
    PROMOTION_READINESS_RECOMMENDED_ACTION_DASHBOARD_SKIPPED,
    PROMOTION_READINESS_RUNTIME_DIR,
)
from .control_plane.runtime.time import now_local_iso
from .doctor import add_promotion_readiness_freshness, latest_promotion_readiness_event
from .history import load_registry, write_reserved_run_artifacts
from .paths import resolve_runtime_root

PROMOTION_GATE_ACTION = "python3 examples/canary/canary-promotion-readiness-smoke.py"


def _render_promotion_readiness_record_markdown(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# LoopX Promotion Readiness Evidence",
            "",
            f"- schema_version: `{payload.get('schema_version')}`",
            f"- generated_at: `{payload.get('generated_at')}`",
            f"- classification: `{payload.get('classification')}`",
            f"- evidence_scope: `{payload.get('evidence_scope')}`",
            f"- dashboard_readiness: `{payload.get('dashboard_readiness')}`",
            f"- delivery_batch_scale: `{payload.get('delivery_batch_scale')}`",
            f"- delivery_outcome: `{payload.get('delivery_outcome')}`",
            "",
            "## Recommended Action",
            "",
            str(payload.get("recommended_action") or ""),
        ]
    )


def record_promotion_readiness(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    dashboard_readiness: str,
    execute: bool,
) -> dict[str, Any]:
    """Append release-scoped readiness evidence without requiring a project Goal."""

    if dashboard_readiness not in {"passed", "skipped"}:
        raise ValueError("dashboard readiness must be `passed` or `skipped`")
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(
        registry,
        runtime_root_override,
        registry_path=registry_path,
    )
    generated_at = now_local_iso()
    recommended_action = (
        PROMOTION_READINESS_RECOMMENDED_ACTION_DASHBOARD_SKIPPED
        if dashboard_readiness == "skipped"
        else PROMOTION_READINESS_RECOMMENDED_ACTION
    )
    record = {
        "schema_version": "promotion_readiness_event_v1",
        "generated_at": generated_at,
        "classification": PROMOTION_READINESS_CLASSIFICATION,
        "evidence_scope": "runtime_release",
        "dashboard_readiness": dashboard_readiness,
        "delivery_batch_scale": PROMOTION_READINESS_DELIVERY_BATCH_SCALE,
        "delivery_outcome": PROMOTION_READINESS_DELIVERY_OUTCOME,
        "recommended_action": recommended_action,
    }
    runs_dir = runtime_root / PROMOTION_READINESS_RUNTIME_DIR
    index_path = runs_dir / "index.jsonl"
    payload = {
        "ok": True,
        "dry_run": not execute,
        "appended": execute,
        "registry": str(registry_path),
        "runtime_root": str(runtime_root),
        "index_path": str(index_path),
        **record,
    }
    if execute:
        runs_dir.mkdir(parents=True, exist_ok=True)
        index_record = dict(record)
        write_reserved_run_artifacts(
            runs_dir=runs_dir,
            generated_at=generated_at,
            record=record,
            index_record=index_record,
            payload=payload,
            render_markdown=_render_promotion_readiness_record_markdown,
        )
    else:
        payload["planned_write"] = {
            "scope": "runtime_release",
            "index_path": str(index_path),
        }
    return payload


def render_promotion_readiness_record_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# LoopX Promotion Readiness Record",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- dry_run: `{payload.get('dry_run')}`",
        f"- appended: `{payload.get('appended')}`",
        f"- runtime_root: `{payload.get('runtime_root')}`",
        f"- evidence_scope: `{payload.get('evidence_scope')}`",
        f"- dashboard_readiness: `{payload.get('dashboard_readiness')}`",
        f"- index_path: `{payload.get('index_path')}`",
    ]
    if payload.get("json_path"):
        lines.append(f"- json_path: `{payload.get('json_path')}`")
    if payload.get("markdown_path"):
        lines.append(f"- markdown_path: `{payload.get('markdown_path')}`")
    return "\n".join(lines)


def promotion_gate_message(readiness: dict[str, Any]) -> str:
    status = str(readiness.get("freshness_status") or "unknown")
    generated_at = readiness.get("generated_at") or "none"
    age_hours = readiness.get("age_hours")
    reason = readiness.get("reason") or ""
    detail = f"generated_at={generated_at}"
    if age_hours is not None:
        detail += f", age_hours={age_hours}"
    if reason:
        detail += f", reason={reason}"
    return (
        "promotion-readiness evidence is "
        f"{status}; {detail}. This is non-blocking, but before promoting a live "
        "checkout prefer `loopx doctor` and "
        f"`{PROMOTION_GATE_ACTION}`."
    )


def build_promotion_gate(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(
        registry,
        runtime_root_override,
        registry_path=registry_path,
    )
    readiness = add_promotion_readiness_freshness(
        latest_promotion_readiness_event(runtime_root)
    )
    should_warn = bool(readiness.get("requires_readiness_run"))
    gate_state = "warning" if should_warn else "ready"
    payload = {
        "ok": True,
        "registry": str(registry_path),
        "runtime_root": str(runtime_root),
        "gate": "promotion_readiness",
        "gate_state": gate_state,
        "can_promote": not should_warn,
        "should_warn": should_warn,
        "non_blocking": True,
        "recommended_action": PROMOTION_GATE_ACTION if should_warn else "promotion readiness is fresh",
        "readiness": readiness,
    }
    if should_warn:
        payload["warning_message"] = promotion_gate_message(readiness)
    return payload


def render_promotion_gate_markdown(payload: dict[str, Any]) -> str:
    readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    lines = [
        "# LoopX Promotion Gate",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- gate: `{payload.get('gate')}`",
        f"- gate_state: `{payload.get('gate_state')}`",
        f"- can_promote: `{payload.get('can_promote')}`",
        f"- should_warn: `{payload.get('should_warn')}`",
        f"- non_blocking: `{payload.get('non_blocking')}`",
        f"- runtime_root: `{payload.get('runtime_root')}`",
        f"- freshness_status: `{readiness.get('freshness_status')}`",
        f"- requires_readiness_run: `{readiness.get('requires_readiness_run')}`",
        f"- generated_at: `{readiness.get('generated_at')}`",
        f"- age_hours: `{readiness.get('age_hours')}`",
    ]
    if readiness.get("reason"):
        lines.append(f"- reason: {readiness.get('reason')}")
    if payload.get("warning_message"):
        lines.extend(["", "## Warning", str(payload.get("warning_message"))])
    lines.extend(["", "## Recommended Action", str(payload.get("recommended_action") or "")])
    return "\n".join(lines)

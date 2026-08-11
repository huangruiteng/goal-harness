from __future__ import annotations

from pathlib import Path
from typing import Any

from .control_plane.runtime.time import now_utc_iso
from .history import collect_history, load_registry
from .paths import resolve_runtime_root
from .presentation.markdown import as_dict, as_list
from .presentation.public_safety import public_safe_boundary, redact_public_text
from .status import collect_status


COMMAND = "/loopx-global-risks"
SCHEMA_VERSION = "global_manager_command_response_v0"
SOURCE_SURFACES = [
    "status attention queue",
    "status health items",
    "global registry findings",
    "run history summaries",
]


def _redact_text(value: object, *, limit: int = 260) -> str:
    return redact_public_text(
        value,
        limit=limit,
        replacements={"/loop-global-risks": COMMAND},
        truncation_marker="…",
    )


def _request() -> dict[str, Any]:
    return {
        "schema_version": "global_manager_command_request_v0",
        "command": COMMAND,
        "legacy_aliases": ["/loop-global-risks"],
        "cli_command": "loopx global-risks",
        "include": ["stale_runs", "health_risks", "boundary_warnings", "failing_checks"],
        "privacy_mode": "public_safe_summary",
        "dry_run": True,
    }


def build_global_risks_error(error: object) -> dict[str, Any]:
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "request": _request(),
        "generated_at": now_utc_iso(),
        "error": _redact_text(error),
        "omissions": [
            "Raw/private failure details and local paths were intentionally omitted."
        ],
        "boundary": public_safe_boundary(),
    }


def _risk_from_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": str(finding.get("kind") or "status_warning"),
        "severity": str(finding.get("severity") or "info"),
        "goal_id": finding.get("goal_id"),
        "evidence_refs": _redact_text(
            finding.get("evidence_refs") or ["status_contract"],
            limit=120,
        ),
        "next_safe_action": _redact_text(
            finding.get("recommended_action") or finding.get("message")
        ),
    }


def _risk_from_health(health_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "health_blocker",
        "severity": str(health_item.get("severity") or "high"),
        "goal_id": health_item.get("goal_id"),
        "waiting_on": health_item.get("waiting_on"),
        "evidence_refs": ["status_health_items"],
        "next_safe_action": _redact_text(
            health_item.get("recommended_action")
            or "Inspect the blocking health item before spending compute."
        ),
    }


RISK_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}
RISK_KIND_DISPLAY = {
    "stale_run": "Stale Runs",
    "health_blocker": "Health Blockers",
    "boundary_warning": "Boundary Warnings",
    "status_warning": "Status Warnings",
    "failing_check": "Failing Checks",
}


def _risk_sort_key(risk: dict[str, Any]) -> tuple[int, int, str]:
    severity = str(risk.get("severity") or "info")
    kind = str(risk.get("kind") or "")
    kind_display_rank = list(RISK_KIND_DISPLAY).index(kind) if kind in RISK_KIND_DISPLAY else 99
    return (
        RISK_SEVERITY_RANK.get(severity, 4),
        kind_display_rank,
        str(risk.get("goal_id") or ""),
    )


def build_global_risks(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    scan_roots: list[Path],
    agent_id: str | None,
    limit: int,
) -> dict[str, Any]:
    normalized_limit = max(1, limit)
    status_payload = collect_status(
        registry_path=registry_path,
        runtime_root_override=runtime_root_override,
        scan_roots=scan_roots,
        limit=max(normalized_limit, 1),
    )
    if status_payload.get("ok") is not True:
        return build_global_risks_error("Global status source unavailable.")

    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_override)
    history_payload = collect_history(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=None,
        limit=max(normalized_limit * 2, 10),
    )

    risks: list[dict[str, Any]] = []

    # 1. Findings from global registry (status_warning, boundary_warning)
    global_registry = as_dict(status_payload.get("global_registry"))
    for finding in as_list(global_registry.get("findings")):
        if isinstance(finding, dict):
            risks.append(_risk_from_finding(finding))

    # 2. Health blockers from status
    for health_item in as_list(status_payload.get("health_items")):
        if isinstance(health_item, dict) and health_item.get("severity") == "high":
            risks.append(_risk_from_health(health_item))

    # 3. Stale runs from history — runs older than the freshness window
    #    that are still classified as active/running
    stale_kinds = {"active", "running", "in_progress", "agent_working", "agent_loop"}
    for run in as_list(history_payload.get("runs")):
        if not isinstance(run, dict):
            continue
        classification = str(run.get("classification") or "").strip()
        if classification in stale_kinds:
            risks.append(
                {
                    "kind": "stale_run",
                    "severity": "medium",
                    "goal_id": run.get("goal_id"),
                    "generated_at": run.get("generated_at"),
                    "classification": classification,
                    "evidence_refs": ["run_history_index"],
                    "next_safe_action": _redact_text(
                        run.get("recommended_action")
                        or "Inspect the stale run and decide whether to continue, "
                        "pause, or terminate."
                    ),
                }
            )

    risks.sort(key=_risk_sort_key)
    matched_count = len(risks)
    retained = risks[:normalized_limit]
    truncated = matched_count > normalized_limit

    # Classify into groups
    groups: dict[str, list[dict[str, Any]]] = {}
    for risk in retained:
        kind = str(risk.get("kind") or "status_warning")
        group_label = RISK_KIND_DISPLAY.get(kind, "Other Risks")
        groups.setdefault(group_label, []).append(risk)

    high_count = sum(1 for r in retained if r.get("severity") == "high")
    medium_count = sum(1 for r in retained if r.get("severity") == "medium")

    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "request": _request(),
        "generated_at": now_utc_iso(),
        "summary": {
            "headline": (
                f"{matched_count} risk(s) identified: "
                f"{high_count} high, {medium_count} medium."
            ),
            "risk_count": matched_count,
            "returned_risk_count": len(retained),
            "high_severity_count": high_count,
            "medium_severity_count": medium_count,
            "source_surfaces": SOURCE_SURFACES,
            "truncated": truncated,
        },
        "groups": groups,
        "risks": retained,
        "actions": [
            {
                "action_id": "act_inspect_risk",
                "kind": "read_more",
                "requires_user_approval": False,
                "requires_maintainer_authority": False,
                "preview": (
                    "Run `loopx status` or `loopx quota should-run --goal-id <goal>` "
                    "to inspect one risk source."
                ),
            },
            {
                "action_id": "act_mitigate_risk",
                "kind": "ask_user",
                "requires_user_approval": True,
                "requires_maintainer_authority": False,
                "preview": (
                    "When a high-severity risk is blocking, ask the operator to "
                    "approve mitigation before running the affected path."
                ),
            },
        ],
        "omissions": [
            (
                "Raw logs, raw transcripts, connector payloads, credential values, "
                "local paths, and private source bodies were intentionally omitted."
            ),
            "Recent progress, gates, and todos are outside this focused command.",
        ],
        "boundary": public_safe_boundary(),
    }


def render_global_risks_markdown(payload: dict[str, Any]) -> str:
    if not payload.get("ok"):
        lines = [
            "# LoopX Global Risks Unavailable",
            "",
            "- ok: `False`",
            f"- error: {_redact_text(payload.get('error'))}",
        ]
        omissions = [
            _redact_text(item)
            for item in as_list(payload.get("omissions"))
            if _redact_text(item)
        ]
        if omissions:
            lines.extend(["", "## Omissions"])
            lines.extend(f"- {item}" for item in omissions)
        return "\n".join(lines)

    summary = as_dict(payload.get("summary"))
    request = as_dict(payload.get("request"))
    lines = [
        "# LoopX Global Risks",
        "",
        f"- command: `{_redact_text(request.get('command'), limit=120)}`",
        f"- risk_count: `{summary.get('risk_count')}`",
        f"- high_severity: `{summary.get('high_severity_count')}`",
        f"- truncated: `{bool(summary.get('truncated'))}`",
    ]
    groups = as_dict(payload.get("groups"))
    for group_label in RISK_KIND_DISPLAY.values():
        items = [
            item
            for item in as_list(groups.get(group_label))
            if isinstance(item, dict)
        ]
        if not items:
            continue
        lines.extend(["", f"## {group_label}"])
        for risk in items:
            goal_id = _redact_text(risk.get("goal_id"), limit=120)
            severity = _redact_text(risk.get("severity"), limit=40)
            next_action = _redact_text(risk.get("next_safe_action"))
            line = (
                f"- severity=`{severity}`"
                + (f" goal=`{goal_id}`" if goal_id else "")
                + f": {next_action}"
            )
            lines.append(line)
    if not any(
        as_list(groups.get(label))
        for label in RISK_KIND_DISPLAY.values()
    ):
        lines.extend(["", "- No risks identified."])
    lines.extend(
        [
            "",
            "## Boundary",
            "- Raw/private material omitted; local paths are not recorded.",
        ]
    )
    return "\n".join(lines)

from __future__ import annotations

from typing import AbstractSet, Any, Callable, Optional


AttentionItemBuilder = Callable[..., dict[str, Any]]
GlobalRegistryShadowAttacher = Callable[[dict[str, Any], dict[str, Any]], None]


def merge_global_registry_findings(
    *,
    health_items: list[dict[str, Any]],
    history_items: list[dict[str, Any]],
    findings: list[Any],
    goal_id_filter: Optional[str],
    source_registry_shadow_findings: AbstractSet[str],
    attention_item: AttentionItemBuilder,
    attach_global_registry_shadow_finding: GlobalRegistryShadowAttacher,
) -> None:
    live_quota_items_by_goal: dict[str, list[dict[str, Any]]] = {}
    for item in history_items:
        if isinstance(item.get("quota"), dict):
            live_quota_items_by_goal.setdefault(str(item.get("goal_id") or ""), []).append(item)

    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if finding.get("severity") not in {"high", "action"}:
            continue
        goal_id = str(finding.get("goal_id") or "global-registry")
        if goal_id_filter:
            finding_goal_ids = [
                str(item)
                for item in (finding.get("goal_ids") or [])
                if str(item or "").strip()
            ]
            if goal_id != goal_id_filter and goal_id_filter not in finding_goal_ids:
                continue
        live_items = live_quota_items_by_goal.get(goal_id, [])
        if finding.get("kind") in source_registry_shadow_findings and live_items:
            for item in live_items:
                attach_global_registry_shadow_finding(item, finding)
            continue
        health_items.append(
            attention_item(
                goal_id=goal_id,
                status=str(finding.get("kind") or "global_registry_finding"),
                waiting_on="codex",
                severity=str(finding.get("severity") or "action"),
                recommended_action=str(finding.get("recommended_action") or "inspect global registry health"),
                source="global_registry",
            )
        )


def build_attention_queue_projection(
    *,
    items: list[dict[str, Any]],
    goal_id_filter: Optional[str],
    autonomous_backlog_candidates: Optional[dict[str, Any]],
    autonomous_monitor_candidates: Optional[dict[str, Any]],
    monitor_signal_waiting_on: str,
) -> dict[str, Any]:
    queue: dict[str, Any] = {
        "available": True,
        "item_count": len(items),
        "needs_user_or_controller": sum(
            1 for item in items if item["waiting_on"] in {"user_or_controller", "controller"}
        ),
        "needs_controller": sum(1 for item in items if item["waiting_on"] == "controller"),
        "needs_codex": sum(1 for item in items if item["waiting_on"] == "codex"),
        "watching_external_evidence": sum(1 for item in items if item["waiting_on"] == "external_evidence"),
        "watching_monitor": sum(1 for item in items if item["waiting_on"] == monitor_signal_waiting_on),
        "items": items,
    }
    if goal_id_filter:
        queue["goal_filter"] = goal_id_filter
        queue["goal_filter_applied"] = True
    if autonomous_backlog_candidates:
        queue["autonomous_backlog_candidates"] = autonomous_backlog_candidates
    if autonomous_monitor_candidates:
        queue["autonomous_monitor_candidates"] = autonomous_monitor_candidates
    return queue

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contract import check_contract
from .history import collect_history, load_registry
from .paths import resolve_runtime_root


CODEX_READY_CLASSIFICATIONS = {
    "controller_opted_in_waiting_for_run",
    "design_next_experiment",
    "inspect_eval_result",
    "needs_more_read_only_evidence",
    "needs_validation",
    "run_validation",
}
USER_OR_CONTROLLER_CLASSIFICATIONS = {
    "needs_controller_opt_in",
    "needs_user_relay",
    "ready_for_controller_opt_in",
    "ready_for_user_relay",
}
WATCH_CLASSIFICATION_PREFIXES = ("await_", "monitor_")
CONNECTED_ADAPTER_STATUSES = {
    "connected",
    "connected-read-only",
    "pre-tick-runnable",
}


def attention_item(
    *,
    goal_id: str,
    status: str,
    waiting_on: str,
    severity: str,
    recommended_action: str,
    source: str,
) -> dict[str, Any]:
    return {
        "goal_id": goal_id,
        "status": status,
        "waiting_on": waiting_on,
        "severity": severity,
        "recommended_action": recommended_action,
        "source": source,
    }


def latest_run(goal: dict[str, Any]) -> dict[str, Any] | None:
    runs = goal.get("latest_runs")
    if not isinstance(runs, list) or not runs:
        return None
    run = runs[0]
    return run if isinstance(run, dict) else None


def goal_attention(goal: dict[str, Any]) -> dict[str, Any] | None:
    goal_id = str(goal.get("id") or "unknown-goal")
    adapter_status = str(goal.get("adapter_status") or "")
    current_run = latest_run(goal)

    if goal.get("legacy_runtime_goal"):
        return None

    if not current_run:
        if adapter_status in CONNECTED_ADAPTER_STATUSES:
            return attention_item(
                goal_id=goal_id,
                status="connected_without_run",
                waiting_on="codex",
                severity="action",
                recommended_action="run the first read-only adapter tick and save a compact run record",
                source="run_history",
            )
        return attention_item(
            goal_id=goal_id,
            status=str(goal.get("status") or "no_run"),
            waiting_on="controller",
            severity="action",
            recommended_action="connect an adapter or run a read-only map before expecting runtime status",
            source="registry",
        )

    json_exists = bool(current_run.get("json_exists"))
    markdown_exists = bool(current_run.get("markdown_exists"))
    if not json_exists or not markdown_exists:
        return attention_item(
            goal_id=goal_id,
            status="run_artifact_missing",
            waiting_on="codex",
            severity="high",
            recommended_action="repair or regenerate the latest run artifacts before trusting status",
            source="run_history",
        )

    classification = str(current_run.get("classification") or "unknown")
    action = str(current_run.get("recommended_action") or "inspect the latest run and choose one next action")
    if classification in USER_OR_CONTROLLER_CLASSIFICATIONS:
        return attention_item(
            goal_id=goal_id,
            status=classification,
            waiting_on="user_or_controller",
            severity="action",
            recommended_action=action,
            source="latest_run",
        )
    if classification in CODEX_READY_CLASSIFICATIONS:
        return attention_item(
            goal_id=goal_id,
            status=classification,
            waiting_on="codex",
            severity="action",
            recommended_action=action,
            source="latest_run",
        )
    if classification.startswith(WATCH_CLASSIFICATION_PREFIXES):
        return attention_item(
            goal_id=goal_id,
            status=classification,
            waiting_on="external_evidence",
            severity="watch",
            recommended_action=action,
            source="latest_run",
        )
    return None


def build_attention_queue(
    *,
    contract: dict[str, Any],
    history: dict[str, Any],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if contract.get("ok") is False:
        items.append(
            attention_item(
                goal_id="goal-harness-contract",
                status="contract_check_failed",
                waiting_on="codex",
                severity="high",
                recommended_action="fix contract errors before advancing goal adapters",
                source="contract",
            )
        )

    for goal in history.get("goals") or []:
        if not isinstance(goal, dict):
            continue
        item = goal_attention(goal)
        if item:
            items.append(item)

    return {
        "available": True,
        "item_count": len(items),
        "needs_user_or_controller": sum(1 for item in items if item["waiting_on"] == "user_or_controller"),
        "needs_codex": sum(1 for item in items if item["waiting_on"] == "codex"),
        "watching_external_evidence": sum(1 for item in items if item["waiting_on"] == "external_evidence"),
        "items": items,
    }


def collect_status(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    scan_roots: list[Path],
    limit: int,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_override)
    history = collect_history(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=None,
        limit=limit,
    )
    contract = check_contract(
        registry_path=registry_path,
        runtime_root_override=runtime_root_override,
        scan_roots=scan_roots,
        limit=limit,
    )
    queue = build_attention_queue(contract=contract, history=history)
    return {
        "ok": bool(contract.get("ok")),
        "registry": str(registry_path),
        "runtime_root": str(runtime_root),
        "goal_count": history.get("goal_count"),
        "run_count": history.get("run_count"),
        "contract": {
            "ok": contract.get("ok"),
            "summary": contract.get("summary"),
            "errors": contract.get("errors") or [],
            "warnings": contract.get("warnings") or [],
        },
        "attention_queue": queue,
    }


def render_status_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Harness Status",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- registry: `{payload.get('registry')}`",
        f"- runtime_root: `{payload.get('runtime_root')}`",
        f"- goals: `{payload.get('goal_count')}`",
        f"- runs: `{payload.get('run_count')}`",
    ]

    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
    summary = contract.get("summary") if isinstance(contract.get("summary"), dict) else {}
    lines.append(
        "- contract: "
        f"ok={contract.get('ok')}, "
        f"errors={summary.get('errors')}, "
        f"warnings={summary.get('warnings')}, "
        f"checks={summary.get('checks')}"
    )

    queue = payload.get("attention_queue") if isinstance(payload.get("attention_queue"), dict) else {}
    lines.extend(
        [
            "",
            "## Attention Queue",
            "- summary: "
            f"items={queue.get('item_count')}, "
            f"needs_user_or_controller={queue.get('needs_user_or_controller')}, "
            f"needs_codex={queue.get('needs_codex')}, "
            f"watching_external_evidence={queue.get('watching_external_evidence')}",
        ]
    )
    items = queue.get("items") if isinstance(queue.get("items"), list) else []
    if not items:
        lines.append("- none")
    for item in items:
        if not isinstance(item, dict):
            continue
        action = str(item.get("recommended_action") or "").replace("|", "\\|")
        lines.append(
            "- "
            f"`{item.get('goal_id')}`: "
            f"status={item.get('status')} "
            f"waiting_on={item.get('waiting_on')} "
            f"severity={item.get('severity')} "
            f"source={item.get('source')}"
        )
        if action:
            lines.append(f"  - action: {action}")

    for title, key in (("Errors", "errors"), ("Warnings", "warnings")):
        entries = contract.get(key) if isinstance(contract.get(key), list) else []
        if entries:
            lines.extend(["", f"## {title}"])
            lines.extend(f"- {entry}" for entry in entries)

    return "\n".join(lines)

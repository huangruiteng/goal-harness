from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .history import load_index, load_registry
from .paths import resolve_runtime_root


REWARD_VALUES = {"positive", "negative", "mixed", "neutral"}
PRIVATE_TEXT_PATTERNS = (
    re.compile(r"/" + r"Users/"),
    re.compile(r"/" + r"ext_data/"),
    re.compile("la" + "rk" + "office", re.I),
    re.compile("docs" + r"\." + "internal", re.I),
    re.compile(r"\bt-20\d{12}-[a-z0-9]+\b"),
    re.compile(r"\b" + "Bear" + r"er\b", re.I),
    re.compile(r"\b" + "Author" + r"ization\b", re.I),
    re.compile(r"\b" + "tok" + r"en\s*=", re.I),
    re.compile(r"\b" + "pass" + r"word\b", re.I),
    re.compile(r"\b" + "sec" + r"ret\b", re.I),
)
HUMAN_REWARD_FIELDS = (
    "recorded_at",
    "decision",
    "reward",
    "reason_summary",
    "follow_up",
)
RUN_OVERLAY_FIELDS = (
    "generated_at",
    "goal_id",
    "classification",
    "recommended_action",
    "health_check",
    "active_task_count",
    "active_priorities",
    "cache_check",
    "controller_readiness",
    "json_path",
    "markdown_path",
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_public_safe_text(label: str, value: str | None) -> None:
    if not value:
        return
    for pattern in PRIVATE_TEXT_PATTERNS:
        if pattern.search(value):
            raise ValueError(f"{label} contains a private-looking value; keep raw evidence in private payloads")


def compact_reward(
    *,
    recorded_at: str | None,
    decision: str,
    reward: str,
    reason_summary: str,
    follow_up: str | None,
) -> dict[str, Any]:
    if reward not in REWARD_VALUES:
        raise ValueError(f"reward must be one of: {', '.join(sorted(REWARD_VALUES))}")
    validate_public_safe_text("decision", decision)
    validate_public_safe_text("reason_summary", reason_summary)
    validate_public_safe_text("follow_up", follow_up)
    payload = {
        "recorded_at": recorded_at or now_utc(),
        "decision": decision,
        "reward": reward,
        "reason_summary": reason_summary,
    }
    if follow_up:
        payload["follow_up"] = follow_up
    return payload


def select_run(runs: list[dict[str, Any]], run_generated_at: str | None) -> dict[str, Any]:
    if not runs:
        raise ValueError("no compact run records found for goal")
    if run_generated_at:
        for run in runs:
            if str(run.get("generated_at") or "") == run_generated_at:
                return run
        raise ValueError(f"run not found for generated_at={run_generated_at}")
    return sorted(runs, key=lambda item: str(item.get("generated_at") or ""), reverse=True)[0]


def build_reward_coordination(
    *,
    goal_id: str,
    selected_run: dict[str, Any],
    reward: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    run_generated_at = str(selected_run.get("generated_at") or "unknown-run")
    reward_value = str(reward.get("reward") or "unknown")
    decision = str(reward.get("decision") or "unknown_decision")
    verb = "dry-run：将记录" if dry_run else "已记录"
    reason_summary = reward.get("reason_summary")
    summary = (
        f"{verb}目标 `{goal_id}` 的 run `{run_generated_at}` "
        f"human_reward={reward_value}，decision=`{decision}`。"
        "权威来源是 run-bound `human_reward` overlay；"
        "active state 只摘要这个指针和下一步。"
    )
    if reason_summary:
        summary = f"{summary} reason_summary：{reason_summary}"
    follow_up = reward.get("follow_up")
    if follow_up:
        summary = f"{summary} follow_up：{follow_up}"
    return {
        "active_state_summary": summary,
        "project_agent_visibility": {
            "source_of_truth": "run_bound_human_reward_overlay",
            "history_command": f"goal-harness history --goal-id {goal_id} --limit 3",
            "active_state_role": "summary_only",
            "review_packet_role": "optional_handoff_only",
        },
    }


def append_human_reward(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    goal_id: str,
    run_generated_at: str | None,
    reward: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_override)
    index_path = runtime_root / "goals" / goal_id / "runs" / "index.jsonl"
    runs, raw_count = load_index(index_path)
    selected = select_run(runs, run_generated_at)

    missing_paths = [
        field
        for field in ("json_path", "markdown_path")
        if not selected.get(field)
    ]
    if missing_paths:
        raise ValueError(f"selected run is missing required index path fields: {', '.join(missing_paths)}")

    index_record = {
        field: selected[field]
        for field in RUN_OVERLAY_FIELDS
        if field in selected
    }
    index_record["goal_id"] = str(index_record.get("goal_id") or goal_id)
    index_record["human_reward"] = {
        field: reward[field]
        for field in HUMAN_REWARD_FIELDS
        if field in reward
    }

    if not dry_run:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_record, ensure_ascii=False) + "\n")

    selected_run = {
        "generated_at": selected.get("generated_at"),
        "classification": selected.get("classification"),
        "recommended_action": selected.get("recommended_action"),
        "json_exists": selected.get("json_exists"),
        "markdown_exists": selected.get("markdown_exists"),
    }
    coordination = build_reward_coordination(
        goal_id=goal_id,
        selected_run=selected_run,
        reward=index_record["human_reward"],
        dry_run=dry_run,
    )

    return {
        "ok": True,
        "registry": str(registry_path),
        "runtime_root": str(runtime_root),
        "goal_id": goal_id,
        "index_path": str(index_path),
        "raw_index_records_before": raw_count,
        "dry_run": dry_run,
        "selected_run": selected_run,
        "human_reward": index_record["human_reward"],
        **coordination,
        "index_record": index_record,
        "appended": not dry_run,
    }


def render_reward_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Harness Human Reward",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- goal: `{payload.get('goal_id')}`",
        f"- index: `{payload.get('index_path')}`",
        f"- appended: `{payload.get('appended')}`",
        f"- dry_run: `{payload.get('dry_run')}`",
    ]
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
        return "\n".join(lines)

    selected = payload.get("selected_run") if isinstance(payload.get("selected_run"), dict) else {}
    reward = payload.get("human_reward") if isinstance(payload.get("human_reward"), dict) else {}
    lines.extend(
        [
            "",
            "## Selected Run",
            f"- generated_at: `{selected.get('generated_at')}`",
            f"- classification: `{selected.get('classification')}`",
            f"- artifacts: `{selected.get('json_exists')}/{selected.get('markdown_exists')}`",
            "",
            "## Reward",
            f"- recorded_at: `{reward.get('recorded_at')}`",
            f"- decision: `{reward.get('decision')}`",
            f"- reward: `{reward.get('reward')}`",
            f"- reason_summary: {reward.get('reason_summary')}",
        ]
    )
    if reward.get("follow_up"):
        lines.append(f"- follow_up: {reward.get('follow_up')}")
    if payload.get("active_state_summary"):
        lines.extend(["", "## Active-State Summary", str(payload.get("active_state_summary"))])
    visibility = payload.get("project_agent_visibility") if isinstance(payload.get("project_agent_visibility"), dict) else {}
    if visibility:
        lines.extend(
            [
                "",
                "## Project-Agent Visibility",
                f"- source_of_truth: `{visibility.get('source_of_truth')}`",
                f"- history_command: `{visibility.get('history_command')}`",
                f"- active_state_role: `{visibility.get('active_state_role')}`",
                f"- review_packet_role: `{visibility.get('review_packet_role')}`",
            ]
        )
    return "\n".join(lines)

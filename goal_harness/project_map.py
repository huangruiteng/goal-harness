from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .feedback import validate_public_safe_text
from .global_registry import sync_project_registry_to_global
from .history import load_registry
from .paths import resolve_runtime_root
from .state_refresh import (
    derive_recommended_action,
    extract_section_lines,
    now_local,
    parse_frontmatter,
    resolve_goal_state,
    run_file_stem,
)
from .runtime import validate_goal_id_path_segment


DEFAULT_PROJECT_MAP_CLASSIFICATION = "read_only_project_map"
READ_ONLY_MAP_ADAPTER_KIND = "read_only_project_map_v0"
READ_ONLY_MAP_ADAPTER_STATUSES = {
    "connected",
    "connected-read-only",
    "read-only-map-ready",
}
READ_ONLY_MAP_DRY_RUN_PREVIEW_STATUSES = {
    "planned",
}
PROJECT_INVENTORY_PATHS = (
    "README.md",
    "AGENTS.md",
    ".goal-harness/registry.json",
    ".codex/goals",
    "docs",
    "tests",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
)
STATE_SECTIONS = (
    "Authority Sources",
    "Operating Contract",
    "Work Clusters",
    "Validation Surfaces",
    "Private/Public Boundary",
    "Next Action",
    "Progress Ledger",
)


def adapter_supports_read_only_map(adapter_kind: str | None) -> bool:
    if not adapter_kind:
        return False
    return adapter_kind == READ_ONLY_MAP_ADAPTER_KIND or adapter_kind.endswith("_read_only_map_v0")


def compact_authority_sources(goal: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not goal or not isinstance(goal.get("authority_sources"), list):
        return []
    sources: list[dict[str, Any]] = []
    for source in goal.get("authority_sources") or []:
        if not isinstance(source, dict):
            continue
        sources.append(
            {
                "kind": str(source.get("kind") or "unknown"),
                "role": str(source.get("role") or "unknown"),
                "declares_path": bool(source.get("path")),
                "declares_url": bool(source.get("url")),
            }
        )
    return sources


def collect_project_inventory(project: Path | None) -> dict[str, Any]:
    if project is None:
        return {
            "repo_exists": False,
            "files_present": 0,
            "files_checked": len(PROJECT_INVENTORY_PATHS),
            "checks": [],
        }
    checks = []
    for rel_path in PROJECT_INVENTORY_PATHS:
        path = project / rel_path
        checks.append(
            {
                "path": rel_path,
                "exists": path.exists(),
                "kind": "dir" if path.is_dir() else "file" if path.is_file() else "missing",
            }
        )
    return {
        "repo_exists": project.exists(),
        "files_present": sum(1 for item in checks if item["exists"]),
        "files_checked": len(checks),
        "checks": checks,
    }


def collect_state_sections(state_text: str) -> dict[str, Any]:
    sections = {}
    for heading in STATE_SECTIONS:
        lines = extract_section_lines(state_text, heading, limit=8)
        sections[heading] = {
            "present": bool(lines),
            "line_count": len(lines),
            "sample": lines,
        }
    return {
        "sections_found": sum(1 for item in sections.values() if item["present"]),
        "sections_checked": len(sections),
        "sections": sections,
    }


def build_project_map_record(
    *,
    goal_id: str,
    project: Path | None,
    state_file: Path,
    state_text: str,
    classification: str,
    recommended_action: str,
    generated_at: str,
    registry_goal: dict[str, Any],
) -> dict[str, Any]:
    adapter = registry_goal.get("adapter") if isinstance(registry_goal.get("adapter"), dict) else {}
    authority_sources = compact_authority_sources(registry_goal)
    authority_source_count = len(authority_sources)
    if not authority_sources and isinstance(registry_goal.get("authority_source_count"), int):
        authority_source_count = int(registry_goal.get("authority_source_count") or 0)
    inventory = collect_project_inventory(project)
    state_sections = collect_state_sections(state_text)
    state_exists = state_file.exists()
    health_check = (
        f"repo {1 if inventory.get('repo_exists') else 0}/1; "
        f"state_file {1 if state_exists else 0}/1; "
        f"sections {state_sections['sections_found']}/{state_sections['sections_checked']}; "
        f"files {inventory['files_present']}/{inventory['files_checked']}"
    )
    return {
        "generated_at": generated_at,
        "goal_id": goal_id,
        "classification": classification,
        "recommended_action": recommended_action,
        "health_check": health_check,
        "state": {
            "path": str(state_file),
            "frontmatter": parse_frontmatter(state_text),
        },
        "registry_goal": {
            "present": True,
            "domain": registry_goal.get("domain"),
            "status": registry_goal.get("status"),
            "adapter": {
                "kind": adapter.get("kind"),
                "status": adapter.get("status"),
            },
            "authority_source_count": authority_source_count,
            "guard_count": len(registry_goal.get("guards") or []),
            "next_probe_declared": bool(registry_goal.get("next_probe")),
        },
        "authority_sources": authority_sources,
        "state_map": state_sections,
        "project_inventory": inventory,
    }


def derive_residual_risks(record: dict[str, Any], *, opt_in_required: bool) -> list[str]:
    risks: list[str] = []
    registry_goal = record.get("registry_goal") if isinstance(record.get("registry_goal"), dict) else {}
    state_map = record.get("state_map") if isinstance(record.get("state_map"), dict) else {}
    inventory = record.get("project_inventory") if isinstance(record.get("project_inventory"), dict) else {}

    if opt_in_required:
        risks.append("planned_adapter_requires_controller_opt_in")
    if not registry_goal.get("authority_source_count"):
        risks.append("authority_sources_not_declared")

    sections = state_map.get("sections") if isinstance(state_map.get("sections"), dict) else {}
    missing_sections = [
        heading for heading, item in sections.items() if isinstance(item, dict) and not item.get("present")
    ]
    if missing_sections:
        risks.append("state_sections_missing:" + ",".join(missing_sections[:4]))

    if not inventory.get("repo_exists"):
        risks.append("project_repo_missing")

    checks = inventory.get("checks") if isinstance(inventory.get("checks"), list) else []
    missing_paths = {str(item.get("path")) for item in checks if isinstance(item, dict) and not item.get("exists")}
    if ".goal-harness/registry.json" in missing_paths or ".codex/goals" in missing_paths:
        risks.append("project_local_goal_state_not_detected")
    if "README.md" in missing_paths and "docs" in missing_paths:
        risks.append("project_context_surface_sparse")
    validation_markers = {"tests", "package.json", "pyproject.toml", "requirements.txt"}
    if validation_markers.issubset(missing_paths):
        risks.append("standard_validation_surface_not_detected")

    return risks


def compact_project_map(record: dict[str, Any]) -> dict[str, Any]:
    registry_goal = record.get("registry_goal") if isinstance(record.get("registry_goal"), dict) else {}
    adapter = registry_goal.get("adapter") if isinstance(registry_goal.get("adapter"), dict) else {}
    state_map = record.get("state_map") if isinstance(record.get("state_map"), dict) else {}
    inventory = record.get("project_inventory") if isinstance(record.get("project_inventory"), dict) else {}
    return {
        "adapter_kind": adapter.get("kind"),
        "adapter_status": adapter.get("status"),
        "authority_source_count": registry_goal.get("authority_source_count"),
        "guard_count": registry_goal.get("guard_count"),
        "sections_found": state_map.get("sections_found"),
        "sections_checked": state_map.get("sections_checked"),
        "files_present": inventory.get("files_present"),
        "files_checked": inventory.get("files_checked"),
        "residual_risk_count": len(record.get("residual_risks") or []),
    }


def render_read_only_project_map_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Harness Read-Only Project Map",
        "",
        f"- ok: `{payload.get('ok')}`",
        f"- dry_run: `{payload.get('dry_run')}`",
        f"- appended: `{payload.get('appended')}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- classification: `{payload.get('classification')}`",
        f"- generated_at: `{payload.get('generated_at')}`",
        f"- health_check: `{payload.get('health_check')}`",
        f"- opt_in_required: `{payload.get('opt_in_required')}`",
    ]
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
        return "\n".join(lines)

    global_sync = payload.get("global_sync") if isinstance(payload.get("global_sync"), dict) else {}
    if global_sync:
        lines.extend(
            [
                f"- global_registry: `{global_sync.get('global_registry')}`",
                f"- global_sync_wrote: `{global_sync.get('wrote')}`",
            ]
        )

    lines.extend(["", "## Recommended Action", str(payload.get("recommended_action") or "")])

    project_map = payload.get("project_map") if isinstance(payload.get("project_map"), dict) else {}
    if project_map:
        lines.extend(
            [
                "",
                "## Compact Map",
                f"- adapter: `{project_map.get('adapter_kind')}:{project_map.get('adapter_status')}`",
                f"- authority_sources: `{project_map.get('authority_source_count')}`",
                f"- guards: `{project_map.get('guard_count')}`",
                f"- state_sections: `{project_map.get('sections_found')}/{project_map.get('sections_checked')}`",
                f"- project_inventory: `{project_map.get('files_present')}/{project_map.get('files_checked')}`",
                f"- residual_risks: `{project_map.get('residual_risk_count')}`",
            ]
        )

    risks = payload.get("residual_risks") if isinstance(payload.get("residual_risks"), list) else []
    lines.extend(["", "## Residual Risks"])
    if risks:
        for risk in risks:
            lines.append(f"- `{risk}`")
    else:
        lines.append("- none detected in bounded map")

    inventory = payload.get("project_inventory") if isinstance(payload.get("project_inventory"), dict) else {}
    checks = inventory.get("checks") if isinstance(inventory.get("checks"), list) else []
    if checks:
        lines.extend(["", "## Project Inventory"])
        for item in checks:
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{item.get('path')}`: {item.get('kind')}")

    state_map = payload.get("state_map") if isinstance(payload.get("state_map"), dict) else {}
    sections = state_map.get("sections") if isinstance(state_map.get("sections"), dict) else {}
    if sections:
        lines.extend(["", "## State Sections"])
        for heading, item in sections.items():
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{heading}`: present={item.get('present')} lines={item.get('line_count')}")
    return "\n".join(lines)


def read_only_project_map_run(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    goal_id: str,
    project: Path | None,
    state_file: Path | None,
    classification: str,
    recommended_action: str | None,
    dry_run: bool,
    sync_global: bool = True,
) -> dict[str, Any]:
    safe_goal_id = validate_goal_id_path_segment(goal_id)
    validate_public_safe_text("classification", classification)
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(registry, runtime_root_override)
    registry_goal, resolved_project, resolved_state_file = resolve_goal_state(
        registry=registry,
        goal_id=safe_goal_id,
        project_override=project,
        state_file_override=state_file,
    )
    if not registry_goal:
        raise ValueError(f"goal id not found in registry: {safe_goal_id}")
    adapter = registry_goal.get("adapter") if isinstance(registry_goal.get("adapter"), dict) else {}
    adapter_kind = str(adapter.get("kind") or "")
    adapter_status = str(adapter.get("status") or "")
    if not adapter_supports_read_only_map(adapter_kind):
        raise ValueError(
            f"{safe_goal_id} adapter.kind must be `{READ_ONLY_MAP_ADAPTER_KIND}` or end with `_read_only_map_v0`"
        )
    opt_in_required = adapter_status in READ_ONLY_MAP_DRY_RUN_PREVIEW_STATUSES
    if adapter_status not in READ_ONLY_MAP_ADAPTER_STATUSES and not (dry_run and opt_in_required):
        raise ValueError(
            f"{safe_goal_id} adapter.status must be one of {sorted(READ_ONLY_MAP_ADAPTER_STATUSES)}"
            f"; planned adapters may only run read-only-map with --dry-run for opt-in preview"
        )
    if not resolved_state_file.exists():
        raise FileNotFoundError(f"state file does not exist: {resolved_state_file}")

    state_text = resolved_state_file.read_text(encoding="utf-8")
    action = recommended_action or derive_recommended_action(state_text)
    validate_public_safe_text("recommended_action", action)
    generated_at = now_local()
    record = build_project_map_record(
        goal_id=safe_goal_id,
        project=resolved_project,
        state_file=resolved_state_file,
        state_text=state_text,
        classification=classification,
        recommended_action=action,
        generated_at=generated_at,
        registry_goal=registry_goal,
    )
    record["residual_risks"] = derive_residual_risks(record, opt_in_required=opt_in_required)
    project_map = compact_project_map(record)

    runs_dir = runtime_root / "goals" / safe_goal_id / "runs"
    stem = run_file_stem(generated_at)
    json_path = runs_dir / f"{stem}.json"
    markdown_path = runs_dir / f"{stem}.md"
    index_path = runs_dir / "index.jsonl"
    index_record = {
        "generated_at": generated_at,
        "goal_id": safe_goal_id,
        "classification": classification,
        "recommended_action": action,
        "health_check": record["health_check"],
        "residual_risks": record["residual_risks"],
        "project_map": project_map,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    payload = {
        "ok": True,
        "dry_run": dry_run,
        "appended": not dry_run,
        "opt_in_required": opt_in_required,
        "registry": str(registry_path),
        "runtime_root": str(runtime_root),
        "project": str(resolved_project) if resolved_project else None,
        "goal_id": safe_goal_id,
        "classification": classification,
        "recommended_action": action,
        "generated_at": generated_at,
        "health_check": record["health_check"],
        "residual_risks": record["residual_risks"],
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
        "index_path": str(index_path),
        "project_map": project_map,
        **record,
    }
    if not dry_run:
        runs_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(render_read_only_project_map_markdown(payload) + "\n", encoding="utf-8")
        with index_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(index_record, ensure_ascii=False) + "\n")
    if sync_global:
        payload["global_sync"] = sync_project_registry_to_global(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=safe_goal_id,
            dry_run=dry_run,
        )
    else:
        payload["global_sync"] = {
            "enabled": False,
            "global_registry": str(runtime_root / "registry.global.json"),
            "synced_goal_ids": [],
            "wrote": False,
        }
    return payload

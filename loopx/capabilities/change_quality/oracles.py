from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Callable


CHANGE_QUALITY_VALIDATION_PLAN_SCHEMA_VERSION = "change_quality_validation_plan_v0"

VALIDATION_CATEGORIES = ("format", "lint", "typecheck", "test")

_CATEGORY_TOKENS = {
    "format": {"fmt", "format", "formatting"},
    "lint": {"lint", "linter", "clippy"},
    "test": {"test", "tests", "pytest"},
}
_TASK_LIMIT = 64
_SAFE_TASK_NAME = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._:-]{0,127}$")
_NON_ORACLE_PATH_PARTS = {
    "fixtures",
    "node_modules",
    "testdata",
    "third_party",
    "vendor",
}


def _task_category(task_name: str) -> str | None:
    tokens = [token for token in re.split(r"[^a-z0-9]+", task_name.lower()) if token]
    token_set = set(tokens)
    compact = "".join(tokens)
    if token_set & _CATEGORY_TOKENS["format"]:
        return "format"
    if token_set & _CATEGORY_TOKENS["lint"]:
        return "lint"
    if (
        token_set & {"typecheck", "typechecking"}
        or compact in {"typecheck", "checktypes", "typechecking"}
        or {
            "type",
            "check",
        }.issubset(token_set)
    ):
        return "typecheck"
    if token_set & _CATEGORY_TOKENS["test"]:
        return "test"
    return None


def _source_ref(path: str, *parts: str) -> str:
    fragment = ".".join(parts)
    return f"{path}#{fragment}" if fragment else path


def _oracle_id(*, source_ref: str, runner: str, task: str) -> str:
    digest = hashlib.sha256(
        f"{source_ref}\0{runner}\0{task}".encode("utf-8")
    ).hexdigest()[:16]
    return f"oracle_{digest}"


def _candidate(
    *,
    source_ref: str,
    runner: str,
    task: str,
    languages: tuple[str, ...],
) -> dict[str, Any] | None:
    if not _SAFE_TASK_NAME.fullmatch(task):
        return None
    category = _task_category(task)
    if category is None:
        return None
    return {
        "oracle_id": _oracle_id(
            source_ref=source_ref,
            runner=runner,
            task=task,
        ),
        "category": category,
        "runner": runner,
        "task": task,
        "source_ref": source_ref,
        "language_hints": list(languages),
        "origin": "repository_declared_task",
        "execution_mode": "host_resolved",
    }


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _python_candidates(path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    tool = _mapping(payload.get("tool"))

    poe_tasks = _mapping(_mapping(tool.get("poe")).get("tasks"))
    for task in sorted(poe_tasks):
        candidate = _candidate(
            source_ref=_source_ref(path, "tool", "poe", "tasks", task),
            runner="poe_task",
            task=task,
            languages=("python",),
        )
        if candidate is not None:
            candidates.append(candidate)

    hatch_envs = _mapping(_mapping(tool.get("hatch")).get("envs"))
    for environment in sorted(hatch_envs):
        scripts = _mapping(_mapping(hatch_envs[environment]).get("scripts"))
        for task in sorted(scripts):
            candidate = _candidate(
                source_ref=_source_ref(
                    path,
                    "tool",
                    "hatch",
                    "envs",
                    environment,
                    "scripts",
                    task,
                ),
                runner="hatch_script",
                task=task,
                languages=("python",),
            )
            if candidate is not None:
                candidates.append(candidate)

    configured_tools = (
        ("mypy", "typecheck"),
        ("pyright", "typecheck"),
        ("pytest", "test"),
    )
    for tool_name, category in configured_tools:
        config_key = "pytest.ini_options" if tool_name == "pytest" else tool_name
        current: Any = tool
        for part in config_key.split("."):
            current = _mapping(current).get(part)
        if current is None:
            continue
        source_ref = _source_ref(path, "tool", *config_key.split("."))
        candidates.append(
            {
                "oracle_id": _oracle_id(
                    source_ref=source_ref,
                    runner=f"{tool_name}_config",
                    task=tool_name,
                ),
                "category": category,
                "runner": f"{tool_name}_config",
                "task": tool_name,
                "source_ref": source_ref,
                "language_hints": ["python"],
                "origin": "repository_tool_config",
                "execution_mode": "host_resolved",
            }
        )
    return candidates


def _node_candidates(path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    scripts = _mapping(payload.get("scripts"))
    for task in sorted(scripts):
        candidate = _candidate(
            source_ref=_source_ref(path, "scripts", task),
            runner="package_script",
            task=task,
            languages=("javascript", "typescript"),
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _cargo_candidates(path: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    aliases = _mapping(payload.get("alias"))
    for task in sorted(aliases):
        candidate = _candidate(
            source_ref=_source_ref(path, "alias", task),
            runner="cargo_alias",
            task=task,
            languages=("rust",),
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _read_manifest(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        content = path.read_text(encoding="utf-8")
        if path.name == "package.json":
            parsed = json.loads(content)
        else:
            parsed = tomllib.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError):
        return None, "manifest_unreadable"
    if not isinstance(parsed, dict):
        return None, "manifest_root_not_object"
    return parsed, None


def _is_non_oracle_manifest(relative: PurePosixPath) -> bool:
    return bool({part.lower() for part in relative.parts} & _NON_ORACLE_PATH_PARTS)


def build_change_quality_validation_plan(
    *,
    repo_root: Path,
    instruction_refs: list[str],
    manifest_refs: list[str],
) -> dict[str, Any]:
    """Discover repository-declared quality tasks without copying task bodies."""
    candidates: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    ignored_manifest_refs: list[str] = []
    for ref in sorted(set(manifest_refs)):
        relative = PurePosixPath(ref)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        if _is_non_oracle_manifest(relative):
            ignored_manifest_refs.append(ref)
            continue
        parser: Callable[[str, dict[str, Any]], list[dict[str, Any]]]
        if relative.name == "pyproject.toml":
            parser = _python_candidates
        elif relative.name == "package.json":
            parser = _node_candidates
        elif relative.as_posix().endswith(".cargo/config.toml"):
            parser = _cargo_candidates
        else:
            continue
        payload, warning = _read_manifest(repo_root / relative.as_posix())
        if warning is not None:
            warnings.append({"source_ref": ref, "code": warning})
            continue
        assert payload is not None
        candidates.extend(parser(ref, payload))

    deduplicated = {
        candidate["oracle_id"]: candidate for candidate in candidates[:_TASK_LIMIT]
    }
    ordered_candidates = sorted(
        deduplicated.values(),
        key=lambda item: (
            VALIDATION_CATEGORIES.index(item["category"]),
            item["source_ref"],
        ),
    )
    covered = {item["category"] for item in ordered_candidates}
    return {
        "schema_version": CHANGE_QUALITY_VALIDATION_PLAN_SCHEMA_VERSION,
        "selection_policy": "repository_declared_only",
        "required_reads": sorted(set(instruction_refs)),
        "candidates": ordered_candidates,
        "unresolved_categories": [
            category for category in VALIDATION_CATEGORIES if category not in covered
        ],
        "ignored_manifest_refs": ignored_manifest_refs,
        "discovery_warnings": warnings,
        "auto_execute": False,
        "task_bodies_included": False,
    }

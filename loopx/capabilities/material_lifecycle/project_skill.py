from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loopx.project_skill_delivery import (
    PROJECT_SKILL_MANAGED_MARKER,
    PROJECT_SKILL_SCOPE,
    PROJECT_SKILL_SCOPE_FILE,
    canonical_project_skill_source,
    install_project_skill,
    inspect_project_skill,
    project_skill_digest,
    project_skill_target,
    uninstall_project_skill,
)

MATERIAL_SKILL_ID = "loopx-material"
MATERIAL_SKILL_SCOPE = PROJECT_SKILL_SCOPE
MATERIAL_SKILL_SCOPE_FILE = PROJECT_SKILL_SCOPE_FILE
MATERIAL_SKILL_MANAGED_MARKER = PROJECT_SKILL_MANAGED_MARKER


def canonical_material_skill_source() -> Path:
    return canonical_project_skill_source(MATERIAL_SKILL_ID)


def project_material_skill_target(
    project: str | Path,
    surface: str = "codex",
) -> Path:
    return project_skill_target(project, MATERIAL_SKILL_ID, surface)


def material_skill_digest(root: Path) -> str:
    return project_skill_digest(root)


def inspect_project_material_skill(
    project: str | Path,
    *,
    surfaces: Iterable[str] | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    return inspect_project_skill(
        project,
        MATERIAL_SKILL_ID,
        surfaces=surfaces,
        source_root=source_root,
    )


def install_project_material_skill(
    project: str | Path,
    *,
    surfaces: Iterable[str] | None = None,
    execute: bool = False,
    source_root: Path | None = None,
) -> dict[str, Any]:
    return install_project_skill(
        project,
        MATERIAL_SKILL_ID,
        surfaces=surfaces,
        execute=execute,
        source_root=source_root,
    )


def uninstall_project_material_skill(
    project: str | Path,
    *,
    surfaces: Iterable[str] | None = None,
    execute: bool = False,
    source_root: Path | None = None,
) -> dict[str, Any]:
    return uninstall_project_skill(
        project,
        MATERIAL_SKILL_ID,
        surfaces=surfaces,
        execute=execute,
        source_root=source_root,
    )

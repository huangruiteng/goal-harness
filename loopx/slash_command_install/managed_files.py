from __future__ import annotations

from pathlib import Path

MANAGED_MARKER_PREFIX = "<!-- loopx-managed-slash-command:v1"
LEGACY_UPGRADABLE_SIGNATURES = (
    "loopx goal-mode setup (NOT Claude Code's built-in /goal)",
    "The output is loopx control-plane SETUP",
    "goalmode_cmd.py",
)
EXISTING_LOOPX_CAPABILITY_SKILL_SIGNATURES = (
    "# LoopX PR Review",
    "Run `loopx pr-review` first",
)


def _is_legacy_upgradable_loopx_file(existing: str) -> bool:
    return any(signature in existing for signature in LEGACY_UPGRADABLE_SIGNATURES)


def _is_existing_loopx_capability_skill(existing: str) -> bool:
    return any(
        signature in existing
        for signature in EXISTING_LOOPX_CAPABILITY_SKILL_SIGNATURES
    )


def _target_status(path: Path, content: str, *, execute: bool) -> str:
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if MANAGED_MARKER_PREFIX not in existing:
            if _is_legacy_upgradable_loopx_file(existing):
                if execute:
                    path.write_text(content, encoding="utf-8")
                return "upgraded_legacy_managed"
            if path.name == "SKILL.md" and _is_existing_loopx_capability_skill(
                existing
            ):
                return "preserved_existing_loopx_skill"
            return "skipped_user_file"
        if existing == content:
            return "unchanged"
        if execute:
            path.write_text(content, encoding="utf-8")
        return "updated"
    if execute:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return "created" if execute else "would_create"


def _retire_managed_file(path: Path, *, execute: bool) -> str | None:
    if not path.exists():
        return None
    existing = path.read_text(encoding="utf-8")
    if MANAGED_MARKER_PREFIX not in existing:
        return "skipped_user_file"
    if execute:
        path.unlink()
    return "retired_managed_file" if execute else "would_retire_managed_file"


def _retire_status(path: Path, *, execute: bool) -> str:
    return _retire_managed_file(path, execute=execute) or "absent"

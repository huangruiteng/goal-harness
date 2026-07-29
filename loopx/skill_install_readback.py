from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


SKILL_INSTALL_READBACK_SCHEMA_VERSION = "loopx_skill_install_readback_v0"
SKILL_INSTALL_READBACK_FILENAME = ".loopx-skill-install.json"
SKILL_INSTALL_OWNER = "loopx_install_script"
SKILL_INSTALL_INTEGRATION_MODE = "fixed_install_script"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_skill_tree(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        return {
            "available": False,
            "sha256": None,
            "file_count": 0,
        }
    digest = hashlib.sha256()
    file_count = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        file_hash = _sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
        file_count += 1
    return {
        "available": True,
        "sha256": digest.hexdigest(),
        "file_count": file_count,
    }


def _git_value(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _source_readback(source_root: Path) -> dict[str, Any]:
    release_manifest_path = source_root / "release.json"
    try:
        release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        release_manifest = {}
    release_source = (
        release_manifest.get("source")
        if isinstance(release_manifest.get("source"), dict)
        else {}
    )
    if release_source:
        revision_kind, revision = next(
            (
                (kind, release_source.get(field))
                for kind, field in (
                    ("git_commit", "git_commit"),
                    ("archive_sha256", "archive_sha256"),
                    ("source_ref", "ref"),
                )
                if release_source.get(field)
            ),
            (None, None),
        )
        return {
            "kind": "release_snapshot",
            "revision": revision,
            "revision_kind": revision_kind,
            "git_dirty": release_source.get("git_dirty"),
        }

    commit = _git_value(source_root, "rev-parse", "HEAD")
    status = _git_value(source_root, "status", "--porcelain")
    return {
        "kind": "local_checkout",
        "revision": commit,
        "revision_kind": "git_commit" if commit else None,
        "git_dirty": bool(status) if commit is not None else None,
    }


def _skills_digest(items: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def build_skill_install_readback(
    *,
    skills_dir: Path,
    skill_ids: Sequence[str],
    source_root: Path,
    installed_at: str | None = None,
) -> dict[str, Any]:
    normalized_ids = sorted(
        {skill_id.strip() for skill_id in skill_ids if skill_id.strip()}
    )
    items = {
        skill_id: hash_skill_tree(skills_dir / skill_id) for skill_id in normalized_ids
    }
    skills_digest = _skills_digest(items)
    source = _source_readback(source_root)
    if not source.get("revision"):
        source["revision"] = skills_digest
        source["revision_kind"] = "skills_digest"
    return {
        "schema_version": SKILL_INSTALL_READBACK_SCHEMA_VERSION,
        "owner": SKILL_INSTALL_OWNER,
        "integration_mode": SKILL_INSTALL_INTEGRATION_MODE,
        "installed_at": installed_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source,
        "materialized_skill_ids": normalized_ids,
        "skills": {
            "digest": skills_digest,
            "items": items,
        },
    }


def write_skill_install_readback(
    *,
    skills_dir: Path,
    skill_ids: Sequence[str],
    source_root: Path,
    installed_at: str | None = None,
) -> Path:
    skills_dir.mkdir(parents=True, exist_ok=True)
    payload = build_skill_install_readback(
        skills_dir=skills_dir,
        skill_ids=skill_ids,
        source_root=source_root,
        installed_at=installed_at,
    )
    target = skills_dir / SKILL_INSTALL_READBACK_FILENAME
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=skills_dir,
        prefix=f"{SKILL_INSTALL_READBACK_FILENAME}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, target)
    return target

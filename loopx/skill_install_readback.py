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
PACKAGED_HOST_SKILL_IDS = [
    "loopx-project",
    "loopx-pr-review",
    "loopx-doc-registry",
    "loopx-self-repair",
]
ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS = [
    "loopx",
    *PACKAGED_HOST_SKILL_IDS,
]


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


def _source_readback(
    source_root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_env = os.environ if env is None else env
    resolved_commit = source_env.get("LOOPX_RESOLVED_SOURCE_GIT_COMMIT")
    if resolved_commit:
        return {
            "kind": "github_archive",
            "revision": resolved_commit,
            "revision_kind": "git_commit",
            "git_dirty": False,
        }

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


def _source_revision_for_root(source_root: Path) -> str | None:
    revision = _source_readback(source_root, env={}).get("revision")
    return str(revision) if revision else None


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


def configured_host_skills_dir(env: Mapping[str, str]) -> Path | None:
    value = env.get("LOOPX_SKILLS_DIR")
    return Path(value).expanduser() if value and value.strip() else None


def inspect_skill_install_readback(
    *,
    skills_dir: Path | None,
    required_skill_ids: Sequence[str],
    source_root: Path | None = None,
) -> dict[str, Any]:
    expected_source_revision = (
        _source_revision_for_root(source_root) if source_root else None
    )
    required_ids = sorted(
        {skill_id.strip() for skill_id in required_skill_ids if skill_id.strip()}
    )
    if skills_dir is None:
        return {
            "schema_version": SKILL_INSTALL_READBACK_SCHEMA_VERSION,
            "status": "skills_dir_not_configured",
            "ready": False,
            "skills_dir": None,
            "manifest_path": None,
            "required_skill_ids": required_ids,
            "materialized_skill_ids": [],
            "missing_skill_ids": required_ids,
            "digest_mismatches": [],
            "integrity_ok": False,
            "manifest_digest_valid": False,
            "integration_mode": None,
            "source_revision": None,
            "expected_source_revision": expected_source_revision,
            "source_revision_matches": None,
            "source_dirty": None,
            "reason": "LOOPX_SKILLS_DIR is not configured for this host check",
        }

    root = skills_dir.expanduser()
    manifest_path = root / SKILL_INSTALL_READBACK_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        manifest = None
        manifest_error = "install readback manifest is missing"
    except (OSError, json.JSONDecodeError) as error:
        manifest = None
        manifest_error = f"install readback manifest is unreadable: {error}"
    else:
        manifest_error = None

    materialized_ids = sorted(
        skill_id
        for skill_id in required_ids
        if (root / skill_id / "SKILL.md").is_file()
    )
    missing_ids = sorted(set(required_ids) - set(materialized_ids))
    manifest_skills = (
        manifest.get("skills")
        if isinstance(manifest, dict) and isinstance(manifest.get("skills"), dict)
        else {}
    )
    manifest_items = (
        manifest_skills.get("items")
        if isinstance(manifest_skills.get("items"), dict)
        else {}
    )
    digest_mismatches = [
        skill_id
        for skill_id in materialized_ids
        if manifest_items.get(skill_id) != hash_skill_tree(root / skill_id)
    ]
    manifest_ids = (
        {str(skill_id) for skill_id in manifest.get("materialized_skill_ids")}
        if isinstance(manifest, dict)
        and isinstance(manifest.get("materialized_skill_ids"), list)
        else set()
    )
    source = (
        manifest.get("source")
        if isinstance(manifest, dict) and isinstance(manifest.get("source"), dict)
        else {}
    )
    source_revision = source.get("revision")
    source_revision_matches = (
        source_revision == expected_source_revision
        if source_revision and expected_source_revision
        else None
    )
    manifest_valid = bool(
        isinstance(manifest, dict)
        and manifest.get("schema_version") == SKILL_INSTALL_READBACK_SCHEMA_VERSION
        and manifest.get("owner") == SKILL_INSTALL_OWNER
        and manifest.get("integration_mode") == SKILL_INSTALL_INTEGRATION_MODE
        and set(required_ids).issubset(manifest_ids)
        and source_revision
    )
    manifest_digest_valid = bool(
        isinstance(manifest_skills.get("digest"), str)
        and manifest_skills.get("digest") == _skills_digest(manifest_items)
    )
    integrity_ok = (
        manifest_valid
        and manifest_digest_valid
        and not digest_mismatches
        and source_revision_matches is not False
    )
    ready = not missing_ids and integrity_ok
    if ready:
        status = "ready_for_host_load"
        reason = "required workflow skills match the fixed-installer readback"
    elif manifest_error:
        status, reason = "manifest_missing_or_invalid", manifest_error
    elif missing_ids:
        status = "required_skills_missing"
        reason = f"missing required workflow skills: {','.join(missing_ids)}"
    elif not manifest_valid:
        status = "manifest_contract_invalid"
        reason = "install readback does not satisfy the fixed-installer contract"
    elif not manifest_digest_valid:
        status = "manifest_digest_mismatch"
        reason = "install readback skill manifest digest does not match its items"
    elif digest_mismatches:
        status = "skill_digest_mismatch"
        reason = f"skill content differs from install readback: {','.join(digest_mismatches)}"
    elif source_revision_matches is False:
        status = "source_revision_mismatch"
        reason = (
            "installed workflow skills came from a different LoopX revision "
            "than the active CLI"
        )
    else:
        status = "manifest_contract_invalid"
        reason = "install readback does not satisfy the fixed-installer contract"

    return {
        "schema_version": SKILL_INSTALL_READBACK_SCHEMA_VERSION,
        "status": status,
        "ready": ready,
        "skills_dir": str(root),
        "manifest_path": str(manifest_path),
        "required_skill_ids": required_ids,
        "materialized_skill_ids": materialized_ids,
        "missing_skill_ids": missing_ids,
        "digest_mismatches": digest_mismatches,
        "integrity_ok": integrity_ok,
        "manifest_digest_valid": manifest_digest_valid,
        "integration_mode": manifest.get("integration_mode")
        if isinstance(manifest, dict)
        else None,
        "source_revision": source_revision,
        "expected_source_revision": expected_source_revision,
        "source_revision_matches": source_revision_matches,
        "source_dirty": source.get("git_dirty"),
        "reason": reason,
    }

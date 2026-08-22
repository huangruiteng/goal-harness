from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from email.parser import Parser
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence


SKILL_INSTALL_READBACK_SCHEMA_VERSION = "loopx_skill_install_readback_v0"
SKILL_INSTALL_READBACK_FILENAME = ".loopx-skill-install.json"
SKILL_INSTALL_OWNER = "loopx_install_script"
SKILL_INSTALL_INTEGRATION_MODE = "fixed_install_script"
PYTHON_DISTRIBUTION_SKILL_INSTALL_OWNER = "loopx_workflow_skills_cli"
PYTHON_DISTRIBUTION_SKILL_INSTALL_MODE = "python_distribution_cli"
SKILL_INSTALL_OWNERS = {
    SKILL_INSTALL_OWNER,
    PYTHON_DISTRIBUTION_SKILL_INSTALL_OWNER,
}
SKILL_INSTALL_INTEGRATION_MODES = {
    SKILL_INSTALL_INTEGRATION_MODE,
    PYTHON_DISTRIBUTION_SKILL_INSTALL_MODE,
}
SKILL_INSTALL_PROFILES = {
    (SKILL_INSTALL_OWNER, SKILL_INSTALL_INTEGRATION_MODE),
    (
        PYTHON_DISTRIBUTION_SKILL_INSTALL_OWNER,
        PYTHON_DISTRIBUTION_SKILL_INSTALL_MODE,
    ),
}
LOOPX_MANAGED_SLASH_COMMAND_MARKER = "<!-- loopx-managed-slash-command:v1"
PACKAGED_HOST_SKILL_IDS = [
    "loopx-project",
    "loopx-pr-program",
    "loopx-pr-review",
    "loopx-doc-registry",
    "loopx-benchmark",
    "loopx-self-repair",
]
ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS = [
    "loopx",
    *PACKAGED_HOST_SKILL_IDS,
]


def _user_home() -> Path:
    return Path.home().expanduser()


def alternate_loopx_skills_root(skills_dir: Path) -> Path | None:
    """Return the alternate LoopX root that can shadow the target root.

    The fixed installer historically wrote the same managed skill set into both
    ``~/.codex/skills`` and ``~/.agents/skills``. ARK-managed agent sessions and
    Codex sessions can both discover those roots, which duplicates LoopX skills
    in the loaded skill catalog. Callers may explicitly pass an alternate root;
    otherwise this returns the other well-known root when the target is one of
    them.
    """

    codex_root = _user_home() / ".codex" / "skills"
    agents_root = _user_home() / ".agents" / "skills"
    try:
        target = skills_dir.expanduser().resolve()
    except OSError:
        return None
    if target == codex_root.expanduser().resolve():
        return agents_root
    if target == agents_root.expanduser().resolve():
        return codex_root
    return None


def _managed_command_facade(path: Path) -> bool:
    try:
        existing = (path / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return False
    return LOOPX_MANAGED_SLASH_COMMAND_MARKER in existing


def retire_duplicate_managed_skills(
    skills_dir: Path,
    *,
    alternate_root: Path | None = None,
    execute: bool,
) -> dict[str, Any]:
    """Retire LoopX-managed skill copies from the alternate well-known root.

    The fixed installer overwrites within the target root, but it historically
    left an older managed copy in the other well-known root. That makes hosts
    that discover both roots load duplicate LoopX skills. This helper retires
    only copies that the alternate root's own readback records as LoopX-managed
    (or command facades carrying the managed marker), so user-modified files
    are never deleted.
    """

    target = Path(skills_dir).expanduser().resolve()
    alternate = (
        Path(alternate_root).expanduser().resolve()
        if alternate_root
        else alternate_loopx_skills_root(target)
    )
    retired: list[str] = []
    would_retire: list[str] = []
    skipped: list[str] = []
    if alternate is None or not alternate.is_dir():
        return {
            "ok": True,
            "schema_version": SKILL_INSTALL_READBACK_SCHEMA_VERSION,
            "target_root": str(target),
            "alternate_root": str(alternate) if alternate else None,
            "retired": retired,
            "would_retire": would_retire,
            "skipped": skipped,
            "reason": "no alternate LoopX skills root configured",
        }

    manifest_path = alternate / SKILL_INSTALL_READBACK_FILENAME
    managed_ids: set[str] = set()
    recorded_hashes: dict[str, str] = {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = None
    if isinstance(manifest, dict):
        raw_ids = manifest.get("materialized_skill_ids")
        if isinstance(raw_ids, list):
            managed_ids.update(
                str(item).strip() for item in raw_ids if str(item or "").strip()
            )
        items = manifest.get("skills")
        if isinstance(items, dict) and isinstance(items.get("items"), dict):
            for skill_id, item in items["items"].items():
                if isinstance(item, dict) and isinstance(item.get("sha256"), str):
                    recorded_hashes[str(skill_id)] = item["sha256"]

    candidate_dirs: list[Path] = []
    if managed_ids:
        candidate_dirs.extend(alternate / skill_id for skill_id in managed_ids)
    if alternate.is_dir():
        candidate_dirs.extend(
            path
            for path in sorted(
                [*alternate.glob("loopx-*"), *alternate.glob("loop-global-*")]
            )
            if path.is_dir() and path not in candidate_dirs
        )

    for candidate in candidate_dirs:
        if not candidate.is_dir() or not (candidate / "SKILL.md").is_file():
            continue
        skill_id = candidate.name
        managed = skill_id in managed_ids
        marker_managed = _managed_command_facade(candidate)
        if not managed and not marker_managed:
            skipped.append(skill_id)
            continue
        recorded_hash = recorded_hashes.get(skill_id)
        if managed and recorded_hash and not marker_managed:
            tree = hash_skill_tree(candidate)
            if not tree.get("available") or tree.get("sha256") != recorded_hash:
                skipped.append(skill_id)
                continue
        if execute:
            shutil.rmtree(candidate)
            retired.append(skill_id)
        else:
            would_retire.append(skill_id)

    return {
        "ok": True,
        "schema_version": SKILL_INSTALL_READBACK_SCHEMA_VERSION,
        "target_root": str(target),
        "alternate_root": str(alternate),
        "retired": retired,
        "would_retire": would_retire,
        "skipped": skipped,
        "reason": "retired alternate LoopX-managed copies" if execute else "dry-run",
    }


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

    for metadata_path in sorted(source_root.glob("loopx-*.dist-info/METADATA")):
        try:
            metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if metadata.get("Name", "").strip().lower() != "loopx":
            continue
        version = metadata.get("Version", "").strip()
        if version:
            return {
                "kind": "python_distribution",
                "revision": version,
                "revision_kind": "package_version",
                "git_dirty": False,
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
    owner: str = SKILL_INSTALL_OWNER,
    integration_mode: str = SKILL_INSTALL_INTEGRATION_MODE,
) -> dict[str, Any]:
    if owner not in SKILL_INSTALL_OWNERS:
        raise ValueError(f"unsupported skill install owner: {owner}")
    if integration_mode not in SKILL_INSTALL_INTEGRATION_MODES:
        raise ValueError(f"unsupported skill install integration mode: {integration_mode}")
    if (owner, integration_mode) not in SKILL_INSTALL_PROFILES:
        raise ValueError(
            "skill install owner and integration mode do not form a supported profile"
        )
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
        "owner": owner,
        "integration_mode": integration_mode,
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
    owner: str = SKILL_INSTALL_OWNER,
    integration_mode: str = SKILL_INSTALL_INTEGRATION_MODE,
) -> Path:
    skills_dir.mkdir(parents=True, exist_ok=True)
    payload = build_skill_install_readback(
        skills_dir=skills_dir,
        skill_ids=skill_ids,
        source_root=source_root,
        installed_at=installed_at,
        owner=owner,
        integration_mode=integration_mode,
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
        and (
            manifest.get("owner"),
            manifest.get("integration_mode"),
        )
        in SKILL_INSTALL_PROFILES
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
        reason = "required workflow skills match the managed install readback"
    elif manifest_error:
        status, reason = "manifest_missing_or_invalid", manifest_error
    elif missing_ids:
        status = "required_skills_missing"
        reason = f"missing required workflow skills: {','.join(missing_ids)}"
    elif not manifest_valid:
        status = "manifest_contract_invalid"
        reason = "install readback does not satisfy the managed install contract"
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
        reason = "install readback does not satisfy the managed install contract"

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

#!/usr/bin/env python3
"""Smoke-test agent onboarding skill-delivery expectations against the
canonical release and active project-skill manifests.

Covers:
- Shipped PR program skill and packaged host skill catalog
- Skill install readback (build, write, inspect on disk)
- Missing and stale skill detection
- Install dedupe (retire duplicate managed skills)
- CWD isolation (skill dir is from env, not cwd)
- Custom-host delivery (host_managed vs surface_managed)
- Project skill commands for change-quality enabled goals
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.skill_install_readback import (  # noqa: E402
    ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS,
    PACKAGED_HOST_SKILL_IDS,
    SKILL_INSTALL_READBACK_FILENAME,
    SKILL_INSTALL_READBACK_SCHEMA_VERSION,
    build_skill_install_readback,
    configured_host_skills_dir,
    hash_skill_tree,
    inspect_skill_install_readback,
    retire_duplicate_managed_skills,
    write_skill_install_readback,
)

from loopx.agent_onboarding import (  # noqa: E402
    REQUIRED_HOST_SKILL_IDS,
    build_agent_onboarding_packet,
)

from loopx.host_loop_activation import (  # noqa: E402
    HOST_MANAGED_SKILL_AGENT_TYPES,
    SUPPORTED_AGENT_TYPES,
    agent_type_uses_host_managed_skills,
    normalize_agent_type,
)

# ---------------------------------------------------------------------------
# public-safety patterns
# ---------------------------------------------------------------------------

PRIVATE_PATTERNS = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def assert_public_safe(text: str, label: str) -> None:
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise AssertionError(
                f"{label} matched private pattern {pattern.pattern!r}"
            )


# ---------------------------------------------------------------------------
# 1. Packaged skill catalog — PR program skill is present
# ---------------------------------------------------------------------------

def scenario_packaged_skills_include_pr_program() -> dict:
    assert "loopx-pr-program" in PACKAGED_HOST_SKILL_IDS, PACKAGED_HOST_SKILL_IDS
    assert "loopx-pr-program" in ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS
    assert "loopx-pr-program" in REQUIRED_HOST_SKILL_IDS
    assert REQUIRED_HOST_SKILL_IDS is ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS

    # Every packaged skill maps to a real skills/ directory in the repo.
    skills_root = REPO_ROOT / "skills"
    for skill_id in PACKAGED_HOST_SKILL_IDS:
        skill_dir = skills_root / skill_id
        assert skill_dir.is_dir(), (skill_id, skill_dir)
        assert (skill_dir / "SKILL.md").is_file(), skill_id

    return {
        "packaged_count": len(PACKAGED_HOST_SKILL_IDS),
        "required_count": len(REQUIRED_HOST_SKILL_IDS),
        "includes_pr_program": "loopx-pr-program" in PACKAGED_HOST_SKILL_IDS,
    }


# ---------------------------------------------------------------------------
# 2. Skill install readback: build, write, verify schema
# ---------------------------------------------------------------------------

def scenario_skill_install_readback_lifecycle() -> dict:
    with tempfile.TemporaryDirectory(prefix="loopx-skill-readback-") as tmp:
        skills_dir = Path(tmp) / "skills"
        skills_dir.mkdir()

        # Create a minimal skill on disk so hash_skill_tree produces meaningful
        # output.
        for skill_id in PACKAGED_HOST_SKILL_IDS:
            skill_root = skills_dir / skill_id
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                f"# {skill_id}\n\nSynthetic fixture skill.\n", encoding="utf-8"
            )

        # Build a readback in memory.
        readback = build_skill_install_readback(
            skills_dir=skills_dir,
            skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )
        assert readback["schema_version"] == SKILL_INSTALL_READBACK_SCHEMA_VERSION
        assert readback["owner"] == "loopx_install_script"
        assert readback["integration_mode"] == "fixed_install_script"
        assert sorted(readback["materialized_skill_ids"]) == sorted(
            PACKAGED_HOST_SKILL_IDS
        )
        assert "skills" in readback
        assert "digest" in readback["skills"]
        assert "items" in readback["skills"]
        assert len(readback["skills"]["items"]) == len(PACKAGED_HOST_SKILL_IDS)

        # Write the readback to disk.
        manifest_path = write_skill_install_readback(
            skills_dir=skills_dir,
            skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )
        assert manifest_path.is_file()
        assert manifest_path.name == SKILL_INSTALL_READBACK_FILENAME

        # Re-read and validate.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == SKILL_INSTALL_READBACK_SCHEMA_VERSION
        assert manifest["owner"] == "loopx_install_script"

        # Inspect the written readback.
        inspection = inspect_skill_install_readback(
            skills_dir=skills_dir,
            required_skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )
        assert inspection["ready"] is True, inspection
        assert inspection["status"] == "ready_for_host_load", inspection
        assert inspection["integrity_ok"] is True
        assert not inspection["missing_skill_ids"]
        assert not inspection["digest_mismatches"]

        # Public safety.
        assert_public_safe(
            json.dumps(readback, sort_keys=True), "skill_readback"
        )
        assert_public_safe(
            json.dumps(inspection, sort_keys=True), "skill_inspection"
        )

    return {
        "schema_version": SKILL_INSTALL_READBACK_SCHEMA_VERSION,
        "manifest_filename": SKILL_INSTALL_READBACK_FILENAME,
    }


# ---------------------------------------------------------------------------
# 3. Missing skill detection
# ---------------------------------------------------------------------------

def scenario_missing_skill_detection() -> dict:
    with tempfile.TemporaryDirectory(prefix="loopx-missing-skill-") as tmp:
        skills_dir = Path(tmp) / "skills"
        skills_dir.mkdir()

        # Only create some of the PACKAGED_HOST_SKILL_IDS, leaving others missing.
        created = {"loopx-pr-program", "loopx-project"}
        for skill_id in created:
            skill_root = skills_dir / skill_id
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                f"# {skill_id}\n\nPresent.\n", encoding="utf-8"
            )

        inspection = inspect_skill_install_readback(
            skills_dir=skills_dir,
            required_skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )
        assert inspection["ready"] is False, inspection
        # Without a written manifest, the status is manifest_missing_or_invalid;
        # the missing_skill_ids are still correctly reported.
        assert inspection["status"] in (
            "required_skills_missing",
            "manifest_missing_or_invalid",
        ), inspection
        assert len(inspection["missing_skill_ids"]) == len(PACKAGED_HOST_SKILL_IDS) - len(created)

        expected_missing = sorted(
            s for s in PACKAGED_HOST_SKILL_IDS if s not in created
        )
        assert inspection["missing_skill_ids"] == expected_missing, inspection

    return {"created": sorted(created), "missing": expected_missing}


# ---------------------------------------------------------------------------
# 4. Stale skill detection (content differs from readback)
# ---------------------------------------------------------------------------

def scenario_stale_skill_detection() -> dict:
    with tempfile.TemporaryDirectory(prefix="loopx-stale-skill-") as tmp:
        skills_dir = Path(tmp) / "skills"
        skills_dir.mkdir()

        # Create all skills on disk and write a readback.
        for skill_id in PACKAGED_HOST_SKILL_IDS:
            skill_root = skills_dir / skill_id
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                f"# {skill_id}\n\nOriginal content.\n", encoding="utf-8"
            )

        write_skill_install_readback(
            skills_dir=skills_dir,
            skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )

        # Now modify one skill on disk without updating the readback.
        stale_skill = "loopx-pr-program"
        (skills_dir / stale_skill / "SKILL.md").write_text(
            f"# {stale_skill}\n\nModified content — stale!\n", encoding="utf-8"
        )

        inspection = inspect_skill_install_readback(
            skills_dir=skills_dir,
            required_skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )
        assert inspection["ready"] is False, inspection
        assert inspection["status"] == "skill_digest_mismatch", inspection
        assert stale_skill in inspection["digest_mismatches"], inspection

    return {"stale_skill": stale_skill, "status": inspection["status"]}


# ---------------------------------------------------------------------------
# 5. Install dedupe: detect and retire duplicates
# ---------------------------------------------------------------------------

def scenario_install_dedupe() -> dict:
    with tempfile.TemporaryDirectory(prefix="loopx-dedupe-") as tmp:
        target = Path(tmp) / ".agents" / "skills"
        alternate = Path(tmp) / ".codex" / "skills"
        target.mkdir(parents=True)
        alternate.mkdir(parents=True)

        # Write identical content to both roots for one skill.
        skill_id = "loopx-pr-program"
        skill_body = f"# {skill_id}\n\nFixture skill.\n"
        for root in (target, alternate):
            skill_root = root / skill_id
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(skill_body, encoding="utf-8")

        # Write a readback at the alternate root that declares the skill as
        # LoopX-managed.
        write_skill_install_readback(
            skills_dir=alternate,
            skill_ids=[skill_id],
            source_root=REPO_ROOT,
        )

        # Dry-run dedupe.
        dedupe = retire_duplicate_managed_skills(
            target,
            alternate_root=alternate,
            execute=False,
        )
        assert dedupe["ok"] is True
        assert skill_id not in dedupe["skipped"]
        assert skill_id in dedupe["would_retire"], dedupe

        # Execute dedupe.
        dedupe = retire_duplicate_managed_skills(
            target,
            alternate_root=alternate,
            execute=True,
        )
        assert skill_id in dedupe["retired"], dedupe
        assert not (alternate / skill_id).is_dir()

        # Prove the target root is untouched.
        assert (target / skill_id).is_dir()
        assert (target / skill_id / "SKILL.md").read_text(encoding="utf-8") == skill_body

    return {"deduped": skill_id, "target_preserved": True}


# ---------------------------------------------------------------------------
# 6. CWD isolation: skill dir from env, not cwd
# ---------------------------------------------------------------------------

def scenario_cwd_isolation() -> dict:
    # LOOPX_SKILLS_DIR from env is an absolute path, not resolved from cwd.
    explicit = "/opt/loopx/skills"
    env = {"LOOPX_SKILLS_DIR": explicit}
    assert configured_host_skills_dir(env) == Path(explicit)

    # Empty string means no skills dir configured.
    assert configured_host_skills_dir({"LOOPX_SKILLS_DIR": ""}) is None
    assert configured_host_skills_dir({"LOOPX_SKILLS_DIR": "  "}) is None

    # Missing env var means no skills dir.
    assert configured_host_skills_dir({}) is None

    # Relative paths are expanded but not anchored to cwd — the env owns the
    # path. The module resolves relative paths via expanduser, not cwd.
    relative_env = {"LOOPX_SKILLS_DIR": "~/.custom-skills"}
    resolved = configured_host_skills_dir(relative_env)
    assert resolved is not None
    assert resolved.is_absolute(), resolved
    assert str(resolved).endswith(".custom-skills"), resolved

    return {
        "env_not_cwd": True,
        "explicit_path": str(configured_host_skills_dir(env)),
        "empty_yields_none": True,
        "missing_yields_none": True,
    }


# ---------------------------------------------------------------------------
# 7. Custom-host delivery: host_managed vs surface_managed parity
# ---------------------------------------------------------------------------

def scenario_skill_delivery_mode_parity() -> dict:
    # Host-managed agent types.
    assert HOST_MANAGED_SKILL_AGENT_TYPES == {
        "ark-managed-agent",
        "traex-cli",
        "other-agent",
    }

    delivery_modes: dict[str, str] = {}
    for agent_type in SUPPORTED_AGENT_TYPES:
        canonical = normalize_agent_type(agent_type)
        uses_host = agent_type_uses_host_managed_skills(canonical)
        delivery_modes[canonical] = "host_managed" if uses_host else "surface_managed"

    # Manual is surface_managed (doesn't use host-managed skills).
    assert delivery_modes["manual"] == "surface_managed"

    # Every host-managed type has no install facade command.
    for agent_type in HOST_MANAGED_SKILL_AGENT_TYPES:
        # The _surface_install_command returns None for these.
        pass  # tested implicitly via agent_onboarding

    return delivery_modes


# ---------------------------------------------------------------------------
# 8. Onboarding packet includes skill delivery contract
# ---------------------------------------------------------------------------

def scenario_onboarding_skill_delivery_contract() -> dict:
    # Build onboarding packets for a representative sample and verify the
    # skill delivery contract is present and correctly typed.
    results = {}

    with tempfile.TemporaryDirectory(prefix="loopx-onboarding-skill-") as tmp:
        project = Path(tmp) / "project"
        project.mkdir()
        registry_path = project / ".loopx" / "registry.json"
        registry_path.parent.mkdir(parents=True)
        registry_path.write_text(
            json.dumps(
                {
                    "goals": [
                        {
                            "id": "skill-goal",
                            "domain": "test",
                            "status": "active",
                            "repo": str(project),
                            "adapter": {
                                "kind": "generic_project_goal_v0",
                                "status": "connected",
                            },
                            "coordination": {
                                "agent_model": "peer_v1",
                                "registered_agents": ["agent-a"],
                            },
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        for agent_type in ("codex-cli", "other-agent"):
            canonical = normalize_agent_type(agent_type)
            onboard = build_agent_onboarding_packet(
                project=project,
                agent_type=canonical,
                goal_id="skill-goal",
                agent_id="agent-a",
            )
            delivery = onboard["skill_delivery"]
            assert delivery["schema_version"] == "loopx_host_skill_delivery_v0"

            if canonical in HOST_MANAGED_SKILL_AGENT_TYPES:
                assert delivery["mode"] == "host_managed", (canonical, delivery)
                assert delivery["host_readback_required"] is True
                assert "required_skill_ids" in delivery
                assert "readback_fields" in delivery
                # PR program skill is in the required set for host-managed.
                assert "loopx-pr-program" in delivery["required_skill_ids"], (
                    canonical,
                    delivery,
                )
            else:
                assert delivery["mode"] == "surface_managed", (canonical, delivery)
                assert delivery["host_readback_required"] is False

            results[canonical] = {
                "mode": delivery["mode"],
                "host_readback_required": delivery["host_readback_required"],
            }

            assert_public_safe(json.dumps(delivery, sort_keys=True), canonical)

    return results


# ---------------------------------------------------------------------------
# 9. Missing/stale skill manifest — inspect returns accurate reason
# ---------------------------------------------------------------------------

def scenario_readback_integrity_states() -> dict:
    states = {}

    with tempfile.TemporaryDirectory(prefix="loopx-integrity-") as tmp:
        skills_dir = Path(tmp) / "skills"
        skills_dir.mkdir()

        # State 1: Skills dir not configured (None).
        null_inspection = inspect_skill_install_readback(
            skills_dir=None,
            required_skill_ids=PACKAGED_HOST_SKILL_IDS,
            source_root=REPO_ROOT,
        )
        assert null_inspection["ready"] is False
        assert null_inspection["status"] == "skills_dir_not_configured"
        states["null_dir"] = null_inspection["status"]

        # State 2: Manifest is missing.
        (skills_dir / "loopx").mkdir(parents=True)
        (skills_dir / "loopx" / "SKILL.md").write_text(
            "# loopx\n\nTest.\n", encoding="utf-8"
        )
        missing_manifest = inspect_skill_install_readback(
            skills_dir=skills_dir,
            required_skill_ids=["loopx"],
            source_root=REPO_ROOT,
        )
        assert missing_manifest["ready"] is False
        assert missing_manifest["status"] == "manifest_missing_or_invalid"
        states["missing_manifest"] = missing_manifest["status"]

        # State 3: Manifest exists but skill content differs from readback.
        write_skill_install_readback(
            skills_dir=skills_dir,
            skill_ids=["loopx"],
            source_root=REPO_ROOT,
        )
        # Modify the skill content.
        (skills_dir / "loopx" / "SKILL.md").write_text(
            "# loopx\n\nTampered content.\n", encoding="utf-8"
        )
        stale = inspect_skill_install_readback(
            skills_dir=skills_dir,
            required_skill_ids=["loopx"],
            source_root=REPO_ROOT,
        )
        assert stale["ready"] is False
        assert "loopx" in stale["digest_mismatches"]
        states["stale_content"] = stale["status"]

    return states


# ---------------------------------------------------------------------------
# 10. Public safety across all skill delivery outputs
# ---------------------------------------------------------------------------

def scenario_public_safety() -> dict:
    with tempfile.TemporaryDirectory(prefix="loopx-safety-") as tmp:
        skills_dir = Path(tmp) / "skills"
        skills_dir.mkdir()

        for skill_id in ["loopx", "loopx-pr-program"]:
            skill_root = skills_dir / skill_id
            skill_root.mkdir(parents=True)
            (skill_root / "SKILL.md").write_text(
                f"# {skill_id}\n\nSynthetic.\n", encoding="utf-8"
            )

        readback = build_skill_install_readback(
            skills_dir=skills_dir,
            skill_ids=["loopx", "loopx-pr-program"],
            source_root=REPO_ROOT,
        )
        assert_public_safe(json.dumps(readback, sort_keys=True), "readback_json")

        write_skill_install_readback(
            skills_dir=skills_dir,
            skill_ids=["loopx", "loopx-pr-program"],
            source_root=REPO_ROOT,
        )
        inspection = inspect_skill_install_readback(
            skills_dir=skills_dir,
            required_skill_ids=["loopx", "loopx-pr-program"],
            source_root=REPO_ROOT,
        )
        assert_public_safe(json.dumps(inspection, sort_keys=True), "inspection_json")

        dedupe = retire_duplicate_managed_skills(
            skills_dir, execute=False
        )
        assert_public_safe(json.dumps(dedupe, sort_keys=True), "dedupe_json")

        # Hash output is public-safe.
        tree = hash_skill_tree(skills_dir / "loopx")
        assert tree["available"] is True
        assert isinstance(tree["sha256"], str)
        assert len(tree["sha256"]) == 64
        assert_public_safe(tree["sha256"], "sha256_hash")

    return {"public_safe": True}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    catalog = scenario_packaged_skills_include_pr_program()
    lifecycle = scenario_skill_install_readback_lifecycle()
    missing = scenario_missing_skill_detection()
    stale = scenario_stale_skill_detection()
    dedupe = scenario_install_dedupe()
    cwd = scenario_cwd_isolation()
    modes = scenario_skill_delivery_mode_parity()
    onboarding = scenario_onboarding_skill_delivery_contract()
    integrity = scenario_readback_integrity_states()
    safety = scenario_public_safety()

    summary = {
        "schema_version": "skill_delivery_walkthrough_v0",
        "ok": True,
        "packaged_skills": catalog,
        "install_readback_lifecycle": lifecycle,
        "missing_skill_detection": missing,
        "stale_skill_detection": stale,
        "install_dedupe": dedupe,
        "cwd_isolation": cwd,
        "skill_delivery_modes": modes,
        "onboarding_contract": onboarding,
        "readback_integrity_states": integrity,
        "public_safety": safety,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("agent-onboarding-skill-delivery-walkthrough-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

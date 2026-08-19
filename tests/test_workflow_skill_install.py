from __future__ import annotations

import json
from pathlib import Path

from loopx.skill_install_readback import (
    ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS,
    PACKAGED_HOST_SKILL_IDS,
    PYTHON_DISTRIBUTION_SKILL_INSTALL_MODE,
    PYTHON_DISTRIBUTION_SKILL_INSTALL_OWNER,
    SKILL_INSTALL_READBACK_FILENAME,
)
from loopx.workflow_skill_install import (
    resolve_workflow_skill_source,
    workflow_skill_install,
)


def test_source_checkout_contains_packaged_workflow_skills() -> None:
    source = resolve_workflow_skill_source()

    assert source["available"] is True
    assert source["kind"] == "source_checkout"
    for skill_id in PACKAGED_HOST_SKILL_IDS:
        assert (Path(source["skills_root"]) / skill_id / "SKILL.md").is_file()


def test_install_is_idempotent_and_uninstall_removes_managed_skills(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "host skills"

    installed = workflow_skill_install(skills_dir=skills_dir, execute=True)

    assert installed["ok"] is True
    assert installed["after"]["ready"] is True
    assert sorted(installed["after"]["materialized_skill_ids"]) == sorted(
        ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS
    )
    assert set(installed["installed"]) == set(PACKAGED_HOST_SKILL_IDS)
    assert "'" in installed["rollback_command"]
    manifest = json.loads(
        (skills_dir / SKILL_INSTALL_READBACK_FILENAME).read_text(encoding="utf-8")
    )
    assert manifest["owner"] == PYTHON_DISTRIBUTION_SKILL_INSTALL_OWNER
    assert manifest["integration_mode"] == PYTHON_DISTRIBUTION_SKILL_INSTALL_MODE

    repeated = workflow_skill_install(skills_dir=skills_dir, execute=True)

    assert repeated["ok"] is True
    assert set(repeated["installed"].values()) == {"unchanged"}
    assert repeated["entry"]["status"] == "unchanged"

    removed = workflow_skill_install(
        skills_dir=skills_dir,
        execute=True,
        uninstall=True,
    )

    assert removed["ok"] is True
    assert sorted(removed["result"]["removed"]) == sorted(
        ARK_MANAGED_AGENT_REQUIRED_SKILL_IDS
    )
    assert not (skills_dir / SKILL_INSTALL_READBACK_FILENAME).exists()


def test_uninstall_preserves_locally_modified_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    installed = workflow_skill_install(skills_dir=skills_dir, execute=True)
    assert installed["ok"] is True

    modified = skills_dir / "loopx-project" / "SKILL.md"
    modified.write_text(modified.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")

    removed = workflow_skill_install(
        skills_dir=skills_dir,
        execute=True,
        uninstall=True,
    )

    assert removed["ok"] is False
    assert removed["result"]["preserved_modified"] == ["loopx-project"]
    assert modified.is_file()
    assert (skills_dir / SKILL_INSTALL_READBACK_FILENAME).is_file()


def test_inspect_does_not_create_target(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"

    inspected = workflow_skill_install(skills_dir=skills_dir)

    assert inspected["ok"] is True
    assert inspected["operation"] == "inspect"
    assert inspected["install_required"] is True
    assert not skills_dir.exists()

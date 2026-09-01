from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from loopx import file_lock
from loopx import workflow_skill_install as install_module
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
    assert "loopx-benchmark" in PACKAGED_HOST_SKILL_IDS
    for skill_id in PACKAGED_HOST_SKILL_IDS:
        assert (Path(source["skills_root"]) / skill_id / "SKILL.md").is_file()


def test_pip_target_distribution_finds_filtered_data_file_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution_root = tmp_path / "runtime" / "site-packages"
    module_file = distribution_root / "loopx" / "workflow_skill_install.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("# fixture\n", encoding="utf-8")
    skills_root = distribution_root / "share" / "loopx" / "skills"
    for skill_id in PACKAGED_HOST_SKILL_IDS:
        skill_dir = skills_root / skill_id
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n", encoding="utf-8")

    class TargetDistribution:
        version = "0.5.3"
        files: tuple[Path, ...] = ()

        @staticmethod
        def locate_file(path: str) -> Path:
            return distribution_root / path

    monkeypatch.setattr(install_module, "__file__", str(module_file))
    monkeypatch.setattr(
        install_module,
        "distribution",
        lambda package: TargetDistribution() if package == "loopx" else None,
    )

    source = resolve_workflow_skill_source()

    assert source["available"] is True
    assert source["kind"] == "python_distribution"
    assert source["skills_root"] == skills_root
    assert source["source_root"] == distribution_root
    assert source["distribution_version"] == "0.5.3"


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
    assert (skills_dir / "loopx-benchmark" / "SKILL.md").is_file()
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


class _ByteRangeLockBackend:
    """Stand-in for ``msvcrt`` so the Windows lock branch runs on any host."""

    LK_NBLCK = 1
    LK_UNLCK = 0

    def __init__(self) -> None:
        self.modes: list[int] = []

    def locking(self, file_descriptor: int, mode: int, length: int) -> None:
        self.modes.append(mode)


def test_install_takes_the_windows_lock_branch_without_fcntl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _ByteRangeLockBackend()
    monkeypatch.setattr(file_lock, "fcntl", None)
    monkeypatch.setattr(file_lock, "msvcrt", backend)
    skills_dir = tmp_path / "skills"

    installed = workflow_skill_install(skills_dir=skills_dir, execute=True)

    assert installed["ok"] is True
    assert installed["after"]["ready"] is True
    assert backend.modes == [backend.LK_NBLCK, backend.LK_UNLCK]


def test_install_serializes_on_the_shared_workflow_skill_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skills_dir = tmp_path / "skills"
    held: list[Path] = []
    locked: list[Path] = []
    real_readback = install_module.write_skill_install_readback

    @contextmanager
    def recording_lock(path: Path, **kwargs: Any) -> Iterator[Path]:
        locked.append(path)
        held.append(path)
        try:
            yield path
        finally:
            held.pop()

    def recording_readback(**kwargs: Any) -> Any:
        assert held, "the install readback was written outside the lock"
        return real_readback(**kwargs)

    monkeypatch.setattr(install_module, "exclusive_file_lock", recording_lock)
    monkeypatch.setattr(install_module, "write_skill_install_readback", recording_readback)

    installed = workflow_skill_install(skills_dir=skills_dir, execute=True)

    assert installed["ok"] is True
    assert locked == [skills_dir / ".loopx-workflow-skills"]
    assert held == []


def test_inspect_does_not_create_target(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"

    inspected = workflow_skill_install(skills_dir=skills_dir)

    assert inspected["ok"] is True
    assert inspected["operation"] == "inspect"
    assert inspected["install_required"] is True
    assert not skills_dir.exists()


def test_install_and_inspect_dsh_native_entry(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"

    installed = workflow_skill_install(
        skills_dir=skills_dir,
        execute=True,
        host_surface="deepseek-harness-native",
    )

    assert installed["ok"] is True
    assert installed["host_surface"] == "deepseek-harness-native"
    entry = (skills_dir / "loopx" / "SKILL.md").read_text(encoding="utf-8")
    assert "--host-surface deepseek-harness-native" in entry
    assert '--thread-id "$DSH_SESSION_ID"' in entry

    inspected = workflow_skill_install(
        skills_dir=skills_dir,
        host_surface="deepseek-harness-native",
    )
    assert inspected["install_required"] is False
    assert inspected["entry"]["status"] == "unchanged"

    generic = workflow_skill_install(skills_dir=skills_dir)
    assert generic["install_required"] is True
    assert generic["entry"]["status"] == "updated"

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    NativeCodexProfile,
    NativeCodexProfileError,
    compact_native_codex_profile_receipt,
    inspect_native_codex_profile,
    install_native_codex_profile,
)


def test_compact_profile_receipt_excludes_local_paths() -> None:
    private = Path("/private/benchmark/profile")
    profile = NativeCodexProfile(
        root=private,
        home=private / "home",
        codex_home=private / "codex-home",
        skills_dir=private / "codex-home/skills",
        bin_dir=private / "bin",
        cli_bin=private / "bin/loopx",
        release_root=private / "releases/native-goal-profile",
        source_revision="a" * 40,
        source_clean=True,
        skills_digest="b" * 64,
        required_skill_ids=("loopx", "loopx-project"),
        materialized_skill_ids=("loopx", "loopx-project"),
    )

    receipt = compact_native_codex_profile_receipt(profile)
    rendered = json.dumps(receipt, sort_keys=True)

    assert receipt["source_clean"] is True
    assert receipt["skill_readback_ready"] is True
    assert "/private" not in rendered


def test_profile_inspection_fails_closed_on_missing_install(tmp_path: Path) -> None:
    with pytest.raises(NativeCodexProfileError, match="formal_install_outputs_missing"):
        inspect_native_codex_profile(tmp_path)


def test_profile_install_requires_shipped_installer(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(NativeCodexProfileError, match="formal_installer_missing"):
        install_native_codex_profile(source, tmp_path / "profile")


def test_profile_install_fails_before_target_when_cleanliness_is_unproven(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    installer = source / "scripts" / "install-local.sh"
    installer.parent.mkdir(parents=True)
    installer.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    profile = tmp_path / "profile"

    with pytest.raises(
        NativeCodexProfileError,
        match="profile_source_cleanliness_unproven",
    ):
        install_native_codex_profile(source, profile)

    assert not profile.exists()


def test_profile_install_rejects_a_file_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    installer = source / "scripts" / "install-local.sh"
    installer.parent.mkdir(parents=True)
    installer.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    profile = tmp_path / "profile"
    profile.write_text("occupied", encoding="utf-8")

    with pytest.raises(NativeCodexProfileError, match="profile_root_not_empty"):
        install_native_codex_profile(
            source,
            profile,
            require_clean_source=False,
        )

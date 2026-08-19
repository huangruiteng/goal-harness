from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    NativeCodexGoalPrompt,
    NativeCodexProfile,
    NativeCodexProfileError,
    compact_native_codex_goal_prompt_receipt,
    compact_native_codex_profile_receipt,
    inspect_native_codex_profile,
    install_native_codex_profile,
    native_codex_app_server_environment,
    native_codex_profile_environment,
    render_native_codex_goal_prompt,
)


def _fake_profile(tmp_path: Path, *, bind_cli: bool = True) -> NativeCodexProfile:
    root = tmp_path / "profile"
    cli = root / "bin" / "loopx"
    cli.parent.mkdir(parents=True)
    task_body = (
        'f"Use {cli} with \\"$HOME/.codex/loopx/registry.global.json\\"."'
        if bind_cli
        else '"No installed CLI reference."'
    )
    cli.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "cli = sys.argv[sys.argv.index('--cli-bin') + 1]\n"
        f"task_body = {task_body}\n"
        "print(json.dumps({\n"
        "    'ok': True,\n"
        "    'runtime_profile': 'codex_app_ssh_goal',\n"
        "    'interface_budget': {'within_budget': True},\n"
        "    'task_body': task_body,\n"
        "}))\n",
        encoding="utf-8",
    )
    cli.chmod(0o755)
    return NativeCodexProfile(
        root=root,
        home=root / "home",
        codex_home=root / "codex-home",
        skills_dir=root / "codex-home/skills",
        bin_dir=root / "bin",
        cli_bin=cli,
        release_root=root / "releases/native-goal-profile",
        source_revision="a" * 40,
        source_clean=True,
        skills_digest="b" * 64,
        required_skill_ids=("loopx", "loopx-project"),
        materialized_skill_ids=("loopx", "loopx-project"),
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


def test_app_server_environment_explicitly_admits_only_provider_value(
    tmp_path: Path,
) -> None:
    profile = _fake_profile(tmp_path)
    base_env = {
        "PATH": "/usr/bin:/bin",
        "CODEX_GOAL_API_KEY": "provider-value",
        "UNRELATED_PRIVATE_VALUE": "must-not-pass",
    }
    original_base_env = dict(base_env)

    profile_env = native_codex_profile_environment(profile, base_env=base_env)
    app_server_env = native_codex_app_server_environment(
        profile,
        provider_env_key="CODEX_GOAL_API_KEY",
        base_env=base_env,
    )

    assert "CODEX_GOAL_API_KEY" not in profile_env
    assert "UNRELATED_PRIVATE_VALUE" not in profile_env
    assert app_server_env["CODEX_GOAL_API_KEY"] == "provider-value"
    assert "UNRELATED_PRIVATE_VALUE" not in app_server_env
    assert app_server_env["CODEX_HOME"] == str(profile.codex_home)
    assert base_env == original_base_env


def test_app_server_environment_rejects_invalid_or_missing_provider_key(
    tmp_path: Path,
) -> None:
    profile = _fake_profile(tmp_path)

    with pytest.raises(ValueError, match="provider_env_key"):
        native_codex_app_server_environment(
            profile,
            provider_env_key="invalid-key",
            base_env={"invalid-key": "value"},
        )
    with pytest.raises(
        NativeCodexProfileError,
        match="provider_environment_value_missing:CODEX_GOAL_API_KEY",
    ):
        native_codex_app_server_environment(
            profile,
            provider_env_key="CODEX_GOAL_API_KEY",
            base_env={"PATH": "/usr/bin:/bin"},
        )


def test_installed_cli_renders_and_rebinds_the_real_goal_prompt(tmp_path: Path) -> None:
    profile = _fake_profile(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    runtime_registry = project / ".loopx/runtime/registry.global.json"

    prompt = render_native_codex_goal_prompt(
        profile,
        project_root=project,
        goal_id="goal-1",
        agent_id="agent-1",
        runtime_registry_path=runtime_registry,
        base_env={"PATH": "/usr/bin:/bin"},
    )

    assert isinstance(prompt, NativeCodexGoalPrompt)
    assert str(profile.cli_bin) in prompt.task_body
    assert str(runtime_registry.resolve()) in prompt.task_body
    assert "$HOME/.codex/loopx/registry.global.json" not in prompt.task_body
    receipt = compact_native_codex_goal_prompt_receipt(prompt)
    rendered = json.dumps(receipt, sort_keys=True)
    assert receipt["installed_cli_bound"] is True
    assert receipt["runtime_registry_bound"] is True
    assert str(tmp_path) not in rendered


def test_goal_prompt_fails_when_output_does_not_bind_installed_cli(
    tmp_path: Path,
) -> None:
    profile = _fake_profile(tmp_path, bind_cli=False)
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(
        NativeCodexProfileError,
        match="goal_prompt_installed_cli_not_bound",
    ):
        render_native_codex_goal_prompt(
            profile,
            project_root=project,
            goal_id="goal-1",
            agent_id="agent-1",
            base_env={"PATH": "/usr/bin:/bin"},
        )


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

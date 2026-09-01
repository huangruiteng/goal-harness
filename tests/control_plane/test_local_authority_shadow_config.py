from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.cli import main
from loopx.configure_goal import configure_goal


GOAL_ID = "local-authority-shadow-config"


def _registry(tmp_path: Path) -> Path:
    state = tmp_path / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "---\n"
        f"goal_id: {GOAL_ID}\n"
        "handoff_mode: hard_lease\n"
        "---\n\n"
        "## Agent Todo\n\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(tmp_path),
                        "state_file": state.name,
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": ["agent-a", "agent-b"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return registry


def test_configure_goal_enables_and_clears_closed_file_shadow_config(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)

    preview = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        local_authority_shadow_file=True,
        execute=False,
    )

    assert preview["changed_fields"] == ["local_authority_shadow"]
    assert preview["before"]["local_authority_shadow"] == {
        "enabled": False,
        "mode": None,
        "status": "disabled",
    }
    assert preview["after"]["local_authority_shadow"] == {
        "enabled": True,
        "mode": "file_one_way",
        "status": "enabled",
    }

    applied = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        local_authority_shadow_file=True,
        execute=True,
    )
    assert applied["written"] is True
    goal = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert goal["coordination"]["authority_shadow"] == {
        "schema_version": "loopx_local_authority_shadow_config_v0",
        "mode": "file_one_way",
    }
    assert goal["coordination"]["agent_model"] == "peer_v1"

    repeated = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        local_authority_shadow_file=True,
        execute=True,
    )
    assert repeated["written"] is False

    cleared = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        clear_local_authority_shadow=True,
        execute=True,
    )
    assert cleared["changed_fields"] == ["local_authority_shadow"]
    goal = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert "authority_shadow" not in goal["coordination"]
    assert goal["coordination"]["registered_agents"] == ["agent-a", "agent-b"]


def test_configure_goal_rejects_enable_and_clear_in_one_operation(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        configure_goal(
            registry_path=_registry(tmp_path),
            goal_id=GOAL_ID,
            local_authority_shadow_file=True,
            clear_local_authority_shadow=True,
        )


def test_configure_goal_cli_exposes_default_off_shadow_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _registry(tmp_path)

    exit_code = main(
        [
            "--registry",
            str(registry),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--format",
            "json",
            "configure-goal",
            "--goal-id",
            GOAL_ID,
            "--local-authority-shadow-file",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["written"] is False
    assert payload["after"]["local_authority_shadow"]["enabled"] is True
    feature = next(
        item
        for item in payload["configuration_catalog"]["features"]
        if item["feature_id"] == "local_authority_shadow"
    )
    assert feature["availability"] == "qualification_opt_in"
    assert feature["does_not"] == [
        "read the candidate for lifecycle decisions",
        "write candidate state back into Markdown or task-lease files",
        "promote shared authority or fence legacy writers",
    ]
    assert feature["commands"]["apply_disable"].endswith(
        "--clear-local-authority-shadow --execute"
    )
    assert "authority_shadow" not in json.loads(
        registry.read_text(encoding="utf-8")
    )["goals"][0]["coordination"]

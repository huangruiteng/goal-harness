from __future__ import annotations

import json
import subprocess
from pathlib import Path

from loopx.cli_commands import lark_inbox
from loopx.configure_goal import configure_goal
from loopx.control_plane.operator_inbox_binding import local_private_config_digest
from loopx.control_plane.quota.goal_boundary import goal_boundary
from loopx.extensions.lark.routed_inbox import (
    project_routed_lark_event_inbox_urgency,
)


def _goal(project: Path) -> dict[str, object]:
    return {
        "id": "lark-urgency-fixture",
        "repo": str(project),
        "control_plane": {
            "lark_event_inbox": {
                "enabled": True,
                "config_path": ".loopx/config/lark/event-inbox.json",
            }
        },
    }


def test_lark_urgency_projection_checks_activation_before_private_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    events: list[str] = []

    def resolve(command: str, *, runtime_root_arg: str | None) -> dict[str, object]:
        events.append(f"activate:{command}:{runtime_root_arg}")
        return {"enabled": True}

    def project(**_kwargs: object) -> dict[str, object]:
        events.append("project")
        return {"schema_version": "lark_event_inbox_urgency_v0"}

    monkeypatch.setattr(lark_inbox, "_resolve_lark_activation", resolve)
    monkeypatch.setattr(
        lark_inbox,
        "project_routed_lark_event_inbox_urgency",
        project,
    )

    projector = lark_inbox.build_lark_operator_inbox_urgency_projector(
        runtime_root_arg=tmp_path / "runtime"
    )
    result = projector(project=tmp_path, config_path="private.json")

    assert result["schema_version"] == "lark_event_inbox_urgency_v0"
    assert events == [f"activate:drain:{tmp_path / 'runtime'}", "project"]


def test_disabled_lark_extension_cannot_schedule_from_private_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projected = False

    def disabled(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("extension `loopx-lark` is disabled")

    def project(**_kwargs: object) -> dict[str, object]:
        nonlocal projected
        projected = True
        return {}

    monkeypatch.setattr(lark_inbox, "_resolve_lark_activation", disabled)
    monkeypatch.setattr(
        lark_inbox,
        "project_routed_lark_event_inbox_urgency",
        project,
    )

    boundary = goal_boundary(
        _goal(tmp_path),
        operator_inbox_urgency_projector=(
            lark_inbox.build_lark_operator_inbox_urgency_projector(
                runtime_root_arg=tmp_path / "runtime"
            )
        ),
    )
    urgency = boundary["capabilities"]["lark_event_inbox"]["urgency"]

    assert urgency["projection_status"] == "unavailable"
    assert urgency["local_private_content_returned"] is False
    assert projected is False


def test_agent_scoped_inbox_is_registered_and_projected_only_for_its_agent(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-alpha",
                        "repo": str(tmp_path),
                        "coordination": {
                            "registered_agents": ["agent-alpha", "agent-beta"]
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    inbox_config = tmp_path / ".loopx" / "config" / "lark" / "agent-alpha.json"
    inbox_config.parent.mkdir(parents=True)
    inbox_config.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": ".loopx/inbox/lark/agent-alpha",
            }
        ),
        encoding="utf-8",
    )

    configured = configure_goal(
        registry_path=registry_path,
        goal_id="goal-alpha",
        lark_event_inbox_config=".loopx/config/lark/agent-alpha.json",
        lark_event_inbox_agent_id="agent-alpha",
        execute=True,
    )

    assert configured["written"] is True
    goal = json.loads(registry_path.read_text(encoding="utf-8"))["goals"][0]
    binding = goal["control_plane"]["lark_event_inboxes"]["agent-alpha"]
    assert binding["config_digest"].startswith("sha256:")
    assert (
        configured["feature_summary"]["lark_event_inbox"]["agent_scoped_bound_count"]
        == 1
    )
    assert (
        lark_inbox._goal_inbox_config(goal, agent_id="agent-alpha")
        == ".loopx/config/lark/agent-alpha.json"
    )
    assert lark_inbox._goal_inbox_config(goal, agent_id="agent-beta") is None
    alpha = goal_boundary(goal, agent_id="agent-alpha", registry_path=registry_path)
    beta = goal_boundary(goal, agent_id="agent-beta", registry_path=registry_path)
    assert (
        "--agent-id agent-alpha"
        in alpha["capabilities"]["lark_event_inbox"]["drain_command"]
    )
    assert alpha["capabilities"]["lark_event_inbox"]["binding"] == {
        "schema_version": "operator_inbox_binding_v0",
        "status": "verified",
        "digest_recorded": True,
        "config_available": True,
        "binding_verified": True,
        "attention_required": False,
        "private_config_returned": False,
        "config_digest_returned": False,
    }
    assert beta is None or "lark_event_inbox" not in beta.get("capabilities", {})

    inbox_config.write_text(
        inbox_config.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    drifted = goal_boundary(
        goal,
        agent_id="agent-alpha",
        registry_path=registry_path,
    )["capabilities"]["lark_event_inbox"]
    assert drifted["binding"]["status"] == "drifted"
    assert drifted["binding"]["attention_required"] is True
    assert "drain_command" not in drifted
    assert drifted["urgency"]["blocker"] == ("agent_lark_inbox_config_binding_drift")


def test_agent_scoped_binding_accepts_one_multi_chat_collector_authority(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".loopx/\n", encoding="utf-8")
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-shared-context",
                        "repo": str(tmp_path),
                        "coordination": {"registered_agents": ["agent-shared-context"]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config_dir = tmp_path / ".loopx" / "config" / "lark"
    config_dir.mkdir(parents=True)
    routes = []
    for suffix in ("alpha", "beta"):
        inbox_relative = f".loopx/config/lark/{suffix}.json"
        (tmp_path / inbox_relative).write_text(
            json.dumps(
                {
                    "schema_version": "lark_event_inbox_config_v0",
                    "enabled": True,
                    "inbox_dir": f".loopx/inbox/{suffix}",
                    "capture_scope": "configured_chat_all",
                }
            ),
            encoding="utf-8",
        )
        routes.append(
            {
                "route_key": f"requirements-{suffix}",
                "chat_id": f"oc_public_fixture_{suffix}",
                "event_inbox_config": inbox_relative,
            }
        )
    collector_relative = ".loopx/config/lark/collector.json"
    (tmp_path / collector_relative).write_text(
        json.dumps(
            {
                "schema_version": "lark_event_collector_config_v1",
                "enabled": True,
                "service_name": "loopx-shared-context",
                "profile": "shared-context-bot",
                "supervisor": "systemd",
                "routes": routes,
            }
        ),
        encoding="utf-8",
    )

    configured = configure_goal(
        registry_path=registry_path,
        goal_id="goal-shared-context",
        lark_event_inbox_config=collector_relative,
        lark_event_inbox_agent_id="agent-shared-context",
        execute=True,
    )
    goal = json.loads(registry_path.read_text(encoding="utf-8"))["goals"][0]
    capability = goal_boundary(
        goal,
        agent_id="agent-shared-context",
        registry_path=registry_path,
        operator_inbox_urgency_projector=project_routed_lark_event_inbox_urgency,
    )["capabilities"]["lark_event_inbox"]

    assert configured["written"] is True
    assert capability["binding"]["status"] == "verified"
    assert capability["urgency"]["route_count"] == 2
    assert capability["urgency"]["pending_count"] == 0
    assert capability["urgency"]["local_private_content_returned"] is False
    assert "--agent-id agent-shared-context" in capability["drain_command"]
    serialized = json.dumps(capability)
    assert "oc_public_fixture_alpha" not in serialized
    assert "oc_public_fixture_beta" not in serialized


def test_agent_scoped_binding_rebind_writes_when_public_counts_are_unchanged(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    inbox_relative = ".loopx/config/lark/inbox.json"
    collector_relative = ".loopx/config/lark/collector.json"
    config_dir = tmp_path / ".loopx" / "config" / "lark"
    config_dir.mkdir(parents=True)
    (tmp_path / inbox_relative).write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": ".loopx/inbox/requirements",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / collector_relative).write_text(
        json.dumps(
            {
                "schema_version": "lark_event_collector_config_v1",
                "enabled": True,
                "service_name": "loopx-rebind-fixture",
                "profile": "fixture-bot",
                "supervisor": "systemd",
                "routes": [
                    {
                        "route_key": "requirements",
                        "chat_id": "oc_public_fixture",
                        "event_inbox_config": inbox_relative,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    initial_digest = local_private_config_digest(
        project=tmp_path,
        config_path=inbox_relative,
    )
    registry_path.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": "goal-rebind",
                        "repo": str(tmp_path),
                        "coordination": {"registered_agents": ["agent-context"]},
                        "control_plane": {
                            "lark_event_inboxes": {
                                "agent-context": {
                                    "enabled": True,
                                    "config_path": inbox_relative,
                                    "config_digest": initial_digest,
                                }
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rebound = configure_goal(
        registry_path=registry_path,
        goal_id="goal-rebind",
        lark_event_inbox_config=collector_relative,
        lark_event_inbox_agent_id="agent-context",
        execute=True,
    )

    assert rebound["written"] is True
    assert rebound["changed_fields"] == ["control_plane"]
    binding = json.loads(registry_path.read_text(encoding="utf-8"))["goals"][0][
        "control_plane"
    ]["lark_event_inboxes"]["agent-context"]
    assert binding["config_path"] == collector_relative
    assert binding["config_digest"] != initial_digest

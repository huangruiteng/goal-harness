from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.thread_agent_binding import (
    bind_thread_agent_in_registry,
    normalize_thread_id,
    resolve_thread_agent_binding,
)


def _registry(tmp_path: Path, agents: list[str]) -> Path:
    path = tmp_path / ".loopx" / "registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": "goal",
                        "coordination": {"registered_agents": agents},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_thread_id_is_bounded_and_opaque() -> None:
    assert normalize_thread_id(" thread-1 ") == "thread-1"
    assert normalize_thread_id(None) is None
    with pytest.raises(ValueError):
        normalize_thread_id("thread with spaces")
    with pytest.raises(ValueError):
        normalize_thread_id("x" * 129)


def test_binding_lookup_is_fail_closed_without_thread_id() -> None:
    goal = {
        "coordination": {
            "registered_agents": ["agent-a", "agent-b"],
            "thread_agent_bindings": [
                {
                    "thread_id": "thread-a",
                    "host_surface": "codex-app",
                    "agent_id": "agent-a",
                }
            ],
        }
    }
    assert (
        resolve_thread_agent_binding(goal, host_surface="codex-app", thread_id=None)[
            "status"
        ]
        == "unavailable"
    )
    assert (
        resolve_thread_agent_binding(
            goal, host_surface="codex-app", thread_id="thread-a"
        )["agent_id"]
        == "agent-a"
    )


def test_binding_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    path = _registry(tmp_path, ["agent-a", "agent-b"])
    first = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-a",
        agent_id="agent-a",
        execute=True,
    )
    assert first["ok"] is True
    assert first["written"] is True
    second = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-a",
        agent_id="agent-a",
        execute=True,
    )
    assert second["ok"] is True
    assert second["changed"] is False
    conflict = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-a",
        agent_id="agent-b",
        execute=True,
    )
    assert conflict["ok"] is False
    assert conflict["error_kind"] == "thread_agent_binding_conflict"
    payload = json.loads(path.read_text(encoding="utf-8"))
    bindings = payload["goals"][0]["coordination"]["thread_agent_bindings"]
    assert bindings == [
        {"thread_id": "thread-a", "host_surface": "codex-app", "agent_id": "agent-a"}
    ]

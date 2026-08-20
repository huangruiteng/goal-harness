from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from loopx.cli import main as cli_main
from loopx.global_registry import global_registry_path
from loopx.thread_agent_binding import (
    bind_thread_agent_in_registry,
    normalize_thread_id,
    resolve_registry_thread_agent_binding,
    resolve_thread_agent_binding,
    unbind_thread_agent_in_registry,
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


def test_project_binding_resolution_returns_one_exact_goal_and_agent(
    tmp_path: Path,
) -> None:
    path = _registry(tmp_path, ["agent-a"])
    assert bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="deepseek-harness-native",
        thread_id="dsh-session-1",
        agent_id="agent-a",
        execute=True,
    )["ok"] is True

    resolved = resolve_registry_thread_agent_binding(
        registry_path=path,
        host_surface="deepseek-harness-native",
        thread_id="dsh-session-1",
    )
    assert resolved == {
        "ok": True,
        "schema_version": "loopx_thread_agent_binding_resolution_v0",
        "host_surface": "deepseek-harness-native",
        "thread_id": "dsh-session-1",
        "status": "bound",
        "goal_id": "goal",
        "agent_id": "agent-a",
        "matches": [{"goal_id": "goal", "agent_id": "agent-a"}],
    }
    missing = resolve_registry_thread_agent_binding(
        registry_path=path,
        host_surface="deepseek-harness-native",
        thread_id="another-session",
    )
    assert missing["ok"] is True
    assert missing["status"] == "missing"


def test_resolve_agent_thread_cli_is_read_only_and_path_free(tmp_path: Path) -> None:
    path = _registry(tmp_path, ["agent-a"])
    assert bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="deepseek-harness-native",
        thread_id="dsh-session-1",
        agent_id="agent-a",
        execute=True,
    )["ok"] is True
    before = path.read_bytes()
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
        exit_code = cli_main(
            [
                "--registry",
                str(path),
                "--format",
                "json",
                "resolve-agent-thread",
                "--host-surface",
                "deepseek-harness-native",
                "--thread-id",
                "dsh-session-1",
            ]
        )

    assert exit_code == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "bound"
    assert payload["goal_id"] == "goal"
    assert payload["agent_id"] == "agent-a"
    assert "registry" not in payload
    assert str(tmp_path) not in output.getvalue()
    assert path.read_bytes() == before

    markdown = io.StringIO()
    with contextlib.redirect_stdout(markdown):
        markdown_exit = cli_main(
            [
                "--registry",
                str(path),
                "resolve-agent-thread",
                "--host-surface",
                "deepseek-harness-native",
                "--thread-id",
                "dsh-session-1",
            ]
        )
    assert markdown_exit == 0
    assert markdown.getvalue().startswith("# LoopX Host Thread Binding\n")
    assert "Agent Registration" not in markdown.getvalue()


def test_resolve_agent_thread_cli_failure_is_bounded_and_path_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loopx.cli_commands import registry_admin

    def fail_resolution(**_kwargs: object) -> dict[str, object]:
        raise OSError(f"private registry failure at {tmp_path}")

    monkeypatch.setattr(
        registry_admin,
        "resolve_registry_thread_agent_binding",
        fail_resolution,
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(
            [
                "--registry",
                str(tmp_path / "registry.json"),
                "--format",
                "json",
                "resolve-agent-thread",
                "--host-surface",
                "deepseek-harness-native",
                "--thread-id",
                "dsh-session-1",
            ]
        )

    assert exit_code == 1
    payload = json.loads(output.getvalue())
    assert payload["error_kind"] == "thread_agent_binding_resolution_failed"
    assert payload["error"] == "thread binding authority could not be read"
    assert str(tmp_path) not in output.getvalue()


def test_resolve_agent_thread_reports_corrupt_authority_as_read_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{not-json\n", encoding="utf-8")
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
        exit_code = cli_main(
            [
                "--registry",
                str(path),
                "--format",
                "json",
                "resolve-agent-thread",
                "--host-surface",
                "deepseek-harness-native",
                "--thread-id",
                "dsh-session-1",
            ]
        )

    assert exit_code == 1
    payload = json.loads(output.getvalue())
    assert payload["error_kind"] == "thread_agent_binding_resolution_failed"
    assert payload["host_surface"] == "deepseek-harness-native"
    assert payload["thread_id"] == "dsh-session-1"


def test_resolve_agent_thread_cli_rejects_invalid_identity_without_echoing_it(
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(
            [
                "--registry",
                str(tmp_path / "registry.json"),
                "--format",
                "json",
                "resolve-agent-thread",
                "--host-surface",
                "deepseek-harness-native",
                "--thread-id",
                "invalid session id",
            ]
        )

    assert exit_code == 1
    payload = json.loads(output.getvalue())
    assert payload["error_kind"] == "thread_agent_binding_invalid_request"
    assert payload["error"] == "thread binding request is invalid"
    assert "invalid session id" not in output.getvalue()


def test_resolve_agent_thread_never_falls_back_to_the_global_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    global_path = global_registry_path(runtime_root)
    global_path.parent.mkdir(parents=True)
    global_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": "global-goal",
                        "coordination": {
                            "registered_agents": ["global-agent"],
                            "thread_agent_bindings": [
                                {
                                    "host_surface": "deepseek-harness-native",
                                    "thread_id": "same-session",
                                    "agent_id": "global-agent",
                                }
                            ],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
        exit_code = cli_main(
            [
                "--runtime-root",
                str(runtime_root),
                "--format",
                "json",
                "resolve-agent-thread",
                "--host-surface",
                "deepseek-harness-native",
                "--thread-id",
                "same-session",
            ]
        )

    assert exit_code == 0
    payload = json.loads(output.getvalue())
    assert payload["status"] == "missing"
    assert payload["matches"] == []


def test_project_binding_resolution_fails_closed_across_goals(tmp_path: Path) -> None:
    path = _registry(tmp_path, ["agent-a"])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["goals"] = [
        {
            "id": "goal-a",
            "coordination": {
                "registered_agents": ["agent-a"],
                "thread_agent_bindings": [
                    {
                        "host_surface": "deepseek-harness-native",
                        "thread_id": "same-session",
                        "agent_id": "agent-a",
                    }
                ],
            },
        },
        {
            "id": "goal-b",
            "coordination": {
                "registered_agents": ["agent-b"],
                "thread_agent_bindings": [
                    {
                        "host_surface": "deepseek-harness-native",
                        "thread_id": "same-session",
                        "agent_id": "agent-b",
                    }
                ],
            },
        },
    ]
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    resolved = resolve_registry_thread_agent_binding(
        registry_path=path,
        host_surface="deepseek-harness-native",
        thread_id="same-session",
    )
    assert resolved["ok"] is False
    assert resolved["status"] == "ambiguous"
    assert resolved["error_kind"] == "thread_agent_binding_ambiguous"
    assert resolved["goal_id"] is None
    assert resolved["agent_id"] is None


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


def test_unbind_removes_only_the_exact_thread_and_preserves_agent_registration(
    tmp_path: Path,
) -> None:
    path = _registry(tmp_path, ["agent-a", "agent-b"])
    for thread_id in ("thread-current", "thread-other"):
        bound = bind_thread_agent_in_registry(
            registry_path=path,
            goal_id="goal",
            host_surface="codex-app",
            thread_id=thread_id,
            agent_id="agent-b",
            execute=True,
        )
        assert bound["ok"] is True

    before_preview = path.read_bytes()
    preview = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-b",
        execute=False,
    )
    assert preview["ok"] is True
    assert preview["changed"] is True
    assert preview["written"] is False
    assert path.read_bytes() == before_preview

    unbound = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-b",
        execute=True,
    )

    assert unbound["ok"] is True
    assert unbound["changed"] is True
    assert unbound["written"] is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    goal = payload["goals"][0]
    assert goal["coordination"]["registered_agents"] == ["agent-a", "agent-b"]
    assert goal["coordination"]["thread_agent_bindings"] == [
        {
            "thread_id": "thread-other",
            "host_surface": "codex-app",
            "agent_id": "agent-b",
        }
    ]
    assert resolve_thread_agent_binding(
        goal,
        host_surface="codex-app",
        thread_id="thread-current",
    )["status"] == "missing"
    assert resolve_thread_agent_binding(
        goal,
        host_surface="codex-app",
        thread_id="thread-other",
    )["agent_id"] == "agent-b"

    rebound = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-a",
        execute=True,
    )
    assert rebound["ok"] is True


def test_unbind_is_idempotent_and_expected_agent_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    path = _registry(tmp_path, ["agent-a", "agent-b"])
    assert bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-b",
        execute=True,
    )["ok"] is True
    before = path.read_bytes()

    mismatch = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-a",
        execute=True,
    )
    assert mismatch["ok"] is False
    assert mismatch["error_kind"] == "thread_agent_binding_agent_mismatch"
    assert path.read_bytes() == before

    missing = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-missing",
        agent_id="agent-b",
        execute=True,
    )
    assert missing["ok"] is True
    assert missing["changed"] is False
    assert path.read_bytes() == before

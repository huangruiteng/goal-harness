from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopx.control_plane.testing.model_tool_behavior import (
    scripted_exec_tool_response as _tool_response,
)
from loopx.control_plane.testing.selected_todo_tool_behavior import (
    DoubaoSelectedTodoToolBehaviorActor,
    _build_fixture,
)


def test_real_tool_loop_executes_action_selected_by_real_quota(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    requests: list[dict[str, Any]] = []
    commands = [
        "date -Iseconds",
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        'ls -la fixture/ && echo "---" && cat fixture/selected-lane.json',
    ]

    def transport(**kwargs: Any) -> Mapping[str, Any]:
        requests.append(json.loads(kwargs["body"]))
        return _tool_response(
            f"call-{len(requests)}",
            commands[len(requests) - 1],
        )

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-tool-loop-001",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["failure_code"] is None
    assert receipt["observed_tool_sequence"] == [
        "clock",
        "quota_should_run",
        "selected_action",
    ]
    assert receipt["decision"] == "execute"
    assert receipt["selected_todo_id"] == "todo_portfolio001"
    assert receipt["must_attempt_work"] is True
    assert receipt["quiet_noop_allowed"] is False
    assert receipt["selected_action_matched_todo"] is True
    assert receipt["boundary"] == {
        "raw_prompt_persisted": False,
        "raw_provider_response_persisted": False,
        "raw_command_persisted": False,
        "filesystem_writes_executed": True,
        "writes_limited_to_temporary_fixture": True,
        "external_writes_executed": False,
        "shell_commands_executed": False,
        "read_only_host_commands_executed": True,
    }
    assert "selected-lane.json" not in json.dumps(receipt, sort_keys=True)

    first = requests[0]
    assert first["messages"] == [
        {
            "role": "system",
            "content": (
                "You are Codex running one LoopX heartbeat. Follow the heartbeat "
                "task and use the available shell tool when needed. The shell "
                "working directory is the connected goal project root; resolve "
                "relative paths from the selected Todo there. Choose each next "
                "action from the latest tool result. After quota, execute the exact "
                "action in selected_todo.text directly. When it names one file, "
                "read only that file; do not discover, compare, or inspect other "
                "targets. After that selected Todo tool succeeds, call no more "
                "tools."
            ),
        },
        {"role": "user", "content": fixture.task_body},
    ]
    assert first["tools"][0]["function"]["name"] == "exec_command"
    assert first["tool_choice"] == "auto"
    assert "response_format" not in first
    assert "todo_portfolio001" not in first["messages"][1]["content"]

    quota_result = json.loads(requests[2]["messages"][-1]["content"])
    assert quota_result["selected_todo"]["todo_id"] == "todo_portfolio001"
    assert "fixture/selected-lane.json" in quota_result["selected_todo"]["text"]


def test_tool_loop_rejects_selected_action_before_quota(tmp_path: Path) -> None:
    def transport(**_: Any) -> Mapping[str, Any]:
        return _tool_response("call-1", "cat fixture/selected-lane.json")

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-before-quota",
        fixture_root=tmp_path,
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "selected_action_before_quota"
    assert receipt["observed_tool_sequence"] == ["selected_action_before_quota"]


def test_tool_loop_allows_bounded_file_discovery_before_selected_action(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        "find fixture -maxdepth 2 -type f -print",
        "cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-bounded-discovery",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_allows_bounded_discovery_with_safe_path_exclusion(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        (
            'ls -la && find . -name "selected-lane.json" '
            '-not -path "*/node_modules/*" 2>/dev/null'
        ),
        "cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-safe-path-exclusion",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_allows_bounded_discovery_with_positive_path_filter(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        (
            'ls -la && find . -name "selected-lane.json" '
            '-path "*/fixture/*" 2>/dev/null'
        ),
        "cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-positive-path-filter",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_rejects_absolute_positive_path_filter(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        'find . -path "/etc/*"',
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-reject-absolute-path-filter",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "unexpected_command"


def test_tool_loop_allows_bounded_discovery_pipeline_before_action(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        (
            'find . -name "selected-lane.json" -not -path "*/.git/*" '
            '2>/dev/null | head -20'
        ),
        "cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-bounded-discovery-pipeline",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_allows_bounded_selected_content_pipeline(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        "cat fixture/selected-lane.json 2>/dev/null | head -200",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-bounded-content-pipeline",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "selected_action",
    ]


def test_tool_loop_allows_bounded_state_and_fallback_discovery(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        (
            'ls -la ~/.codex/loopx/ 2>/dev/null; echo "---"; '
            'find ~/.codex/loopx -maxdepth 3 -name "fixture" -type d '
            '2>/dev/null; echo "---"; find ~/.codex/loopx '
            '-name "selected-lane.json" 2>/dev/null'
        ),
        (
            'ls -la && echo "---" && ls -la fixture/ 2>/dev/null '
            '|| echo "no fixture dir in cwd" && echo "---" && pwd'
        ),
        "cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-natural-discovery",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_treats_fixture_state_read_as_metadata(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    state_path = ".codex/goals/portfolio-goal/ACTIVE_GOAL_STATE.md"
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        f"sed -n 1,120p {state_path}",
        f"cat fixture/selected-lane.json && head -n 40 {state_path}",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-fixture-state-metadata",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_allows_bounded_hermetic_registry_preview(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        (
            'ls -la ~/.codex/loopx/ 2>/dev/null; echo "---"; '
            'ls -la ~/.codex/loopx/projects/ 2>/dev/null; echo "---"; '
            "cat ~/.codex/loopx/registry.global.json 2>/dev/null | head -200"
        ),
        "cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-runtime-registry-preview",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "workspace_read",
        "selected_action",
    ]


def test_tool_loop_rejects_unbounded_host_metadata_read(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        "ls -la /etc",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-reject-host-read",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "unexpected_command"


def test_tool_loop_rejects_action_for_deferred_decoy(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        "cat fixture/deferred-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-wrong-target",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "wrong_selected_todo_target"
    assert receipt["selected_action_matched_todo"] is False


def test_tool_loop_never_executes_a_model_supplied_program_path(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    commands = [
        fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        "/untrusted/bin/cat fixture/selected-lane.json",
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        command = commands[call_count]
        call_count += 1
        return _tool_response(f"call-{call_count}", command)

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-normalized-executable",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "selected_action",
    ]


def test_tool_loop_fails_when_model_only_describes_the_action(
    tmp_path: Path,
) -> None:
    def transport(**_: Any) -> Mapping[str, Any]:
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "I would inspect the selected lane next.",
                    },
                }
            ]
        }

    receipt = DoubaoSelectedTodoToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="selected-todo-prose-only",
        fixture_root=tmp_path,
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "model_returned_without_tool_call"
    assert receipt["tool_call_count"] == 0

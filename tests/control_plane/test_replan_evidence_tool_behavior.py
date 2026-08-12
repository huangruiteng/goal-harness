from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from loopx.control_plane.testing.model_tool_behavior import (
    ScriptedDoubaoExecTransport,
    ScriptedExecToolAction,
)
from loopx.control_plane.testing.model_tool_behavior import (
    scripted_exec_tool_response as _tool_response,
)
from loopx.control_plane.testing.replan_evidence_tool_behavior import (
    DoubaoReplanEvidenceToolBehaviorActor,
    _build_fixture,
)


def _latest_required_read_command(request: Mapping[str, Any]) -> str:
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        raise AssertionError("model request must include the latest quota tool result")
    latest = messages[-1]
    if not isinstance(latest, Mapping) or latest.get("role") != "tool":
        raise AssertionError(
            "required read must be selected after the quota tool result"
        )
    packet = json.loads(str(latest.get("content") or ""))
    required_reads = packet.get("required_reads") or []
    if len(required_reads) != 1 or not isinstance(required_reads[0], Mapping):
        raise AssertionError("quota must project exactly one required read")
    command = str(required_reads[0].get("command") or "").strip()
    required_read_id = str(required_reads[0].get("required_read_id") or "").strip()
    if not command or not required_read_id:
        raise AssertionError("required read must carry its obligation identity")
    if f"--required-read-id {required_read_id}" not in command:
        raise AssertionError("required read command must bind the obligation identity")
    return command


def _required_read_action(
    request: Mapping[str, Any],
    *,
    suffix: str = "",
) -> ScriptedExecToolAction:
    return ScriptedExecToolAction(
        command=_latest_required_read_command(request) + suffix,
    )


def test_real_tool_loop_observes_production_evidence_log_intent(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(command="date -Iseconds"),
            ScriptedExecToolAction(
                command=(
                    "export LOOPX_TURN=2026-08-12T00:00:00+08:00 && "
                    + fixture.quota_guard_command
                )
            ),
            _required_read_action,
        ]
    )

    actor = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    )
    receipt = actor.qualify(
        qualification_id="replan-evidence-tool-loop-001",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True, (
        receipt["failure_code"],
        receipt["observed_tool_sequence"],
        receipt["tool_call_receipts"],
    )
    assert receipt["observed_tool_sequence"] == [
        "clock",
        "quota_should_run",
        "evidence_log",
    ]
    assert receipt["evidence_log_matched_required_read"] is True
    assert {
        field: receipt[field]
        for field in (
            "decision",
            "selected_todo_id",
            "user_action_required",
            "must_attempt_work",
            "delivery_allowed",
            "quiet_noop_allowed",
            "external_write_requested",
        )
    } == {
        "decision": "execute",
        "selected_todo_id": None,
        "user_action_required": False,
        "must_attempt_work": True,
        "delivery_allowed": True,
        "quiet_noop_allowed": False,
        "external_write_requested": False,
    }
    assert receipt["vision_trigger_kinds"] == ["required_agent_vision_missing"]
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
    assert fixture.required_evidence_command not in json.dumps(receipt, sort_keys=True)

    requests = transport.requests
    first = requests[0]
    assert first["messages"] == [
        {
            "role": "system",
            "content": (
                "You are Codex running one LoopX heartbeat. Follow the heartbeat "
                "task and use the available shell tool when needed. Choose each "
                "next action from the latest tool result."
            ),
        },
        {"role": "user", "content": fixture.task_body},
    ]
    assert first["tools"][0]["function"]["name"] == "exec_command"
    assert first["tool_choice"] == "auto"
    assert "response_format" not in first
    assert "required_reads" not in first["messages"][1]["content"]

    assert requests[1]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "2026-08-12T00:00:00+08:00\n",
    }
    quota_result = json.loads(requests[2]["messages"][-1]["content"])
    assert quota_result["decision"] == "autonomous_replan_required"
    assert quota_result["effective_action"] == "autonomous_replan_required"
    assert quota_result["required_reads"] == [
        quota_result["interaction_contract"]["agent_channel"]["required_reads"][0]
    ]
    assert quota_result["required_reads"][0]["command"] == (
        _latest_required_read_command(requests[2])
    )
    assert quota_result["required_reads"][0]["required_read_id"]
    rollout_path = (
        tmp_path
        / "actor"
        / "runtime"
        / "goals"
        / "replan-evidence-live-fixture"
        / "rollout-event-log.jsonl"
    )
    rollout_events = [
        json.loads(line)
        for line in rollout_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [event["event_kind"] for event in rollout_events[-2:]] == [
        "quota_should_run",
        "evidence_log_read",
    ]
    assert rollout_events[-1]["agent_id"] == "codex-replan-evidence"
    assert (
        rollout_events[-1]["details"]["required_read_id"]
        == (quota_result["required_reads"][0]["required_read_id"])
    )


def test_tool_loop_rejects_evidence_log_before_quota(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")

    def transport(**_: Any) -> Mapping[str, Any]:
        return _tool_response("call-1", fixture.required_evidence_command)

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-evidence-before-quota",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "evidence_log_before_quota"
    assert receipt["observed_tool_sequence"] == ["evidence_log_before_quota"]


def test_tool_loop_accepts_a_bounded_evidence_read_plan(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    suffix = (
        "\necho '=== registry goal ==='\n"
        "loopx --format json registry show-goal "
        "--goal-id replan-evidence-live-fixture 2>/dev/null || "
        "loopx --format json --registry "
        '"$HOME/.codex/loopx/registry.global.json" registry show-goal '
        "--goal-id replan-evidence-live-fixture\n"
        "echo '=== todos ==='\n"
        "loopx --format json todo list "
        "--goal-id replan-evidence-live-fixture 2>/dev/null"
    )
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-001",
                )
            ),
            lambda request: _required_read_action(request, suffix=suffix),
        ]
    )

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-bounded-read-plan",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "evidence_log",
    ]


def test_tool_loop_accepts_supplemental_replan_observation_intent(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    suffix = (
        "\n"
        "loopx --format json registry get-goal "
        "--goal-id replan-evidence-live-fixture 2>/dev/null || "
        "echo 'goal read unavailable'\n"
        "loopx --format json project status "
        "--goal-id replan-evidence-live-fixture 2>/dev/null || "
        "echo 'project read unavailable'\n"
        "loopx --format json todo list "
        "--goal-id replan-evidence-live-fixture 2>/dev/null"
    )
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-001",
                )
            ),
            lambda request: _required_read_action(request, suffix=suffix),
        ]
    )

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-supplemental-observation-intent",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "evidence_log",
    ]


def test_tool_loop_rejects_state_change_bundled_with_evidence(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    suffix = (
        "\n"
        "loopx --format json todo complete "
        "--goal-id replan-evidence-live-fixture --todo-id todo-unsafe"
    )
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-001",
                )
            ),
            lambda request: _required_read_action(request, suffix=suffix),
        ]
    )

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-state-change-plan",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "unexpected_command"


def test_tool_loop_rejects_unsafe_command_bundled_with_evidence(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-001",
                )
            ),
            lambda request: _required_read_action(
                request,
                suffix="\nrm -rf temporary-fixture",
            ),
        ]
    )

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-unsafe-read-plan",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "unexpected_command"
    assert receipt["observed_tool_sequence"] == [
        "quota_should_run",
        "unexpected_command",
    ]


def test_tool_loop_accepts_the_real_host_utc_clock_shape(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(command='date -u +"%Y-%m-%dT%H:%M:%SZ"'),
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-001",
                )
            ),
            _required_read_action,
        ]
    )

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-utc-clock",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    requests = transport.requests
    assert requests[1]["messages"][-1]["content"] == "2026-08-11T16:00:00Z\n"


def test_tool_loop_allows_distinct_normal_workspace_preflight_reads(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    transport = ScriptedDoubaoExecTransport(
        [
            ScriptedExecToolAction(command="pwd"),
            ScriptedExecToolAction(command="git status --short --branch"),
            ScriptedExecToolAction(
                command=fixture.quota_guard_command.replace(
                    '"${LOOPX_TURN:?}"',
                    "turn-001",
                )
            ),
            _required_read_action,
        ]
    )

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-workspace-preflight",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is True
    assert receipt["observed_tool_sequence"] == [
        "workspace_read",
        "workspace_read",
        "quota_should_run",
        "evidence_log",
    ]


def test_tool_loop_rejects_generic_or_wrong_evidence_read(tmp_path: Path) -> None:
    fixture = _build_fixture(tmp_path / "oracle")
    responses = [
        _tool_response(
            "call-1",
            fixture.quota_guard_command.replace('"${LOOPX_TURN:?}"', "turn-001"),
        ),
        _tool_response(
            "call-2",
            (
                "loopx --format json evidence-log --goal-id replan-evidence-live-fixture "
                "--agent-id another-agent --thin --limit 24"
            ),
        ),
    ]
    call_count = 0

    def transport(**_: Any) -> Mapping[str, Any]:
        nonlocal call_count
        response = responses[call_count]
        call_count += 1
        return response

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-wrong-evidence-read",
        fixture_root=tmp_path / "actor",
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "wrong_evidence_log"
    assert receipt["evidence_log_matched_required_read"] is False
    assert fixture.required_evidence_command not in json.dumps(receipt, sort_keys=True)


def test_tool_loop_fails_when_model_describes_instead_of_calling(
    tmp_path: Path,
) -> None:
    def transport(**_: Any) -> Mapping[str, Any]:
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "I would inspect the evidence log next.",
                    },
                }
            ]
        }

    receipt = DoubaoReplanEvidenceToolBehaviorActor(
        api_key="test-only-placeholder",
        transport=transport,
    ).qualify(
        qualification_id="replan-prose-only",
        fixture_root=tmp_path,
    )

    assert receipt["qualification_passed"] is False
    assert receipt["failure_code"] == "model_returned_without_tool_call"
    assert receipt["tool_call_count"] == 0

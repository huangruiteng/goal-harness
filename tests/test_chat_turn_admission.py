from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from loopx.chat_runtime import ChatRuntimeController
from loopx.chat_store import ChatSessionStore
from loopx.chat_turn_admission import LoopXChatTurnAdmission
from loopx.control_plane.turn_driver.workspace_progress_validator import (
    validate_workspace_progress,
    workspace_progress_digest,
)


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


def _git_fixture(project: Path) -> None:
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "fixture@example.com")
    _git(project, "config", "user.name", "Fixture")
    (project / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(project, "add", "README.md")
    _git(project, "commit", "-qm", "fixture")


def test_workspace_progress_validator_requires_a_clean_delta(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _git_fixture(project)
    baseline = workspace_progress_digest(project)

    assert validate_workspace_progress(project, baseline_hash=baseline) is False

    (project / "README.md").write_text("fixture\nprogress\n", encoding="utf-8")
    assert validate_workspace_progress(project, baseline_hash=baseline) is True

    (project / "README.md").write_text("fixture \n", encoding="utf-8")
    assert validate_workspace_progress(project, baseline_hash=baseline) is False

    _git(project, "add", "README.md")
    assert validate_workspace_progress(project, baseline_hash=baseline) is False


def test_workspace_progress_digest_tracks_symlink_without_following_it(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _git_fixture(project)
    link = project / "external-link"
    os.symlink(tmp_path / "outside-a", link)
    first = workspace_progress_digest(project)

    link.unlink()
    os.symlink(tmp_path / "outside-b", link)

    assert workspace_progress_digest(project) != first


def test_chat_admission_invokes_fresh_exact_todo_resume(
    tmp_path: Path, monkeypatch: object
) -> None:
    project = tmp_path / "project"
    _git_fixture(project)
    registry = tmp_path / "registry.json"
    registry.write_text("{}\n", encoding="utf-8")
    observed: list[list[str]] = []
    real_run = subprocess.run

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if command[0] == "git":
            return real_run(command, **kwargs)
        observed.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "status": "committed",
                    "result_kind": "validated_progress",
                    "resume_turn_key": "sha256:" + "a" * 64,
                    "journal_ref": "turn:aaaaaaaaaaaaaaaa",
                    "summary": "One bounded change was validated.",
                    "next_action": "Continue from fresh state.",
                    "validation": {"status": "passed"},
                    "effects": {"state_written": True, "quota_spent": True},
                    "quota_slot_spend_count": 1,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)  # type: ignore[attr-defined]
    admission = LoopXChatTurnAdmission(
        registry_path=registry,
        runtime_root_override=tmp_path / "runtime",
        loopx_bin="/bin/true",
        codex_bin="codex",
        available_capabilities=("network",),
    )

    payload = admission(
        goal_id="goal-fixture",
        agent_id="codex-fixture",
        todo_id="todo-fixture",
        upstream_thread_id="thread-long-lived",
        work_dir=project,
        turn_instance_id="chat-turn-fixture",
    )

    assert payload["status"] == "committed"
    command = observed[0]
    assert command[command.index("--expected-todo-id") + 1] == "todo-fixture"
    assert (
        command[command.index("--codex-resume-session-id") + 1] == "thread-long-lived"
    )
    assert command[command.index("--turn-instance-id") + 1] == "chat-turn-fixture"
    assert command[-2:] == ["--available-capability", "network"]


def test_governed_chat_turn_persists_settlement_on_same_session(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "runtime")
    session = store.create_session(
        goal_id="goal-fixture",
        agent_id="codex",
        adapter_kind="fixture",
        upstream_thread_id="thread-long-lived",
        upstream_mode="chat",
        channel_id="goal.goal-fixture",
    )
    calls: list[dict[str, object]] = []

    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {
            "ok": True,
            "status": "committed",
            "result_kind": "validated_progress",
            "resume_turn_key": "sha256:" + "b" * 64,
            "journal_ref": "turn:bbbbbbbbbbbbbbbb",
            "summary": "One material Chat turn advanced.",
            "next_action": "Read fresh LoopX state.",
            "validation": {"status": "passed"},
            "effects": {"state_written": True, "quota_spent": True},
            "quota_slot_spend_count": 1,
        }

    controller = ChatRuntimeController(
        store=store,
        codex_bin="codex",
        governed_turn_runner=runner,
    )
    turn, created = controller.submit_governed_turn(
        session_id=str(session["session_id"]),
        client_turn_id="material-fixture",
        message="Advance the fixture.",
        todo_id="todo-fixture",
        governed_agent_id="codex-peer-fixture",
        work_dir=tmp_path,
    )
    completed = controller.wait_for_turn(
        session_id=str(session["session_id"]),
        turn_id=str(turn["turn_id"]),
        timeout_sec=2,
    )

    assert created is True
    assert calls[0]["upstream_thread_id"] == "thread-long-lived"
    assert calls[0]["todo_id"] == "todo-fixture"
    assert calls[0]["agent_id"] == "codex-peer-fixture"
    assert completed["response"]["governance"] == {
        "schema_version": "loopx_chat_turn_governance_v0",
        "mode": "governed",
        "todo_id": "todo-fixture",
        "agent_id": "codex-peer-fixture",
        "turn_key": "sha256:" + "b" * 64,
        "journal_ref": "turn:bbbbbbbbbbbbbbbb",
        "status": "committed",
        "result_kind": "validated_progress",
        "validation": {"status": "passed"},
        "effects": {"state_written": True, "quota_spent": True},
        "quota_slot_spend_count": 1,
    }
    restored = store.load_session(str(session["session_id"]))
    deadline = time.monotonic() + 1
    while (
        restored is not None
        and restored["status"] != "ready"
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
        restored = store.load_session(str(session["session_id"]))
    assert restored is not None
    assert restored["upstream_thread_id"] == "thread-long-lived"
    assert restored["status"] == "ready"


def test_governed_chat_turn_rejects_a_non_codex_transport(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path / "runtime")
    session = store.create_session(
        goal_id="goal-fixture",
        agent_id="claude-code",
        adapter_kind="fixture",
        upstream_thread_id="thread-other-provider",
        channel_id="goal.goal-fixture",
    )
    controller = ChatRuntimeController(
        store=store,
        codex_bin="codex",
        governed_turn_runner=lambda **_kwargs: {},
    )

    with pytest.raises(ValueError, match="resumable Codex Goal session"):
        controller.submit_governed_turn(
            session_id=str(session["session_id"]),
            client_turn_id="material-fixture",
            message="Advance the fixture.",
            todo_id="todo-fixture",
            governed_agent_id="codex-peer-fixture",
            work_dir=tmp_path,
        )

from __future__ import annotations

import json
from pathlib import Path

from loopx.chat_store import ChatSessionStore
from loopx.cli import main


def _registry_payload() -> dict[str, object]:
    return {
        "goals": [
            {
                "id": "sample-goal",
                "coordination": {
                    "registered_agents": ["codex-sample-worker"],
                    "thread_agent_bindings": [
                        {
                            "host_surface": "codex-app-ssh",
                            "thread_id": "opaque-host-session",
                            "agent_id": "codex-sample-worker",
                        }
                    ],
                },
            }
        ]
    }


def _base_args(registry_path: Path, runtime_root: Path) -> list[str]:
    return [
        "--registry",
        str(registry_path),
        "--runtime-root",
        str(runtime_root),
        "--format",
        "json",
        "worker-bridge",
    ]


def test_attached_session_cli_bind_claim_and_complete(
    tmp_path: Path,
    capsys,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(_registry_payload()), encoding="utf-8")
    runtime_root = tmp_path / "runtime"
    base = _base_args(registry_path, runtime_root)

    assert (
        main(
            [
                *base,
                "attached-session-bind",
                "--goal-id",
                "sample-goal",
                "--agent-id",
                "codex-sample-worker",
                "--host-surface",
                "codex-app-ssh",
                "--host-session-id",
                "opaque-host-session",
                "--executor-endpoint-id",
                "codex",
                "--execute",
            ]
        )
        == 0
    )
    bound = json.loads(capsys.readouterr().out)
    session_id = bound["session"]["session_id"]
    assert "upstream_thread_id" not in bound["session"]

    store = ChatSessionStore(runtime_root)
    queued, created = store.create_queued_turn(
        session_id,
        client_turn_id="lark-message-1",
        message="hello from connector",
        origin="lark",
    )
    assert created

    assert (
        main(
            [
                *base,
                "attached-session-claim",
                "--session-id",
                session_id,
                "--host-surface",
                "codex-app-ssh",
                "--host-session-id",
                "opaque-host-session",
                "--claim-id",
                "claim-1",
            ]
        )
        == 0
    )
    claimed = json.loads(capsys.readouterr().out)
    assert claimed["turn"]["turn_id"] == queued["turn_id"]
    assert claimed["turn"]["message"] == "hello from connector"

    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps({"message": "hello from host"}), encoding="utf-8")
    assert (
        main(
            [
                *base,
                "attached-session-complete",
                "--session-id",
                session_id,
                "--turn-id",
                str(queued["turn_id"]),
                "--host-surface",
                "codex-app-ssh",
                "--host-session-id",
                "opaque-host-session",
                "--claim-id",
                "claim-1",
                "--completion-id",
                "completion-1",
                "--response-json",
                str(response_path),
            ]
        )
        == 0
    )
    completed = json.loads(capsys.readouterr().out)
    assert completed["created"] is True
    assert store.load_turn(session_id, str(queued["turn_id"]))["status"] == "completed"

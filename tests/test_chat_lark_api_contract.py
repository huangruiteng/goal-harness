from __future__ import annotations

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loopx.chat_server import (
    CHAT_GOAL_CONTEXTS_PATH,
    CHAT_LARK_APP_SETUPS_PATH,
    CHAT_LARK_APPS_PATH,
    CHAT_LARK_CHATS_PATH,
    CHAT_LARK_CONNECTIONS_PATH,
    ChatHTTPServer,
    build_goal_repository_contexts,
)
from loopx.chat_lark_api import LarkChatRequestMixin
from loopx.extensions.lark.goal_channel_contracts import write_goal_channel_binding
from loopx.extensions.lark.goal_channel_targets import add_lark_goal_channel_target


def test_lark_management_uses_dedicated_local_api_routes() -> None:
    assert CHAT_GOAL_CONTEXTS_PATH == "/api/chat/goals/contexts"
    assert CHAT_LARK_APPS_PATH == "/api/chat/lark/apps"
    assert CHAT_LARK_APP_SETUPS_PATH == "/api/chat/lark/app-setups"
    assert CHAT_LARK_CHATS_PATH == "/api/chat/lark/chats"
    assert CHAT_LARK_CONNECTIONS_PATH == "/api/chat/lark/connections"


def test_goal_repository_context_is_credential_free_and_path_free(tmp_path: Path) -> None:
    project = tmp_path / "private" / "loopx"
    project.mkdir(parents=True)
    calls: list[list[str]] = []

    def git_runner(args: list[str]) -> dict[str, Any]:
        calls.append(args)
        if args[-3:] == ["config", "--get", "remote.origin.url"]:
            return {"returncode": 0, "stdout": "git@github.com:loopx-ai/loopx.git\n"}
        if args[-2:] == ["branch", "--show-current"]:
            return {"returncode": 0, "stdout": "codex/lark-goal-topic-binding\n"}
        return {"returncode": 1, "stdout": ""}

    rows = build_goal_repository_contexts(
        registry={"goals": [{"id": "goal-alpha", "repo": str(project)}]},
        git_runner=git_runner,
    )

    assert rows == [
        {
            "goal_id": "goal-alpha",
            "repository": {
                "branch": "codex/lark-goal-topic-binding",
                "identity": "git:github.com/loopx-ai/loopx",
                "label": "loopx-ai/loopx",
                "read_only": True,
            },
        }
    ]
    encoded = json.dumps(rows)
    assert str(tmp_path) not in encoded
    assert "git@" not in encoded
    assert calls


def test_runtime_snapshot_reuses_private_goal_channel_bindings(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import loopx.chat_lark_api as api

    runtime_root = tmp_path / "runtime"
    project = tmp_path / "project"
    source_registry = project / ".loopx" / "registry.json"
    source_registry.parent.mkdir(parents=True)
    source_registry.write_text("{}\n", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry = {
        "goals": [
            {
                "id": "goal-alpha",
                "repo": str(project),
                "objective": "Alpha delivery",
            }
        ]
    }
    monkeypatch.setattr(api, "load_registry", lambda _path: registry)
    monkeypatch.setattr(api, "resolve_runtime_root", lambda *_args, **_kwargs: runtime_root)
    monkeypatch.setattr(
        api,
        "resolve_goal_source_runtime_route",
        lambda **_kwargs: {"source_registry": str(source_registry)},
    )
    target_path = runtime_root / "goal-channel-targets.json"
    add_lark_goal_channel_target(
        target_path=target_path,
        target_name="mew-product",
        chat_id="oc_public_fixture",
        chat_name="Product",
        identity_mode="local_user",
        sender_profile="mew",
        sender_identity="bot",
        bot_app_id="cli_public_fixture",
        bot_display_name="linkmacbot",
        cli_bin="fake-lark",
        execute=True,
    )
    write_goal_channel_binding(
        source_registry.parent / "goal-channel.json",
        {
            "schema_version": "loopx_goal_channel_lark_binding_v0",
            "bindings": {
                "goal-alpha": {
                    "goal_id": "goal-alpha",
                    "provider": "lark",
                    "enabled": True,
                    "target_ref": "mew-product",
                    "topic": {"root_message_id": "om_topic_alpha"},
                }
            },
        },
    )

    snapshot = api.build_lark_goal_topic_runtime_snapshot(
        registry_path=registry_path,
        runtime_root_override=None,
    )

    assert set(snapshot["binding_payloads"]) == {"goal-alpha"}
    assert snapshot["goal_contexts"] == {
        "goal-alpha": {
            "work_dir": str(project.resolve()),
            "objective": "Alpha delivery",
        }
    }
    assert snapshot["target_payload"]["targets"]["mew-product"]["identity"]["sender_profile"] == "mew"


def test_chat_server_closes_lark_goal_topic_runtime(monkeypatch: Any) -> None:
    closed: list[str] = []

    class Closer:
        def __init__(self, name: str) -> None:
            self.name = name

        def close(self) -> None:
            closed.append(self.name)

    monkeypatch.setattr(ThreadingHTTPServer, "server_close", lambda _self: None)
    server = object.__new__(ChatHTTPServer)
    server.lark_app_setup_manager = Closer("setup")  # type: ignore[assignment]
    server.lark_goal_topic_runtime = Closer("topics")  # type: ignore[attr-defined]
    server.runtime_controller = Closer("chat")  # type: ignore[assignment]
    server.server_close()

    assert closed == ["setup", "topics", "chat"]


def test_connect_refreshes_the_app_level_event_consumer(monkeypatch: Any, tmp_path: Path) -> None:
    import loopx.chat_lark_api as api

    refreshed: list[bool] = []
    responses: list[dict[str, Any]] = []
    monkeypatch.setattr(
        api,
        "connect_lark_goal_topic",
        lambda **_kwargs: {"ok": True, "status": "connected"},
    )

    class Handler(LarkChatRequestMixin):
        path = "/api/chat/lark/connections"
        server = SimpleNamespace(
            lark_goal_topic_runtime=SimpleNamespace(refresh=lambda: refreshed.append(True))
        )

        def _read_json(self) -> dict[str, Any]:
            return {
                "goal_id": "goal-alpha",
                "app_ref": "mew",
                "chat_id": "oc_public_fixture",
                "chat_name": "Product",
                "incoming_mode": "mentions",
                "execute": True,
            }

        def _goal_channel_context(self, _goal_id: str):
            return ({"goals": [{"id": "goal-alpha"}]}, tmp_path / "goal-channel.json")

        def _goal_channel_target_path(self) -> Path:
            return tmp_path / "goal-channel-targets.json"

        def _lark_runner(self):
            return lambda *_args: {"returncode": 0, "stdout": "{}", "stderr": ""}

        def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            responses.append({**payload, "http_status": status})

        def _send_error(self, message: str, **_kwargs: Any) -> None:
            raise AssertionError(message)

    Handler()._lark_connect()

    assert refreshed == [True]
    assert responses == [{"ok": True, "status": "connected", "http_status": 200}]

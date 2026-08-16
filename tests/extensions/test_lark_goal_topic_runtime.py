from __future__ import annotations

import importlib
import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from loopx.extensions.lark.event_inbox import inspect_lark_event_inbox
from loopx.extensions.lark.event_collector import _jq_projection
from loopx.extensions.lark.goal_channel_contracts import read_goal_channel_binding
from loopx.extensions.lark.goal_channel_targets import read_goal_channel_targets
from loopx.extensions.lark.goal_topic_connections import connect_lark_goal_topic


def test_goal_topic_runtime_exposes_the_inbox_bridge() -> None:
    module = importlib.import_module("loopx.extensions.lark.goal_topic_runtime")

    assert callable(getattr(module, "process_lark_goal_topic_event", None))


def test_existing_collector_preserves_topic_routing_fields() -> None:
    projection = _jq_projection("oc_public_fixture")

    assert "root_id:.root_id" in projection
    assert "parent_id:.parent_id" in projection
    assert "mentions:(.mentions // [])" in projection


def _connection_runner(state: dict[str, Any]):
    def run(args: list[str], _cwd: object, _timeout: object) -> dict[str, Any]:
        if "auth" in args and "status" in args:
            payload: Any = {
                "appId": "cli_public_fixture",
                "identities": {
                    "bot": {
                        "available": True,
                        "verified": True,
                        "appName": "linkmacbot",
                    }
                },
            }
        elif "chats" in args and "get" in args:
            payload = {"data": {"chat_id": "oc_public_fixture"}}
        elif "+chat-members-list" in args:
            payload = {"data": {"chats": [{"app_id": "cli_public_fixture"}]}}
        elif "+messages-send" in args:
            payload = {"data": {"message_id": "om_topic_alpha"}}
            state["topic_text"] = args[args.index("--text") + 1]
        elif "+messages-mget" in args:
            payload = {
                "data": {
                    "items": [
                        {
                            "message_id": "om_topic_alpha",
                            "body": {"content": state["topic_text"]},
                        }
                    ]
                }
            }
        else:
            raise AssertionError(args)
        return {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}

    return run


def _reply_runner(state: dict[str, Any]):
    def run(args: list[str]) -> dict[str, Any]:
        state.setdefault("calls", []).append(list(args))
        if args[3:6] == ["auth", "status", "--verify"]:
            payload: Any = {
                "identities": {
                    "bot": {
                        "available": True,
                        "verified": True,
                        "appName": "linkmacbot",
                    }
                }
            }
        elif args[3:6] == ["im", "chats", "get"]:
            payload = {"data": {"chat_id": "oc_public_fixture"}}
        elif "+messages-reply" in args:
            state["reply_text"] = args[args.index("--text") + 1]
            payload = {"data": {"message_id": "om_reply_fixture"}}
        elif "+messages-mget" in args:
            payload = {
                "data": {
                    "items": [
                        {
                            "message_id": "om_reply_fixture",
                            "body": {"content": state["reply_text"]},
                        }
                    ]
                }
            }
        else:
            raise AssertionError(args)
        return {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}

    return run


def test_mention_uses_existing_inbox_reply_and_ack_path(tmp_path: Path) -> None:
    from loopx.extensions.lark.goal_topic_runtime import process_lark_goal_topic_event

    state: dict[str, Any] = {}
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    registry = {
        "goals": [
            {
                "id": "goal-alpha",
                "repo": str(tmp_path),
                "objective": "Alpha delivery",
            }
        ]
    }
    connected = connect_lark_goal_topic(
        registry=registry,
        goal_id="goal-alpha",
        target_path=target_path,
        binding_path=binding_path,
        app_ref="mew",
        chat_id="oc_public_fixture",
        chat_name="Product group",
        incoming_mode="mentions",
        runner=_connection_runner(state),
        cli_bin="fake-lark",
    )
    assert connected["ok"] is True

    answers: list[tuple[str, str]] = []
    result = process_lark_goal_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "event_id": "evt_incoming",
            "message_id": "om_incoming",
            "chat_id": "oc_public_fixture",
            "root_id": "om_topic_alpha",
            "create_time": "2026-08-14T21:00:00Z",
            "content": "@linkmacbot 你现在 loopx 的版本是什么",
            "mentioned": True,
        },
        runtime_root=tmp_path / "runtime",
        answer=lambda route, text: (
            answers.append((str(route["goal_id"]), text))
            or "当前运行的是 LoopX 开发版。"
        ),
        reply_runner=_reply_runner(state),
    )

    assert result["ok"] is True
    assert result["status"] == "replied_and_acknowledged"
    assert result["goal_id"] == "goal-alpha"
    assert answers == [
        ("goal-alpha", "@linkmacbot 你现在 loopx 的版本是什么")
    ]
    assert state["reply_text"] == "当前运行的是 LoopX 开发版。"
    reply_call = next(call for call in state["calls"] if "+messages-reply" in call)
    assert reply_call[:3] == ["lark-cli", "--profile", "mew"]
    assert reply_call[reply_call.index("--message-id") + 1] == "om_incoming"
    projection = inspect_lark_event_inbox(
        project=tmp_path / "runtime",
        config_path=Path(result["inbox_config_ref"]),
    )
    assert projection["pending_count"] == 0
    assert projection["processed_count"] == 1


def test_bound_topic_reuses_one_goal_chat_session(tmp_path: Path) -> None:
    from loopx.extensions.lark.goal_topic_runtime import answer_lark_goal_topic

    class FakeRuntime:
        def __init__(self) -> None:
            self.open_calls: list[dict[str, Any]] = []
            self.submit_calls: list[dict[str, Any]] = []

        def open_session(self, **kwargs: Any):
            self.open_calls.append(kwargs)
            return ({"session_id": "session-alpha"}, bool(len(self.open_calls) > 1))

        def submit_turn(self, **kwargs: Any):
            self.submit_calls.append(kwargs)
            return ({"turn_id": "turn-alpha"}, True)

        def wait_for_turn(self, **_kwargs: Any):
            return {
                "status": "completed",
                "response": {"message": "当前运行的是 LoopX 开发版。"},
            }

    runtime = FakeRuntime()
    route = {
        "app_ref": "mew",
        "goal_id": "goal-alpha",
        "target_ref": "mew-product",
        "topic_root_message_id": "om_topic_alpha",
        "message_id": "om_incoming",
    }
    first = answer_lark_goal_topic(
        route=route,
        text="@linkmacbot 你现在 loopx 的版本是什么",
        work_dir=tmp_path,
        objective="Alpha delivery",
        runtime_controller=runtime,
    )
    second = answer_lark_goal_topic(
        route={**route, "message_id": "om_incoming_2"},
        text="再确认一下",
        work_dir=tmp_path,
        objective="Alpha delivery",
        runtime_controller=runtime,
    )

    assert first == "当前运行的是 LoopX 开发版。"
    assert second == first
    assert runtime.open_calls[0]["mode"] == "resume_latest"
    assert runtime.open_calls[0]["channel_id"].startswith("lark.")
    assert runtime.open_calls[0]["channel_id"] == runtime.open_calls[1]["channel_id"]
    assert runtime.submit_calls[0]["client_turn_id"].startswith("lark.")
    assert "只生成预览" in runtime.submit_calls[0]["message"]


def test_runtime_service_uses_one_consumer_for_reused_app_profile(tmp_path: Path) -> None:
    from loopx.extensions.lark.goal_topic_runtime import LarkGoalTopicRuntimeService

    started = threading.Event()
    stopped = threading.Event()
    profiles: list[str] = []
    target_payload = {
        "schema_version": "loopx_goal_channel_provider_targets_v0",
        "targets": {
            "mew-product": {
                "name": "mew-product",
                "provider": "lark",
                "enabled": True,
                "channel": {"chat_id": "oc_public_fixture", "chat_name": "Product"},
                "identity": {
                    "sender_profile": "mew",
                    "sender_identity": "bot",
                    "bot_app_id": "cli_public_fixture",
                    "bot_display_name": "linkmacbot",
                    "cli_bin": "fake-lark",
                },
            }
        },
    }
    binding_payloads = {
        goal_id: {
            "schema_version": "loopx_goal_channel_lark_binding_v0",
            "bindings": {
                goal_id: {
                    "goal_id": goal_id,
                    "provider": "lark",
                    "enabled": True,
                    "target_ref": "mew-product",
                    "topic": {"root_message_id": f"om_{goal_id}"},
                    "routing": {"incoming_mode": "mentions", "reply_mode": "topic_reply"},
                }
            },
        }
        for goal_id in ("goal-alpha", "goal-beta")
    }

    def poller(profile: str, _stop: threading.Event) -> None:
        profiles.append(profile)
        started.set()
        _stop.wait(2)
        stopped.set()

    service = LarkGoalTopicRuntimeService(
        snapshot_provider=lambda: {
            "target_payload": target_payload,
            "binding_payloads": binding_payloads,
            "goal_contexts": {},
        },
        runtime_root=tmp_path,
        runtime_controller=object(),
        profile_poller=poller,
    )
    service.refresh()

    assert started.wait(1)
    assert service.active_profiles() == ["mew"]
    assert profiles == ["mew"]

    service.close()
    assert stopped.wait(1)
    assert service.active_profiles() == []


def test_profile_stream_keeps_one_consumer_open_between_messages(tmp_path: Path) -> None:
    from loopx.extensions.lark.goal_topic_runtime import stream_lark_goal_topic_profile

    captured: dict[str, Any] = {}
    snapshot = {
        "target_payload": {
            "schema_version": "loopx_goal_channel_provider_targets_v0",
            "targets": {
                "mew-product": {
                    "name": "mew-product",
                    "provider": "lark",
                    "enabled": True,
                    "channel": {"chat_id": "oc_public_fixture"},
                    "identity": {
                        "sender_profile": "mew",
                        "sender_identity": "bot",
                        "bot_app_id": "cli_public_fixture",
                        "cli_bin": "fake-lark",
                    },
                }
            },
        },
        "binding_payloads": {
            "goal-alpha": {
                "schema_version": "loopx_goal_channel_lark_binding_v0",
                "bindings": {
                    "goal-alpha": {
                        "goal_id": "goal-alpha",
                        "provider": "lark",
                        "enabled": True,
                        "target_ref": "mew-product",
                        "topic": {"root_message_id": "om_topic_alpha"},
                        "routing": {
                            "incoming_mode": "mentions",
                            "reply_mode": "topic_reply",
                        },
                    }
                },
            }
        },
    }

    class FinishedConsumer:
        stdout = iter(())

        def poll(self) -> int:
            return 0

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def terminate(self) -> None:
            raise AssertionError("a completed consumer must not be terminated")

        def kill(self) -> None:
            raise AssertionError("a completed consumer must not be killed")

    def process_factory(args: list[str]) -> FinishedConsumer:
        captured["args"] = list(args)
        return FinishedConsumer()

    result = stream_lark_goal_topic_profile(
        profile="mew",
        snapshot_provider=lambda: snapshot,
        stop=threading.Event(),
        runtime_root=tmp_path,
        answer=lambda _route, _text: "ok",
        process_factory=process_factory,
    )

    timeout_index = captured["args"].index("--timeout")
    assert captured["args"][timeout_index + 1] == "30m"
    assert result == {
        "ok": True,
        "status": "stream_ended",
        "event_count": 0,
        "replied_count": 0,
    }


def test_profile_poll_routes_provider_event_through_existing_reply_path(tmp_path: Path) -> None:
    from loopx.extensions.lark.goal_topic_runtime import poll_lark_goal_topic_profile_once

    state: dict[str, Any] = {}
    target_payload = {
        "schema_version": "loopx_goal_channel_provider_targets_v0",
        "targets": {
            "mew-product": {
                "name": "mew-product",
                "provider": "lark",
                "enabled": True,
                "channel": {"chat_id": "oc_public_fixture", "chat_name": "Product"},
                "identity": {
                    "sender_profile": "mew",
                    "sender_identity": "bot",
                    "bot_app_id": "cli_public_fixture",
                    "bot_display_name": "linkmacbot",
                    "cli_bin": "fake-lark",
                },
            }
        },
    }
    binding_payloads = {
        "goal-alpha": {
            "schema_version": "loopx_goal_channel_lark_binding_v0",
            "bindings": {
                "goal-alpha": {
                    "goal_id": "goal-alpha",
                    "provider": "lark",
                    "enabled": True,
                    "target_ref": "mew-product",
                    "topic": {"root_message_id": "om_topic_alpha"},
                    "routing": {"incoming_mode": "mentions", "reply_mode": "topic_reply"},
                }
            },
        }
    }
    event = {
        "event_id": "evt_incoming",
        "message_id": "om_incoming",
        "chat_id": "oc_public_fixture",
        "create_time": "2026-08-14T21:00:00Z",
        "content": "@linkmacbot 你现在 loopx 的版本是什么",
    }

    def consume_runner(args: list[str]) -> dict[str, Any]:
        state["consume_args"] = list(args)
        return {"returncode": 0, "stdout": json.dumps(event) + "\n", "stderr": ""}

    def provider_runner(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert "+messages-mget" in args
        state["provider_attempts"] = int(state.get("provider_attempts") or 0) + 1
        if state["provider_attempts"] == 1:
            return subprocess.CompletedProcess(
                args,
                0,
                json.dumps({"data": {"items": []}}),
                "",
            )
        payload = {
            "data": {
                "items": [
                    {
                        "message_id": "om_incoming",
                        "chat_id": "oc_public_fixture",
                        "root_id": "om_topic_alpha",
                        "sender": {"sender_type": "user", "id": "ou_public_fixture"},
                    }
                ]
            }
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    result = poll_lark_goal_topic_profile_once(
        profile="mew",
        snapshot={
            "target_payload": target_payload,
            "binding_payloads": binding_payloads,
            "goal_contexts": {},
        },
        runtime_root=tmp_path,
        answer=lambda _route, _text: "当前运行的是 LoopX 开发版。",
        consume_runner=consume_runner,
        provider_runner=provider_runner,
        reply_runner=_reply_runner(state),
    )

    assert result == {
        "ok": True,
        "status": "polled",
        "event_count": 1,
        "replied_count": 1,
        "event_statuses": ["replied_and_acknowledged"],
    }
    assert state["consume_args"][:3] == ["fake-lark", "--profile", "mew"]
    assert "event" in state["consume_args"]
    assert state["provider_attempts"] == 2
    assert state["reply_text"] == "当前运行的是 LoopX 开发版。"

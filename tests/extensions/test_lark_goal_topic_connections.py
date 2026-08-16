from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.extensions.lark.goal_topic_connections import (
    connect_lark_goal_topic,
    disconnect_lark_goal_topic,
    list_lark_apps,
    list_lark_connections,
    list_lark_group_chats,
    reply_lark_goal_topic,
    route_lark_topic_event,
)
from loopx.extensions.lark.goal_channel_contracts import read_goal_channel_binding
from loopx.extensions.lark.goal_channel_targets import read_goal_channel_targets


APP_ID = "cli_public_fixture"
CHAT_ID = "oc_public_fixture"


def _registry(tmp_path: Path) -> dict[str, Any]:
    return {
        "goals": [
            {"id": "goal-alpha", "repo": str(tmp_path), "objective": "Alpha delivery"},
            {"id": "goal-beta", "repo": str(tmp_path), "objective": "Beta delivery"},
        ]
    }


def _runner(state: dict[str, Any]):
    def run(args: list[str], _cwd: object, _timeout: object) -> dict[str, Any]:
        state.setdefault("calls", []).append(list(args))
        profile = args[args.index("--profile") + 1] if "--profile" in args else ""
        if args[-2:] == ["profile", "list"] or args[-2:] == ["profile", "list"]:
            payload: Any = [
                {"name": "mew", "appId": APP_ID, "brand": "feishu", "active": True},
                {"name": "standby", "appId": "cli_standby_fixture", "brand": "feishu", "active": False},
            ]
        elif "auth" in args and "status" in args:
            payload = {
                "appId": APP_ID if profile == "mew" else "cli_standby_fixture",
                "identities": {
                    "bot": {
                        "available": True,
                        "verified": profile == "mew",
                        "appName": "LoopX Mew" if profile == "mew" else "Standby",
                    }
                },
            }
        elif "+chat-list" in args or "+chat-search" in args:
            payload = {"data": {"chats": [{"chat_id": CHAT_ID, "name": "Product group"}]}}
        elif "chats" in args and "get" in args:
            payload = {"data": {"chat_id": CHAT_ID, "name": "Product group"}}
        elif "+chat-members-list" in args:
            payload = {"data": {"chats": [{"app_id": APP_ID}]}}
        elif "+messages-send" in args:
            goal_id = "goal-alpha" if "Alpha delivery" in args[args.index("--text") + 1] else "goal-beta"
            message_id = "om_topic_alpha" if goal_id == "goal-alpha" else "om_topic_beta"
            state.setdefault("sent", {})[message_id] = args[args.index("--text") + 1]
            payload = {"data": {"message_id": message_id}}
        elif "+messages-reply" in args:
            state["reply_args"] = list(args)
            payload = {"data": {"message_id": "om_reply_fixture"}}
        elif "+messages-mget" in args:
            message_id = args[args.index("--message-ids") + 1]
            payload = {
                "data": {
                    "chats": [
                        {
                            "message_id": message_id,
                            "body": {"content": state.get("sent", {}).get(message_id, "reply ok")},
                        }
                    ]
                }
            }
        else:
            return {"returncode": 1, "stdout": "", "stderr": f"unexpected: {args}"}
        return {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}

    return run


def test_lists_apps_with_readiness_without_returning_secrets() -> None:
    state: dict[str, Any] = {}
    apps = list_lark_apps(runner=_runner(state), cli_bin="fake-lark")

    assert apps == [
        {"app_ref": "mew", "label": "LoopX Mew", "brand": "feishu", "active": True, "ready": True},
        {"app_ref": "standby", "label": "Standby", "brand": "feishu", "active": False, "ready": False},
    ]
    assert "secret" not in json.dumps(apps).lower()
    assert all("app_id" not in app for app in apps)


def test_lists_group_chats_through_the_selected_app() -> None:
    state: dict[str, Any] = {}
    chats = list_lark_group_chats(
        app_ref="mew",
        query="product",
        runner=_runner(state),
        cli_bin="fake-lark",
    )

    assert chats == [{"chat_id": CHAT_ID, "chat_name": "Product group"}]
    call = next(args for args in state["calls"] if "+chat-search" in args)
    assert call[call.index("--profile") + 1] == "mew"
    assert "--types" not in call

    list_lark_group_chats(
        app_ref="mew",
        runner=_runner(state),
        cli_bin="fake-lark",
    )
    list_call = next(args for args in state["calls"] if "+chat-list" in args)
    assert list_call[list_call.index("--types") + 1] == "group"


def test_two_goals_share_one_connection_with_distinct_topics(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"

    for goal_id in ("goal-alpha", "goal-beta"):
        result = connect_lark_goal_topic(
            registry=_registry(tmp_path),
            goal_id=goal_id,
            target_path=target_path,
            binding_path=binding_path,
            app_ref="mew",
            chat_id=CHAT_ID,
            chat_name="Product group",
            incoming_mode="mentions",
            runner=runner,
            cli_bin="fake-lark",
        )
        assert result["ok"] is True
        assert result["readback_verified"] is True

    targets = read_goal_channel_targets(target_path)["targets"]
    assert len(targets) == 1
    bindings = read_goal_channel_binding(binding_path)["bindings"]
    assert bindings["goal-alpha"]["target_ref"] == bindings["goal-beta"]["target_ref"]
    assert bindings["goal-alpha"]["topic"]["root_message_id"] == "om_topic_alpha"
    assert bindings["goal-beta"]["topic"]["root_message_id"] == "om_topic_beta"
    assert bindings["goal-alpha"]["routing"] == {
        "incoming_mode": "mentions",
        "reply_mode": "topic_reply",
    }

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path, "goal-beta": binding_path},
    )
    assert len(rows) == 2
    assert {row["goal_id"] for row in rows} == {"goal-alpha", "goal-beta"}
    assert {row["app_ref"] for row in rows} == {"mew"}
    assert {row["chat_name"] for row in rows} == {"Product group"}
    assert {row["topic_name"] for row in rows} == {"Alpha delivery", "Beta delivery"}
    assert "oc_" not in json.dumps(rows)
    assert "om_" not in json.dumps(rows)


def test_routes_mentions_by_topic_and_replies_in_thread(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    connect_lark_goal_topic(
        registry=_registry(tmp_path),
        goal_id="goal-alpha",
        target_path=target_path,
        binding_path=binding_path,
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        incoming_mode="mentions",
        runner=runner,
        cli_bin="fake-lark",
    )

    unmentioned = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={"chat_id": CHAT_ID, "root_id": "om_topic_alpha", "message_id": "om_incoming", "mentioned": False},
    )
    assert unmentioned is None

    route = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={"chat_id": CHAT_ID, "root_id": "om_topic_alpha", "message_id": "om_incoming", "mentioned": True},
    )
    assert route == {
        "app_ref": "mew",
        "goal_id": "goal-alpha",
        "message_id": "om_incoming",
        "reply_mode": "topic_reply",
        "target_ref": next(iter(read_goal_channel_targets(target_path)["targets"])),
        "topic_root_message_id": "om_topic_alpha",
    }

    reply_route = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_reply_to_bot",
            "mentioned": False,
            "reply_context_verified": True,
            "reply_to_bot": True,
        },
    )
    assert reply_route is not None
    assert reply_route["goal_id"] == "goal-alpha"
    assert reply_route["message_id"] == "om_reply_to_bot"

    provider_mention_route = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_provider_mention",
            "content": "@LoopX Mew 当前版本是什么？",
            "mentions": [{"name": "LoopX Mew"}],
        },
    )
    assert provider_mention_route is not None
    assert provider_mention_route["goal_id"] == "goal-alpha"

    rendered_mention_route = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_rendered_mention",
            "content": "@LoopX Mew 当前版本是什么？",
        },
    )
    assert rendered_mention_route is not None
    assert rendered_mention_route["goal_id"] == "goal-alpha"

    self_message_route = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_self_message",
            "sender_id": APP_ID,
            "content": "@LoopX Mew 当前运行的是 LoopX 开发版。",
        },
    )
    assert self_message_route is None

    reply = reply_lark_goal_topic(
        route=route,
        text="Handled",
        runner=runner,
        cli_bin="fake-lark",
    )
    assert reply["ok"] is True
    assert "--reply-in-thread" in state["reply_args"]
    assert state["reply_args"][state["reply_args"].index("--message-id") + 1] == "om_incoming"


def test_disconnect_removes_only_the_selected_goal_topic(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    for goal_id in ("goal-alpha", "goal-beta"):
        connect_lark_goal_topic(
            registry=_registry(tmp_path),
            goal_id=goal_id,
            target_path=target_path,
            binding_path=binding_path,
            app_ref="mew",
            chat_id=CHAT_ID,
            chat_name="Product group",
            incoming_mode="mentions",
            runner=runner,
            cli_bin="fake-lark",
        )

    result = disconnect_lark_goal_topic(binding_path=binding_path, goal_id="goal-alpha")
    assert result["ok"] is True
    bindings = read_goal_channel_binding(binding_path)["bindings"]
    assert set(bindings) == {"goal-beta"}
    assert len(read_goal_channel_targets(target_path)["targets"]) == 1

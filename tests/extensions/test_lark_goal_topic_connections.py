from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.extensions.lark.goal_channel_contracts import read_goal_channel_binding
from loopx.extensions.lark.goal_channel_targets import (
    add_lark_goal_channel_target,
    read_goal_channel_targets,
)
from loopx.extensions.lark.goal_topic_connections import (
    LarkGroupChatLookupError,
    connect_lark_goal_topic,
    decide_lark_topic_event,
    disconnect_lark_goal_topic,
    list_lark_apps,
    list_lark_connections,
    list_lark_group_chats,
    reply_lark_goal_topic,
    route_lark_topic_event,
)

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
        elif "auth" in args and "check" in args:
            ready = profile == "mew"
            payload = {
                "ok": ready,
                "granted": ["im:message", "im:message:readonly"] if ready else [],
                "missing": [] if ready else ["im:message", "im:message:readonly"],
            }
            if not ready:
                return {"returncode": 1, "stdout": json.dumps(payload), "stderr": ""}
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
        {
            "app_ref": "mew",
            "label": "LoopX Mew",
            "brand": "feishu",
            "active": True,
            "ready": True,
            "reply_ready": True,
            "health_error_code": None,
        },
        {
            "app_ref": "standby",
            "label": "Standby",
            "brand": "feishu",
            "active": False,
            "ready": False,
            "reply_ready": False,
            "health_error_code": "lark_app_not_ready",
        },
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
    assert call[call.index("--as") + 1] == "bot"
    assert "--types" not in call

    list_lark_group_chats(
        app_ref="mew",
        runner=_runner(state),
        cli_bin="fake-lark",
    )
    list_call = next(args for args in state["calls"] if "+chat-list" in args)
    assert list_call[list_call.index("--types") + 1] == "group"
    assert list_call[list_call.index("--as") + 1] == "bot"


def test_group_chat_lookup_failure_is_not_silently_reported_as_empty() -> None:
    def failing_runner(args: list[str], _cwd: object, _timeout: object) -> dict[str, Any]:
        return {"returncode": 1, "stdout": "", "stderr": "provider unavailable"}

    with pytest.raises(LarkGroupChatLookupError) as error:
        list_lark_group_chats(
            app_ref="mew",
            runner=failing_runner,
            cli_bin="fake-lark",
        )

    assert getattr(error.value, "error_code", None) == "lark_group_lookup_failed"


def test_async_inbox_requires_one_registered_agent(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry["goals"][0]["coordination"] = {
        "registered_agents": ["agent-alpha"]
    }

    with pytest.raises(ValueError, match="requires a registered agent_id"):
        connect_lark_goal_topic(
            registry=registry,
            registry_path=tmp_path / ".loopx" / "registry.json",
            goal_id="goal-alpha",
            target_path=tmp_path / "targets.json",
            binding_path=tmp_path / "binding.json",
            app_ref="mew",
            chat_id=CHAT_ID,
            chat_name="Product group",
            ingress_mode="async_inbox",
            execute=False,
        )

    with pytest.raises(ValueError, match="registered for the Goal"):
        connect_lark_goal_topic(
            registry=registry,
            registry_path=tmp_path / ".loopx" / "registry.json",
            goal_id="goal-alpha",
            agent_id="agent-other",
            target_path=tmp_path / "targets.json",
            binding_path=tmp_path / "binding.json",
            app_ref="mew",
            chat_id=CHAT_ID,
            chat_name="Product group",
            ingress_mode="async_inbox",
            execute=False,
        )

    preview = connect_lark_goal_topic(
        registry=registry,
        registry_path=tmp_path / ".loopx" / "registry.json",
        goal_id="goal-alpha",
        agent_id="agent-alpha",
        target_path=tmp_path / "targets.json",
        binding_path=tmp_path / "binding.json",
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        incoming_mode="mentions",
        capture_scope="configured_chat_all",
        ingress_mode="async_inbox",
        execute=False,
        runner=_runner({}),
        cli_bin="fake-lark",
    )

    assert preview["details"]["capture_scope"] == "configured_chat_all"
    assert preview["details"]["incoming_mode"] == "all"


@pytest.mark.parametrize("ingress_mode", ["live_steering", "session_queue"])
def test_session_ingress_modes_require_and_persist_exact_session(
    tmp_path: Path,
    ingress_mode: str,
) -> None:
    registry = _registry(tmp_path)
    registry["goals"][0]["coordination"] = {
        "registered_agents": ["agent-alpha"]
    }
    with pytest.raises(ValueError, match="exact active Agent session"):
        connect_lark_goal_topic(
            registry=registry,
            goal_id="goal-alpha",
            agent_id="agent-alpha",
            target_path=tmp_path / "targets.json",
            binding_path=tmp_path / "binding.json",
            app_ref="mew",
            chat_id=CHAT_ID,
            chat_name="Product group",
            ingress_mode=ingress_mode,
            execute=False,
        )

    connected = connect_lark_goal_topic(
        registry=registry,
        goal_id="goal-alpha",
        agent_id="agent-alpha",
        session_id="session-alpha",
        target_path=tmp_path / "targets.json",
        binding_path=tmp_path / "binding.json",
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        ingress_mode=ingress_mode,
        runner=_runner({}),
        cli_bin="fake-lark",
    )

    assert connected["ok"] is True
    binding = read_goal_channel_binding(tmp_path / "binding.json")["bindings"]["goal-alpha"]
    assert binding["agent_id"] == "agent-alpha"
    assert binding["session_id"] == "session-alpha"
    assert binding["routing"]["ingress_mode"] == ingress_mode


def test_async_inbox_registration_failure_preserves_verified_write_receipt(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    registry["goals"][0]["coordination"] = {
        "registered_agents": ["agent-alpha"]
    }
    state: dict[str, Any] = {}

    def fail_registration(**_kwargs: Any) -> dict[str, Any]:
        assert any("+messages-send" in call for call in state["calls"])
        return {"ok": False}

    monkeypatch.setattr(
        "loopx.extensions.lark.goal_topic_connections.configure_goal_with_global_sync",
        fail_registration,
    )

    result = connect_lark_goal_topic(
        registry=registry,
        registry_path=tmp_path / ".loopx" / "registry.json",
        goal_id="goal-alpha",
        agent_id="agent-alpha",
        target_path=tmp_path / "targets.json",
        binding_path=tmp_path / "binding.json",
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        ingress_mode="async_inbox",
        runner=_runner(state),
        cli_bin="fake-lark",
    )

    assert result["ok"] is False
    assert result["status"] == "sent_verified_registration_failed"
    assert result["external_write_performed"] is True
    assert result["readback_verified"] is True
    assert not (tmp_path / "binding.json").exists()


@pytest.mark.parametrize("missing_prerequisite", ["registry_path", "goal_repository"])
def test_async_inbox_preflights_local_state_before_provider_write(
    tmp_path: Path,
    missing_prerequisite: str,
) -> None:
    registry = _registry(tmp_path)
    registry["goals"][0]["coordination"] = {"registered_agents": ["agent-alpha"]}
    registry_path: Path | None = tmp_path / ".loopx" / "registry.json"
    if missing_prerequisite == "registry_path":
        registry_path = None
    else:
        registry["goals"][0]["repo"] = str(tmp_path / "missing-project")
    state: dict[str, Any] = {}

    with pytest.raises(ValueError):
        connect_lark_goal_topic(
            registry=registry,
            registry_path=registry_path,
            goal_id="goal-alpha",
            agent_id="agent-alpha",
            target_path=tmp_path / "targets.json",
            binding_path=tmp_path / "binding.json",
            app_ref="mew",
            chat_id=CHAT_ID,
            chat_name="Product group",
            ingress_mode="async_inbox",
            execute=True,
            runner=_runner(state),
            cli_bin="fake-lark",
        )

    assert not any("+messages-send" in call for call in state.get("calls", []))


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
        "capture_scope": "addressed_only",
        "ingress_mode": "direct_session",
        "reply_mode": "topic_reply",
    }

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path, "goal-beta": binding_path},
        runner=runner,
        cli_bin="fake-lark",
    )
    assert len(rows) == 2
    assert {row["goal_id"] for row in rows} == {"goal-alpha", "goal-beta"}
    assert {row["app_ref"] for row in rows} == {"mew"}
    assert {row["chat_name"] for row in rows} == {"Product group"}
    assert {row["topic_name"] for row in rows} == {"Alpha delivery", "Beta delivery"}
    assert all(row["reply_ready"] is True for row in rows)
    assert all(row["health_error_code"] is None for row in rows)
    assert "oc_" not in json.dumps(rows)
    assert "om_" not in json.dumps(rows)


def test_listening_connection_without_received_events_is_not_reply_ready(
    tmp_path: Path,
) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    connected = connect_lark_goal_topic(
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
    assert connected["ok"] is True

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path},
        runner=runner,
        cli_bin="fake-lark",
        runtime_health={
            "mew": {
                "status": "listening",
                "error_code": None,
                "event_count": 0,
                "replied_count": 0,
                "last_event_status": None,
            }
        },
    )

    assert rows[0]["listener_status"] == "listening"
    assert rows[0]["reply_ready"] is False
    assert rows[0]["health_error_code"] == "lark_event_delivery_unverified"


def test_connect_preview_uses_verified_bot_identity_without_user_oauth(
    tmp_path: Path,
) -> None:
    state: dict[str, Any] = {}
    base_runner = _runner(state)

    def runner(args: list[str], cwd: object, timeout: object) -> dict[str, Any]:
        if "auth" in args and "check" in args:
            state.setdefault("calls", []).append(list(args))
            return {
                "returncode": 1,
                "stdout": json.dumps(
                    {
                        "ok": False,
                        "granted": ["im:message"],
                        "missing": ["im:message:readonly"],
                        "suggestion": "private provider detail must not escape",
                    }
                ),
                "stderr": "",
            }
        return base_runner(args, cwd, timeout)

    result = connect_lark_goal_topic(
        registry=_registry(tmp_path),
        goal_id="goal-alpha",
        target_path=tmp_path / "goal-channel-targets.json",
        binding_path=tmp_path / "goal-channel.json",
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        execute=False,
        runner=runner,
        cli_bin="fake-lark",
    )

    assert result["ok"] is True
    assert result["status"] == "preview_ready"
    assert result["details"]["app_ref"] == "mew"
    assert not any("auth" in call and "check" in call for call in state["calls"])
    assert not any("+messages-send" in call for call in state["calls"])
    assert not (tmp_path / "goal-channel.json").exists()


def test_connection_health_reports_received_event_processing_blocker(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    result = connect_lark_goal_topic(
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
    assert result["ok"] is True

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path},
        runner=runner,
        cli_bin="fake-lark",
        runtime_health={
            "mew": {
                "status": "listening",
                "event_count": 1,
                "replied_count": 0,
                "last_event_status": "message_context_permission_required",
                "error_code": None,
            }
        },
    )

    assert rows[0]["reply_ready"] is False
    assert rows[0]["health_error_code"] == "message_context_permission_required"
    assert rows[0]["history_permission_guidance"] == {
        "schema_version": "lark_bot_group_history_permission_guidance_v0",
        "identity": "bot",
        "capability": "group_history_pagination",
        "action": "enable_application_scopes_and_publish",
        "required_scopes": [
            "im:message.group_msg",
            "im:message.group_msg.include_bot:read",
        ],
        "api_document_url": (
            "https://open.feishu.cn/document/server-docs/im-v1/message/list"
            "?appId=cli_public_fixture"
        ),
    }


def test_connection_health_reports_ambiguous_topic_context(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    result = connect_lark_goal_topic(
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
    assert result["ok"] is True

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path},
        runner=runner,
        cli_bin="fake-lark",
        runtime_health={
            "mew": {
                "status": "listening",
                "event_count": 1,
                "replied_count": 0,
                "last_event_status": "topic_context_ambiguous",
                "error_code": None,
            }
        },
    )

    assert rows[0]["reply_ready"] is False
    assert rows[0]["health_error_code"] == "topic_context_ambiguous"


def test_connection_health_reports_safe_topic_route_mismatch(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    connected = connect_lark_goal_topic(
        registry=_registry(tmp_path),
        goal_id="goal-alpha",
        target_path=target_path,
        binding_path=binding_path,
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        incoming_mode="mentions",
        runner=_runner(state),
        cli_bin="fake-lark",
    )
    assert connected["ok"] is True

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path},
        runner=_runner(state),
        cli_bin="fake-lark",
        runtime_health={
            "mew": {
                "status": "listening",
                "event_count": 1,
                "replied_count": 0,
                "last_event_status": "ignored",
                "last_event_reason": "topic_mismatch",
                "error_code": None,
            }
        },
    )

    assert rows[0]["reply_ready"] is False
    assert rows[0]["health_error_code"] == "lark_event_route_mismatch"
    assert rows[0]["last_event_reason"] == "topic_mismatch"


def test_connection_health_drops_unknown_route_reason(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    connected = connect_lark_goal_topic(
        registry=_registry(tmp_path),
        goal_id="goal-alpha",
        target_path=target_path,
        binding_path=binding_path,
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        incoming_mode="mentions",
        runner=_runner(state),
        cli_bin="fake-lark",
    )
    assert connected["ok"] is True

    rows = list_lark_connections(
        registry=_registry(tmp_path),
        target_path=target_path,
        binding_paths={"goal-alpha": binding_path},
        runner=_runner(state),
        cli_bin="fake-lark",
        runtime_health={
            "mew": {
                "status": "listening",
                "event_count": 1,
                "replied_count": 0,
                "last_event_status": "ignored",
                "last_event_reason": "future_private_reason",
                "error_code": None,
            }
        },
    )

    assert rows[0]["last_event_reason"] is None


def test_connect_uses_bot_chat_access_when_member_listing_is_unavailable(
    tmp_path: Path,
) -> None:
    state: dict[str, Any] = {}
    base_runner = _runner(state)

    def runner(args: list[str], cwd: object, timeout: object) -> dict[str, Any]:
        if "+chat-members-list" in args:
            state.setdefault("calls", []).append(list(args))
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": "identity lacks permission to enumerate chat bots",
            }
        return base_runner(args, cwd, timeout)

    result = connect_lark_goal_topic(
        registry=_registry(tmp_path),
        goal_id="goal-alpha",
        target_path=tmp_path / "goal-channel-targets.json",
        binding_path=tmp_path / "goal-channel.json",
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        incoming_mode="mentions",
        runner=runner,
        cli_bin="fake-lark",
    )

    assert result["ok"] is True
    assert any("+chat-members-list" in call for call in state["calls"])
    bot_chat_checks = [
        call
        for call in state["calls"]
        if "chats" in call and "get" in call and "--as" in call
    ]
    assert bot_chat_checks
    assert all(call[call.index("--as") + 1] == "bot" for call in bot_chat_checks)


def test_existing_target_cli_bin_has_priority_for_connection(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
    runner = _runner(state)
    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    add_lark_goal_channel_target(
        target_path=target_path,
        target_name="mew-product",
        chat_id=CHAT_ID,
        chat_name="Product group",
        identity_mode="local_user",
        sender_profile="mew",
        sender_identity="bot",
        bot_app_id=APP_ID,
        bot_display_name="LoopX Mew",
        cli_bin="target-lark-cli",
        execute=True,
    )

    result = connect_lark_goal_topic(
        registry=_registry(tmp_path),
        goal_id="goal-alpha",
        target_path=target_path,
        binding_path=binding_path,
        app_ref="mew",
        chat_id=CHAT_ID,
        chat_name="Product group",
        runner=runner,
        cli_bin="discovered-lark-cli",
    )

    assert result["ok"] is True
    assert state["calls"]
    assert {call[0] for call in state["calls"]} == {"target-lark-cli"}


def test_routes_bound_topic_messages_and_replies_in_thread(tmp_path: Path) -> None:
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

    unmentioned_decision = decide_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={"chat_id": CHAT_ID, "root_id": "om_topic_alpha", "message_id": "om_incoming", "mentioned": False},
    )
    assert unmentioned_decision == {"matched": False, "reason": "not_addressed", "route": None}

    unmentioned = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={"chat_id": CHAT_ID, "root_id": "om_topic_alpha", "message_id": "om_incoming", "mentioned": False},
    )
    assert unmentioned is None

    invalid_binding = read_goal_channel_binding(binding_path)
    invalid_binding["bindings"]["goal-alpha"]["routing"]["ingress_mode"] = "async-inbox"
    invalid = decide_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": invalid_binding},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_invalid_routing",
            "content": "@LoopX Mew hello",
        },
    )
    assert invalid == {
        "matched": False,
        "reason": "invalid_routing_state",
        "route": None,
    }

    # Legacy bindings without capture_scope still derive it from incoming_mode.
    all_binding = read_goal_channel_binding(binding_path)
    all_binding["bindings"]["goal-alpha"]["routing"].pop("capture_scope")
    all_binding["bindings"]["goal-alpha"]["routing"]["incoming_mode"] = "all"
    unmentioned_all_mode = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": all_binding},
        event={"chat_id": CHAT_ID, "root_id": "om_topic_alpha", "message_id": "om_incoming", "mentioned": False},
    )
    assert unmentioned_all_mode is not None
    assert unmentioned_all_mode["goal_id"] == "goal-alpha"

    # Negative cases: mentioning another user or @all must NOT match in mentions mode
    other_user_decision = decide_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_other_user",
            "content": "@Alice 请看一下这个文档",
            "mentions": [{"name": "Alice", "id": "ou_alice_999"}],
        },
    )
    assert other_user_decision == {"matched": False, "reason": "not_addressed", "route": None}

    all_mention_decision = decide_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_all_mention",
            "content": "@_all 下午两点开会",
            "mentions": [{"key": "@_all", "name": "所有人"}],
        },
    )
    assert all_mention_decision == {"matched": False, "reason": "not_addressed", "route": None}

    unrelated_mentions_decision = decide_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_unrelated",
            "content": "hello team",
            "mentions": [{"name": "Bob", "id": "ou_bob_888"}],
        },
    )
    assert unrelated_mentions_decision == {"matched": False, "reason": "not_addressed", "route": None}

    route = route_lark_topic_event(
        target_payload=read_goal_channel_targets(target_path),
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_incoming",
            "content": "@LoopX Mew hello",
            "mentions": [{"name": "LoopX Mew", "id": "ou_mew_bot"}],
        },
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
            "mentions": [{"name": "LoopX Mew", "id": APP_ID}],
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


def test_provider_bot_open_id_is_persisted_and_routes_tokenized_mentions(
    tmp_path: Path,
) -> None:
    state: dict[str, Any] = {}
    base_runner = _runner(state)

    def runner(args: list[str], cwd: object, timeout: object) -> dict[str, Any]:
        result = base_runner(args, cwd, timeout)
        if "auth" in args and "status" in args and result["returncode"] == 0:
            payload = json.loads(result["stdout"])
            payload["identities"]["bot"]["openId"] = "ou_loopx_mew"
            result = {**result, "stdout": json.dumps(payload)}
        return result

    target_path = tmp_path / "goal-channel-targets.json"
    binding_path = tmp_path / "goal-channel.json"
    connected = connect_lark_goal_topic(
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

    assert connected["ok"] is True
    targets = read_goal_channel_targets(target_path)
    target = next(iter(targets["targets"].values()))
    assert target["identity"]["bot_open_id"] == "ou_loopx_mew"
    decision = decide_lark_topic_event(
        target_payload=targets,
        binding_payloads={"goal-alpha": read_goal_channel_binding(binding_path)},
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_tokenized_mention",
            "content": "@_user_1 请处理",
            "mentions": [{"id": {"open_id": "ou_loopx_mew"}}],
        },
    )
    assert decision["matched"] is True
    assert decision["reason"] == "matched"


def test_topic_route_decision_reports_safe_reason_codes(tmp_path: Path) -> None:
    state: dict[str, Any] = {}
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
        runner=_runner(state),
        cli_bin="fake-lark",
    )
    targets = read_goal_channel_targets(target_path)
    bindings = {"goal-alpha": read_goal_channel_binding(binding_path)}

    cases = [
        ({"chat_id": CHAT_ID}, "invalid_event"),
        (
            {
                "chat_id": "oc_other_fixture",
                "root_id": "om_topic_alpha",
                "message_id": "om_incoming",
                "mentioned": True,
            },
            "chat_mismatch",
        ),
        (
            {
                "chat_id": CHAT_ID,
                "root_id": "om_other_topic",
                "message_id": "om_incoming",
                "mentioned": True,
            },
            "topic_mismatch",
        ),
        (
            {
                "chat_id": CHAT_ID,
                "root_id": "om_topic_alpha",
                "message_id": "om_incoming",
                "sender_id": APP_ID,
                "mentioned": True,
            },
            "self_message",
        ),
        (
            {
                "chat_id": CHAT_ID,
                "root_id": "om_topic_alpha",
                "message_id": "om_incoming_other_mention",
                "content": "@Alice please review @LoopX Mew draft",
                "mentions": [
                    {
                        "key": "@_user_1",
                        "id": {"open_id": "ou_alice"},
                        "name": "Alice",
                    }
                ],
            },
            "not_addressed",
        ),
        (
            {
                "chat_id": CHAT_ID,
                "root_id": "om_topic_alpha",
                "message_id": "om_incoming_prefix_collision",
                "content": "@LoopXMewExtra bot",
            },
            "not_addressed",
        ),
        (
            {
                "chat_id": CHAT_ID,
                "root_id": "om_topic_alpha",
                "message_id": "om_bare_reply_to_bot_unverified",
                "content": "arbitrary reply without verified context",
                "reply_to_bot": True,
            },
            "not_addressed",
        ),
        (
            {
                "chat_id": CHAT_ID,
                "root_id": "om_topic_alpha",
                "message_id": "om_bare_addressed_to_bot",
                "content": "arbitrary message with addressed_to_bot boolean",
                "addressed_to_bot": True,
            },
            "not_addressed",
        ),
    ]
    for event, reason in cases:
        decision = decide_lark_topic_event(
            target_payload=targets,
            binding_payloads=bindings,
            event=event,
        )
        assert decision == {"matched": False, "reason": reason, "route": None}

    matched = decide_lark_topic_event(
        target_payload=targets,
        binding_payloads=bindings,
        event={
            "chat_id": CHAT_ID,
            "root_id": "om_topic_alpha",
            "message_id": "om_incoming",
            "content": "@_user_1 你好",
            "mentions": [
                {
                    "key": "@_user_1",
                    "id": {"open_id": "ou_public_fixture"},
                    "name": " @LoopX   Mew ",
                }
            ],
        },
    )
    assert matched["matched"] is True
    assert matched["reason"] == "matched"
    assert matched["route"]["goal_id"] == "goal-alpha"


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

"""Local-private Lark App, group connection, and Goal Topic bindings.

The module layers the workspace UI on top of the existing Goal Channel target
and binding stores.  App credentials remain owned by ``lark-cli`` profiles;
LoopX stores only a safe profile reference, group target, and per-Goal topic
root message needed for routing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...control_plane.runtime.public_safety import public_safe_compact_text
from .goal_channel_contracts import (
    binding_for_goal,
    goal_from_registry,
    goal_objective,
    now_iso,
    operation_packet,
    provider_idempotency_key,
    read_goal_channel_binding,
    save_goal_binding,
    semantic_key,
    write_goal_channel_binding,
)
from .goal_channel_targets import (
    add_lark_goal_channel_target,
    goal_channel_target_for_name,
    read_goal_channel_targets,
)
from .goal_channel_transport import (
    APP_ID_PATTERN,
    CHAT_ID_PATTERN,
    MESSAGE_ID_PATTERN,
    SAFE_PROFILE_PATTERN,
    bot_membership_verified,
    call,
    chat_verified,
    find_first_string,
    json_payload,
    lark_args,
    message_readback_verified,
)
from .presentation.kanban import CommandRunner, DEFAULT_CLI_BIN, default_subprocess_runner


INCOMING_MODES = {"mentions", "all"}


def _json_value(result: Mapping[str, Any]) -> Any:
    try:
        return json.loads(str(result.get("stdout") or ""))
    except json.JSONDecodeError:
        return None


def _profile_ref(value: Any) -> str:
    profile = str(value or "").strip()
    if not SAFE_PROFILE_PATTERN.fullmatch(profile):
        raise ValueError("Lark App reference must be a safe lark-cli profile name")
    return profile


def _app_identity(
    *,
    app_ref: str,
    runner: CommandRunner,
    cli_bin: str,
) -> dict[str, Any] | None:
    profile = _profile_ref(app_ref)
    result = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=["auth", "status", "--verify", "--json"],
        ),
    )
    payload = json_payload(result)
    identities = payload.get("identities")
    bot = identities.get("bot") if isinstance(identities, Mapping) else None
    app_id = str(payload.get("appId") or "")
    if (
        result.get("returncode") != 0
        or not isinstance(bot, Mapping)
        or not APP_ID_PATTERN.fullmatch(app_id)
    ):
        return None
    return {
        "app_id": app_id,
        "label": public_safe_compact_text(bot.get("appName") or profile, limit=60),
        "ready": bot.get("available") is True and bot.get("verified") is True,
    }


def list_lark_apps(
    *,
    runner: CommandRunner = default_subprocess_runner,
    cli_bin: str = DEFAULT_CLI_BIN,
) -> list[dict[str, Any]]:
    result = call(runner, [cli_bin, "profile", "list"])
    raw_profiles = _json_value(result)
    if result.get("returncode") != 0 or not isinstance(raw_profiles, list):
        return []
    apps: list[dict[str, Any]] = []
    for raw in raw_profiles:
        if not isinstance(raw, Mapping):
            continue
        try:
            app_ref = _profile_ref(raw.get("name"))
        except ValueError:
            continue
        identity = _app_identity(app_ref=app_ref, runner=runner, cli_bin=cli_bin)
        apps.append(
            {
                "app_ref": app_ref,
                "label": str((identity or {}).get("label") or app_ref),
                "brand": public_safe_compact_text(raw.get("brand") or "lark", limit=20),
                "active": raw.get("active") is True,
                "ready": bool(identity and identity.get("ready")),
            }
        )
    return apps


def _chat_items(payload: Any) -> list[dict[str, str]]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    items = data.get("chats") if isinstance(data, Mapping) else None
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    chats: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        chat_id = str(item.get("chat_id") or "")
        if not CHAT_ID_PATTERN.fullmatch(chat_id) or chat_id in seen:
            continue
        seen.add(chat_id)
        chats.append(
            {
                "chat_id": chat_id,
                "chat_name": public_safe_compact_text(item.get("name") or "Unnamed group", limit=60),
            }
        )
    return chats[:50]


def list_lark_group_chats(
    *,
    app_ref: str,
    query: str | None = None,
    runner: CommandRunner = default_subprocess_runner,
    cli_bin: str = DEFAULT_CLI_BIN,
) -> list[dict[str, str]]:
    profile = _profile_ref(app_ref)
    keyword = str(query or "").strip()
    tail = [
        "im",
        "+chat-search" if keyword else "+chat-list",
        *(["--query", keyword] if keyword else ["--types", "group"]),
        "--page-size",
        "50",
        "--as",
        "user",
        "--format",
        "json",
    ]
    result = call(runner, lark_args(cli_bin=cli_bin, profile=profile, tail=tail))
    if result.get("returncode") != 0:
        return []
    return _chat_items(json_payload(result))


def _target_for_connection(
    payload: Mapping[str, Any],
    *,
    app_ref: str,
    chat_id: str,
) -> tuple[str, dict[str, Any]] | None:
    targets = payload.get("targets")
    if not isinstance(targets, Mapping):
        return None
    for name, target in targets.items():
        if not isinstance(target, Mapping):
            continue
        channel = target.get("channel")
        identity = target.get("identity")
        if (
            isinstance(channel, Mapping)
            and isinstance(identity, Mapping)
            and str(channel.get("chat_id") or "") == chat_id
            and str(identity.get("sender_profile") or "") == app_ref
        ):
            return str(name), dict(target)
    return None


def _target_name(app_ref: str, chat_id: str) -> str:
    prefix = re.sub(r"[^a-z0-9._-]+", "-", app_ref.casefold()).strip("-._") or "lark"
    digest = hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:10]
    return f"{prefix[:48]}-{digest}"


def connect_lark_goal_topic(
    *,
    registry: Mapping[str, Any],
    goal_id: str,
    target_path: Path,
    binding_path: Path,
    app_ref: str,
    chat_id: str,
    chat_name: str,
    incoming_mode: str = "mentions",
    execute: bool = True,
    runner: CommandRunner = default_subprocess_runner,
    cli_bin: str = DEFAULT_CLI_BIN,
) -> dict[str, Any]:
    goal = goal_from_registry(registry, goal_id)
    profile = _profile_ref(app_ref)
    safe_chat_id = str(chat_id or "").strip()
    if not CHAT_ID_PATTERN.fullmatch(safe_chat_id):
        raise ValueError("Lark group chat id must begin with oc_")
    if incoming_mode not in INCOMING_MODES:
        raise ValueError("incoming_mode must be mentions or all")
    identity = _app_identity(app_ref=profile, runner=runner, cli_bin=cli_bin)
    if not identity or not identity.get("ready"):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="connect_topic",
            execute=execute,
            status="blocked",
            blocker="lark_app_not_ready",
            public_summary="the selected Lark App is not ready",
        )
    if not execute:
        return operation_packet(
            ok=True,
            goal_id=goal_id,
            operation="connect_topic",
            execute=False,
            status="preview_ready",
            public_summary="previewed one Goal Topic connection",
            details={
                "app_ref": profile,
                "chat_name": public_safe_compact_text(chat_name, limit=60),
                "topic_name": goal_objective(goal),
                "incoming_mode": incoming_mode,
                "reply_mode": "topic_reply",
            },
        )
    if not chat_verified(
        runner=runner,
        cli_bin=cli_bin,
        profile=profile,
        identity="bot",
        chat_id=safe_chat_id,
    ):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="connect_topic",
            execute=True,
            status="blocked",
            blocker="channel_membership_unverified",
            public_summary="the selected Lark App cannot access this group",
        )
    if not bot_membership_verified(
        runner=runner,
        cli_bin=cli_bin,
        profile=profile,
        chat_id=safe_chat_id,
        app_id=str(identity["app_id"]),
    ):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="connect_topic",
            execute=True,
            status="blocked",
            blocker="bot_not_in_chat",
            public_summary="invite the selected Lark App to the group and retry",
        )

    target_payload = read_goal_channel_targets(target_path)
    matched = _target_for_connection(
        target_payload,
        app_ref=profile,
        chat_id=safe_chat_id,
    )
    if matched is None:
        target_name = _target_name(profile, safe_chat_id)
        added = add_lark_goal_channel_target(
            target_path=target_path,
            target_name=target_name,
            chat_id=safe_chat_id,
            chat_name=chat_name,
            identity_mode="local_user",
            sender_profile=profile,
            bot_app_id=str(identity["app_id"]),
            bot_display_name=str(identity["label"]),
            cli_bin=cli_bin,
            execute=True,
        )
        if not added.get("ok"):
            return added
    else:
        target_name = matched[0]

    objective = goal_objective(goal)
    topic_text = f"LoopX Goal Topic: {objective}\nGoal ID: {goal_id}"
    key = provider_idempotency_key(
        semantic_key(goal_id, "lark", "goal_topic", profile, safe_chat_id, topic_text)
    )
    sent = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "+messages-send",
                "--chat-id",
                safe_chat_id,
                "--text",
                topic_text,
                "--idempotency-key",
                key,
                "--as",
                "bot",
                "--format",
                "json",
            ],
        ),
    )
    root_message_id = find_first_string(
        json_payload(sent),
        {"message_id"},
        MESSAGE_ID_PATTERN,
    )
    if sent.get("returncode") != 0 or not root_message_id:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="connect_topic",
            execute=True,
            status="failed",
            blocker="provider_api_failed",
            public_summary="the Goal Topic root message could not be sent",
        )
    verified = message_readback_verified(
        runner=runner,
        cli_bin=cli_bin,
        profile=profile,
        identity="bot",
        message_id=root_message_id,
        expected_text=topic_text,
    )
    if not verified:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="connect_topic",
            execute=True,
            status="sent_unverified",
            blocker="readback_mismatch",
            public_summary="the Goal Topic was sent but could not be verified",
            external_write_performed=True,
        )

    payload = read_goal_channel_binding(binding_path)
    existing = binding_for_goal(payload, goal_id) or {}
    receipts = dict(existing.get("receipts") or {})
    receipts[semantic_key(goal_id, "lark", "goal_topic_receipt", root_message_id)] = {
        "kind": "goal_topic",
        "message_id": root_message_id,
        "verified_at": now_iso(),
    }
    save_goal_binding(
        binding_path=binding_path,
        payload=payload,
        goal_id=goal_id,
        binding={
            **existing,
            "goal_id": goal_id,
            "provider": "lark",
            "enabled": True,
            "target_ref": target_name,
            "channel": {"pinned_message_id": root_message_id},
            "topic": {
                "name": objective,
                "root_message_id": root_message_id,
                "created_automatically": True,
            },
            "routing": {
                "incoming_mode": incoming_mode,
                "reply_mode": "topic_reply",
            },
            "automation": dict(existing.get("automation") or {}),
            "receipts": receipts,
        },
    )
    return operation_packet(
        ok=True,
        goal_id=goal_id,
        operation="connect_topic",
        execute=True,
        status="connected",
        public_summary="connected one Goal to a dedicated Lark topic",
        external_write_performed=True,
        readback_verified=True,
        idempotency_key=key,
        details={
            "app_ref": profile,
            "chat_name": public_safe_compact_text(chat_name, limit=60),
            "target_ref": target_name,
            "topic_name": objective,
            "incoming_mode": incoming_mode,
            "reply_mode": "topic_reply",
        },
    )


def list_lark_connections(
    *,
    registry: Mapping[str, Any],
    target_path: Path,
    binding_paths: Mapping[str, Path],
) -> list[dict[str, Any]]:
    target_payload = read_goal_channel_targets(target_path)
    rows: list[dict[str, Any]] = []
    for goal_id, binding_path in binding_paths.items():
        try:
            goal = goal_from_registry(registry, goal_id)
            binding = binding_for_goal(read_goal_channel_binding(binding_path), goal_id)
        except (OSError, ValueError):
            continue
        if not binding:
            continue
        target_ref = str(binding.get("target_ref") or "")
        target = goal_channel_target_for_name(target_payload, target_ref)
        if target is None:
            continue
        channel = target.get("channel") if isinstance(target.get("channel"), Mapping) else {}
        identity = target.get("identity") if isinstance(target.get("identity"), Mapping) else {}
        topic = binding.get("topic") if isinstance(binding.get("topic"), Mapping) else {}
        routing = binding.get("routing") if isinstance(binding.get("routing"), Mapping) else {}
        legacy_root = (
            binding.get("channel", {}).get("pinned_message_id")
            if isinstance(binding.get("channel"), Mapping)
            else None
        )
        rows.append(
            {
                "app_ref": str(identity.get("sender_profile") or "default"),
                "app_label": public_safe_compact_text(
                    identity.get("bot_display_name") or identity.get("sender_profile") or "Lark App",
                    limit=60,
                ),
                "chat_name": public_safe_compact_text(channel.get("chat_name") or target_ref, limit=60),
                "enabled": binding.get("enabled") is True,
                "goal_id": goal_id,
                "goal_title": goal_objective(goal),
                "incoming_mode": str(routing.get("incoming_mode") or "mentions"),
                "reply_mode": str(routing.get("reply_mode") or "topic_reply"),
                "target_ref": target_ref,
                "topic_name": public_safe_compact_text(topic.get("name") or goal_objective(goal), limit=120),
                "topic_setup_required": not bool(topic.get("root_message_id") or legacy_root),
            }
        )
    return sorted(rows, key=lambda row: (str(row["app_label"]).casefold(), str(row["goal_title"]).casefold()))


def route_lark_topic_event(
    *,
    target_payload: Mapping[str, Any],
    binding_payloads: Mapping[str, Mapping[str, Any]],
    event: Mapping[str, Any],
) -> dict[str, str] | None:
    chat_id = str(event.get("chat_id") or "")
    root_id = str(event.get("root_id") or "")
    message_id = str(event.get("message_id") or "")
    if not (
        CHAT_ID_PATTERN.fullmatch(chat_id)
        and MESSAGE_ID_PATTERN.fullmatch(root_id)
        and MESSAGE_ID_PATTERN.fullmatch(message_id)
    ):
        return None
    for goal_id, payload in binding_payloads.items():
        binding = binding_for_goal(payload, goal_id)
        if not binding or binding.get("enabled") is not True:
            continue
        target_ref = str(binding.get("target_ref") or "")
        target = goal_channel_target_for_name(target_payload, target_ref)
        if target is None:
            continue
        channel = target.get("channel") if isinstance(target.get("channel"), Mapping) else {}
        identity = target.get("identity") if isinstance(target.get("identity"), Mapping) else {}
        topic = binding.get("topic") if isinstance(binding.get("topic"), Mapping) else {}
        binding_channel = binding.get("channel") if isinstance(binding.get("channel"), Mapping) else {}
        topic_root = str(topic.get("root_message_id") or binding_channel.get("pinned_message_id") or "")
        routing = binding.get("routing") if isinstance(binding.get("routing"), Mapping) else {}
        incoming_mode = str(routing.get("incoming_mode") or "mentions")
        if str(channel.get("chat_id") or "") != chat_id or topic_root != root_id:
            continue
        if str(event.get("sender_id") or "") == str(identity.get("bot_app_id") or ""):
            return None
        bot_display_name = " ".join(str(identity.get("bot_display_name") or "").split())
        provider_mentions = event.get("mentions")
        provider_mentioned = bool(
            bot_display_name
            and isinstance(provider_mentions, list)
            and any(
                isinstance(mention, Mapping)
                and " ".join(str(mention.get("name") or "").split()).casefold()
                == bot_display_name.casefold()
                for mention in provider_mentions
            )
        )
        rendered_content = " ".join(str(event.get("content") or "").split())
        rendered_mentioned = bool(
            bot_display_name
            and "@" in rendered_content
            and bot_display_name.casefold() in rendered_content.casefold()
        )
        addressed = bool(
            event.get("mentioned") is True
            or provider_mentioned
            or rendered_mentioned
            or (
                event.get("reply_context_verified") is True
                and event.get("reply_to_bot") is True
            )
        )
        if incoming_mode == "mentions" and not addressed:
            return None
        return {
            "app_ref": str(identity.get("sender_profile") or "default"),
            "goal_id": goal_id,
            "message_id": message_id,
            "reply_mode": str(routing.get("reply_mode") or "topic_reply"),
            "target_ref": target_ref,
            "topic_root_message_id": topic_root,
        }
    return None


def reply_lark_goal_topic(
    *,
    route: Mapping[str, Any],
    text: str,
    runner: CommandRunner = default_subprocess_runner,
    cli_bin: str = DEFAULT_CLI_BIN,
) -> dict[str, Any]:
    profile = _profile_ref(route.get("app_ref"))
    message_id = str(route.get("message_id") or "")
    reply_text = public_safe_compact_text(text, limit=1200)
    if not MESSAGE_ID_PATTERN.fullmatch(message_id) or not reply_text:
        raise ValueError("a valid source message and non-empty reply are required")
    key = provider_idempotency_key(
        semantic_key(str(route.get("goal_id") or ""), "lark", "topic_reply", message_id, reply_text)
    )
    result = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "+messages-reply",
                "--message-id",
                message_id,
                "--text",
                reply_text,
                "--reply-in-thread",
                "--idempotency-key",
                key,
                "--as",
                "bot",
                "--format",
                "json",
            ],
        ),
    )
    reply_id = find_first_string(json_payload(result), {"message_id"}, MESSAGE_ID_PATTERN)
    return operation_packet(
        ok=bool(result.get("returncode") == 0 and reply_id),
        goal_id=str(route.get("goal_id") or "") or None,
        operation="topic_reply",
        execute=True,
        status="sent" if result.get("returncode") == 0 and reply_id else "failed",
        blocker=None if result.get("returncode") == 0 and reply_id else "provider_api_failed",
        public_summary=(
            "replied in the bound Goal topic"
            if result.get("returncode") == 0 and reply_id
            else "the Goal topic reply could not be sent"
        ),
        external_write_performed=bool(result.get("returncode") == 0 and reply_id),
        idempotency_key=key,
    )


def disconnect_lark_goal_topic(*, binding_path: Path, goal_id: str) -> dict[str, Any]:
    payload = read_goal_channel_binding(binding_path)
    bindings = payload.get("bindings")
    mutable = dict(bindings) if isinstance(bindings, Mapping) else {}
    existed = mutable.pop(goal_id, None) is not None
    if existed:
        write_goal_channel_binding(
            binding_path,
            {"schema_version": payload["schema_version"], "bindings": mutable},
        )
    return operation_packet(
        ok=True,
        goal_id=goal_id,
        operation="disconnect_topic",
        execute=True,
        status="disconnected" if existed else "already_disconnected",
        public_summary=(
            "disconnected the selected Goal topic"
            if existed
            else "the selected Goal has no Lark topic connection"
        ),
        readback_verified=binding_for_goal(read_goal_channel_binding(binding_path), goal_id) is None,
    )

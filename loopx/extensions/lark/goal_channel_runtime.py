from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .goal_channel_contracts import (
    DEFAULT_GATE_COOLDOWN_SECONDS,
    binding_for_goal,
    clear_human_gate_auto_notify_marker,
    gate_message,
    goal_from_registry,
    goal_objective,
    human_gate_auto_notify_enabled,
    human_gate_auto_notify_marker_path,
    now_iso,
    operation_packet,
    parse_time,
    provider_idempotency_key,
    quota_human_gate_identity,
    quota_selects_human_gate,
    read_goal_channel_binding,
    save_goal_binding,
    semantic_key,
    write_human_gate_auto_notify_marker,
)
from .goal_channel_transport import (
    APP_ID_PATTERN,
    CHAT_ID_PATTERN,
    MESSAGE_ID_PATTERN,
    auth_verified,
    call,
    chat_verified,
    find_first_string,
    json_payload,
    lark_args,
    message_readback_verified,
    payload_contains_exact,
    pin_readback_verified,
    verified_app_id,
)
from .presentation.kanban import (
    DEFAULT_CLI_BIN,
    CommandRunner,
    LarkKanbanConfig,
    build_record_list_command,
    default_lark_kanban_config_path,
    default_subprocess_runner,
    lark_kanban_config_from_payload,
    lark_kanban_doctor,
    read_lark_kanban_local_config,
    sync_loopx_todos_to_lark_kanban,
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def configure_lark_goal_channel_automation(
    *,
    registry: Mapping[str, Any],
    goal_id: str,
    binding_path: Path,
    human_gate_auto_notify: bool,
    execute: bool = False,
) -> dict[str, Any]:
    goal_from_registry(registry, goal_id)
    payload = read_goal_channel_binding(binding_path)
    binding = binding_for_goal(payload, goal_id)
    if binding is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="configure",
            execute=execute,
            status="blocked",
            blocker="channel_binding_missing",
            public_summary="configure the Goal Channel before enabling automation",
        )
    if human_gate_auto_notify and binding.get("enabled") is not True:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="configure",
            execute=execute,
            status="blocked",
            blocker="channel_binding_incomplete",
            public_summary="complete Goal Channel setup before enabling automation",
        )
    current = human_gate_auto_notify_enabled(binding)
    changed = current != human_gate_auto_notify
    marker_path = human_gate_auto_notify_marker_path(binding_path, goal_id)
    if execute and changed:
        mutable_binding = dict(binding)
        automation = _mapping(binding.get("automation"))
        automation["human_gate_auto_notify_enabled"] = human_gate_auto_notify
        mutable_binding["automation"] = automation
        save_goal_binding(
            binding_path=binding_path,
            payload=payload,
            goal_id=goal_id,
            binding=mutable_binding,
        )
    if execute:
        if human_gate_auto_notify:
            write_human_gate_auto_notify_marker(marker_path)
        else:
            clear_human_gate_auto_notify_marker(marker_path)
    return operation_packet(
        ok=True,
        goal_id=goal_id,
        operation="configure",
        execute=execute,
        status="configured" if execute else "preview_ready",
        public_summary=(
            "enabled automatic human gate notifications for this Goal Channel"
            if execute and human_gate_auto_notify
            else "disabled automatic human gate notifications for this Goal Channel"
            if execute
            else "previewed the Goal Channel automation change"
        ),
        readback_verified=bool(
            execute
            and human_gate_auto_notify_enabled(
                binding_for_goal(read_goal_channel_binding(binding_path), goal_id)
            )
            == human_gate_auto_notify
        ),
        details={
            "changed": changed,
            "human_gate_auto_notify_enabled": human_gate_auto_notify,
        },
    )


def auto_notify_lark_goal_channel_gate(
    *,
    registry: Mapping[str, Any],
    goal_id: str,
    binding_path: Path,
    quota_packet: Mapping[str, Any],
    provider_target: Mapping[str, Any] | None = None,
    external_sink_delivery_authorized: bool,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    goal_from_registry(registry, goal_id)
    payload = read_goal_channel_binding(binding_path)
    binding = binding_for_goal(
        payload,
        goal_id,
        provider_target=provider_target,
    )
    enabled = human_gate_auto_notify_enabled(binding)
    result: dict[str, Any] = {
        "schema_version": "loopx_goal_channel_gate_auto_delivery_v0",
        "ok": True,
        "enabled": enabled,
        "status": "not_configured" if binding is None else "disabled",
        "external_write_performed": False,
        "readback_verified": False,
        "delivery_postcondition": {
            "satisfied": True,
            "blocks_delivery": False,
        },
    }
    if not enabled:
        return result
    if not external_sink_delivery_authorized:
        result["status"] = "external_sink_suppressed"
        return result

    notification = notify_lark_goal_channel_gate(
        registry=registry,
        goal_id=goal_id,
        binding_path=binding_path,
        quota_packet=quota_packet,
        provider_target=provider_target,
        execute=True,
        runner=runner,
    )
    result["notification"] = notification
    blocker = str(notification.get("blocker") or "")
    result["status"] = (
        "not_selected"
        if blocker == "state_transition_rejected"
        else "cooldown"
        if blocker == "notification_cooldown_active"
        else str(notification.get("status") or "failed")
    )
    result["external_write_performed"] = bool(
        notification.get("external_write_performed")
    )
    result["readback_verified"] = bool(notification.get("readback_verified"))
    safe_noop = blocker in {
        "notification_cooldown_active",
        "state_transition_rejected",
    }
    satisfied = bool(notification.get("ok")) or safe_noop
    result["ok"] = satisfied
    result["delivery_postcondition"] = {
        "satisfied": satisfied,
        "blocks_delivery": not satisfied,
    }
    return result


def doctor_lark_goal_channel(
    *,
    registry: Mapping[str, Any],
    registry_path: Path,
    goal_id: str,
    binding_path: Path,
    provider_target: Mapping[str, Any] | None = None,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    goal_from_registry(registry, goal_id)
    payload = read_goal_channel_binding(binding_path)
    binding = binding_for_goal(payload, goal_id, provider_target=provider_target)
    if binding is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="doctor",
            execute=False,
            status="blocked",
            blocker="channel_binding_missing",
            public_summary="no local-private Goal Channel binding exists",
        )
    binding_enabled = binding.get("enabled") is True
    channel = _mapping(binding.get("channel"))
    identity_config = _mapping(binding.get("identity"))
    kanban = _mapping(binding.get("kanban"))
    chat_id = str(channel.get("chat_id") or "")
    pinned_message_id = str(channel.get("pinned_message_id") or "")
    cli_bin = str(identity_config.get("cli_bin") or DEFAULT_CLI_BIN)
    identity = str(identity_config.get("sender_identity") or "")
    profile = str(identity_config.get("sender_profile") or "") or None
    configured_app_id = str(identity_config.get("bot_app_id") or "")
    auth_ok = bool(
        identity == "bot"
        and APP_ID_PATTERN.fullmatch(configured_app_id)
        and auth_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            expected_bot_name=str(identity_config.get("bot_display_name") or "") or None,
        )
        and verified_app_id(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
        )
        == configured_app_id
    )
    channel_ok = bool(
        auth_ok
        and CHAT_ID_PATTERN.fullmatch(chat_id)
        and chat_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            chat_id=chat_id,
        )
    )
    control_message_ok = bool(
        channel_ok
        and MESSAGE_ID_PATTERN.fullmatch(pinned_message_id)
        and message_readback_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            message_id=pinned_message_id,
            expected_text=f"LoopX Goal: {goal_id}",
        )
        and pin_readback_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            chat_id=chat_id,
            message_id=pinned_message_id,
        )
    )
    kanban_path = Path(
        str(kanban.get("config_path") or default_lark_kanban_config_path(registry_path))
    ).expanduser()
    board_payload = read_lark_kanban_local_config(kanban_path)
    board_config = lark_kanban_config_from_payload(board_payload)
    kanban_result = lark_kanban_doctor(
        config_path=kanban_path,
        cli_bin=board_config.cli_bin if board_config else cli_bin,
        identity=board_config.identity if board_config else "user",
        require_board=True,
        runner=runner,
    )
    blocker = None
    if not binding_enabled:
        blocker = "channel_binding_incomplete"
    elif not auth_ok:
        blocker = "provider_identity_unverified"
    elif not channel_ok:
        blocker = "channel_membership_unverified"
    elif not control_message_ok:
        blocker = "readback_mismatch"
    elif not kanban_result.get("ok"):
        blocker = "kanban_binding_missing"
    ok = blocker is None
    return operation_packet(
        ok=ok,
        goal_id=goal_id,
        operation="doctor",
        execute=False,
        status="ready" if ok else "blocked",
        blocker=blocker,
        public_summary=(
            "the Lark Goal Channel binding is ready"
            if ok
            else "the Lark Goal Channel binding needs attention"
        ),
        readback_verified=ok,
        details={
            "binding_present": True,
            "binding_enabled": binding_enabled,
            "identity_verified": auth_ok,
            "channel_membership_verified": channel_ok,
            "control_message_verified": control_message_ok,
            "kanban_ready": bool(kanban_result.get("ok")),
        },
    )


def sync_lark_goal_channel(
    *,
    registry: Mapping[str, Any],
    registry_path: Path,
    goal_id: str,
    binding_path: Path,
    provider_target: Mapping[str, Any] | None = None,
    agent_id: str | None = None,
    execute: bool = False,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    goal_from_registry(registry, goal_id)
    payload = read_goal_channel_binding(binding_path)
    binding = binding_for_goal(payload, goal_id, provider_target=provider_target)
    if binding is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="sync",
            execute=execute,
            status="blocked",
            blocker="channel_binding_missing",
            public_summary="configure the Goal Channel before syncing it",
        )
    if binding.get("enabled") is not True:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="sync",
            execute=execute,
            status="blocked",
            blocker="channel_binding_incomplete",
            public_summary="complete Goal Channel setup before syncing it",
        )
    kanban = _mapping(binding.get("kanban"))
    kanban_path = Path(str(kanban.get("config_path") or "")).expanduser()
    board_payload = read_lark_kanban_local_config(kanban_path)
    config = lark_kanban_config_from_payload(board_payload)
    if config is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="sync",
            execute=execute,
            status="blocked",
            blocker="kanban_binding_missing",
            public_summary="the Goal Channel Kanban binding is missing",
        )
    result = sync_loopx_todos_to_lark_kanban(
        config,
        registry_path=registry_path,
        goal_id=goal_id,
        agent_id=agent_id,
        config_path=kanban_path,
        execute=execute,
        runner=runner,
    )
    ok = bool(result.get("ok"))
    provider_write_ok = ok
    successful_write_count = int(result.get("successful_write_count") or 0)
    external_write_performed = bool(result.get("external_write_performed"))
    records = [
        record for record in result.get("records") or [] if isinstance(record, Mapping)
    ]
    readback_verified = False
    if execute and ok:
        readback_config = LarkKanbanConfig(
            base_token=config.base_token,
            table_id=config.table_id,
            view_id=None,
            cli_bin=config.cli_bin,
            identity=config.identity,
        )
        readback = call(runner, build_record_list_command(readback_config))
        expected_record_ids = {
            str(record.get("record_id") or "")
            for record in records
            if str(record.get("record_id") or "")
        }
        readback_payload = json_payload(readback)
        readback_verified = bool(
            readback.get("returncode") == 0
            and len(expected_record_ids) == len(records)
            and all(
                payload_contains_exact(readback_payload, record_id)
                for record_id in expected_record_ids
            )
        )
        if not readback_verified:
            ok = False
    return operation_packet(
        ok=ok,
        goal_id=goal_id,
        operation="sync",
        execute=execute,
        status="synced" if execute and ok else "preview_ready" if ok else "failed",
        blocker=(
            None
            if ok
            else "readback_mismatch"
            if execute and provider_write_ok
            else "provider_api_failed"
        ),
        public_summary=(
            "synced accepted LoopX todos to the configured Goal Channel Kanban"
            if execute and ok
            else "previewed the Goal Channel Kanban sync"
            if ok
            else "the Goal Channel Kanban sync failed readback"
            if execute and provider_write_ok
            else "the Goal Channel Kanban sync failed after partial provider writes"
            if execute and external_write_performed
            else "the Goal Channel Kanban sync failed"
        ),
        external_write_performed=external_write_performed,
        readback_verified=readback_verified,
        details={
            "kanban_ready": True,
            "todo_count": int(result.get("todo_count") or 0),
            "record_count": len(records),
            "successful_write_count": successful_write_count,
        },
    )


def notify_lark_goal_channel_gate(
    *,
    registry: Mapping[str, Any],
    goal_id: str,
    binding_path: Path,
    quota_packet: Mapping[str, Any],
    provider_target: Mapping[str, Any] | None = None,
    cooldown_seconds: int = DEFAULT_GATE_COOLDOWN_SECONDS,
    execute: bool = False,
    runner: CommandRunner = default_subprocess_runner,
) -> dict[str, Any]:
    goal = goal_from_registry(registry, goal_id)
    payload = read_goal_channel_binding(binding_path)
    raw_binding = binding_for_goal(payload, goal_id)
    if raw_binding is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=execute,
            status="blocked",
            blocker="channel_binding_missing",
            public_summary="configure the Goal Channel before notifying a human gate",
        )
    target_ref = str(raw_binding.get("target_ref") or "")
    if target_ref and provider_target is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=execute,
            status="blocked",
            blocker="provider_target_missing",
            public_summary="configure the referenced shared provider target first",
        )
    binding = binding_for_goal(payload, goal_id, provider_target=provider_target)
    if binding is None:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=execute,
            status="blocked",
            blocker="channel_binding_incomplete",
            public_summary="complete Goal Channel setup before notifying a human gate",
        )
    if binding.get("enabled") is not True:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=execute,
            status="blocked",
            blocker="channel_binding_incomplete",
            public_summary="complete Goal Channel setup before notifying a human gate",
        )
    if not quota_selects_human_gate(quota_packet):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=execute,
            status="rejected",
            blocker="state_transition_rejected",
            public_summary="LoopX has not selected a human gate notification",
        )
    channel = _mapping(binding.get("channel"))
    identity_config = _mapping(binding.get("identity"))
    kanban = _mapping(binding.get("kanban"))
    chat_id = str(channel.get("chat_id") or "")
    cli_bin = str(identity_config.get("cli_bin") or DEFAULT_CLI_BIN)
    identity = str(identity_config.get("sender_identity") or "")
    profile = str(identity_config.get("sender_profile") or "") or None
    message, question = gate_message(
        goal_id=goal_id,
        objective=goal_objective(goal),
        quota_packet=quota_packet,
        kanban_url=str(kanban.get("base_url") or ""),
    )
    gate_identity = quota_human_gate_identity(quota_packet)
    key = semantic_key(
        goal_id,
        "lark",
        "notify_gate",
        gate_identity,
        question,
        chat_id,
    )
    receipts = _mapping(binding.get("receipts"))
    existing_receipt = _mapping(receipts.get(key))
    if existing_receipt:
        existing_message_id = str(existing_receipt.get("message_id") or "")
        existing_verified = bool(
            identity == "bot"
            and MESSAGE_ID_PATTERN.fullmatch(existing_message_id)
            and message_readback_verified(
                runner=runner,
                cli_bin=cli_bin,
                profile=profile,
                identity="bot",
                message_id=existing_message_id,
                expected_text=message,
            )
        )
        if existing_verified:
            return operation_packet(
                ok=True,
                goal_id=goal_id,
                operation="notify_gate",
                execute=execute,
                status="already_sent",
                public_summary="the same human gate notification was already sent",
                readback_verified=True,
                idempotency_key=key,
                receipt_id=f"receipt_{key.removeprefix('sha256:')[:16]}",
            )
        receipts = {
            receipt_key: receipt
            for receipt_key, receipt in receipts.items()
            if receipt_key != key
        }
    same_gate_receipts = [
        receipt
        for receipt in receipts.values()
        if isinstance(receipt, Mapping)
        and receipt.get("kind") == "gate_notification"
        and str(receipt.get("gate_identity") or "") == gate_identity
    ]
    cooldown = quota_packet.get("user_gate_notification_cooldown")
    if (
        same_gate_receipts
        and isinstance(cooldown, Mapping)
        and cooldown.get("notification_suppressed") is True
    ):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=execute,
            status="suppressed",
            blocker="notification_cooldown_active",
            public_summary="the current human gate notification is in cooldown",
        )
    latest_gate_time = max(
        (
            parsed
            for receipt in same_gate_receipts
            if (parsed := parse_time(receipt.get("verified_at"))) is not None
        ),
        default=None,
    )
    if latest_gate_time is not None:
        elapsed = (datetime.now(timezone.utc) - latest_gate_time).total_seconds()
        if elapsed < max(0, cooldown_seconds):
            return operation_packet(
                ok=False,
                goal_id=goal_id,
                operation="notify_gate",
                execute=execute,
                status="suppressed",
                blocker="notification_cooldown_active",
                public_summary="a recent human gate notification is still in cooldown",
                idempotency_key=key,
            )
    if not execute:
        return operation_packet(
            ok=True,
            goal_id=goal_id,
            operation="notify_gate",
            execute=False,
            status="preview_ready",
            public_summary="previewed one bounded human gate notification",
            idempotency_key=key,
            receipt_id=f"receipt_{key.removeprefix('sha256:')[:16]}",
        )
    configured_app_id = str(identity_config.get("bot_app_id") or "")
    if not (
        identity == "bot"
        and APP_ID_PATTERN.fullmatch(configured_app_id)
        and auth_verified(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
            identity="bot",
            expected_bot_name=str(identity_config.get("bot_display_name") or "") or None,
        )
        and verified_app_id(
            runner=runner,
            cli_bin=cli_bin,
            profile=profile,
        )
        == configured_app_id
    ):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=True,
            status="gate_required",
            blocker="provider_identity_unverified",
            public_summary="the configured Lark sender identity could not be verified",
            idempotency_key=key,
        )
    if not CHAT_ID_PATTERN.fullmatch(chat_id) or not chat_verified(
        runner=runner,
        cli_bin=cli_bin,
        profile=profile,
        identity="bot",
        chat_id=chat_id,
    ):
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=True,
            status="gate_required",
            blocker="channel_membership_unverified",
            public_summary="the configured Lark channel is not reachable by the sender",
            idempotency_key=key,
        )
    send = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "+messages-send",
                "--chat-id",
                chat_id,
                "--text",
                message,
                "--idempotency-key",
                provider_idempotency_key(key),
                "--as",
                "bot",
                "--format",
                "json",
            ],
        ),
    )
    message_id = (
        find_first_string(
            json_payload(send),
            {"message_id"},
            MESSAGE_ID_PATTERN,
        )
        or ""
    )
    if send.get("returncode") != 0 or not message_id:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=True,
            status="failed",
            blocker="provider_api_failed",
            public_summary="the human gate notification could not be sent",
            idempotency_key=key,
        )
    verified = message_readback_verified(
        runner=runner,
        cli_bin=cli_bin,
        profile=profile,
        identity="bot",
        message_id=message_id,
        expected_text=message,
    )
    if not verified:
        return operation_packet(
            ok=False,
            goal_id=goal_id,
            operation="notify_gate",
            execute=True,
            status="sent_unverified",
            blocker="readback_mismatch",
            public_summary="the human gate notification was sent but not verified",
            external_write_performed=True,
            idempotency_key=key,
        )
    mutable_receipts = dict(receipts)
    mutable_receipts[key] = {
        "kind": "gate_notification",
        "gate_identity": gate_identity,
        "message_id": message_id,
        "verified_at": now_iso(),
    }
    mutable_binding = dict(raw_binding)
    mutable_binding["receipts"] = mutable_receipts
    save_goal_binding(
        binding_path=binding_path,
        payload=payload,
        goal_id=goal_id,
        binding=mutable_binding,
    )
    return operation_packet(
        ok=True,
        goal_id=goal_id,
        operation="notify_gate",
        execute=True,
        status="sent_verified",
        public_summary="sent one verified human gate notification",
        external_write_performed=True,
        readback_verified=True,
        idempotency_key=key,
        receipt_id=f"receipt_{key.removeprefix('sha256:')[:16]}",
    )

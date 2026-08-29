from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from loopx.extensions.lark import inbox_reactions as inbox_reactions_module
from loopx.extensions.lark.event_inbox import load_lark_event_inbox_config
from loopx.extensions.lark.inbox_reactions import (
    complete_lark_event_inbox_reactions,
    ensure_lark_event_inbox_received_reaction,
    lark_inbox_reaction_receipts,
    mark_lark_event_inbox_processing,
    record_lark_inbox_reaction,
)
from loopx.extensions.lark.inbox_reply import (
    reply_lark_event_inbox,
    send_lark_inbox_message,
)


def _fixture(tmp_path: Path, *, lifecycle: bool = True) -> tuple[Path, Path, Path]:
    inbox = tmp_path / ".loopx" / "inbox" / "feedback"
    inbox.mkdir(parents=True)
    config = tmp_path / ".loopx" / "config" / "lark-inbox.json"
    config.parent.mkdir(parents=True)
    reply = {
        "enabled": True,
        "sender_profile": "project-review-bot",
        "sender_identity": "bot",
        "bot_display_name": "Project Review Bot",
        "chat_id": "oc_project_review",
    }
    if lifecycle:
        reply.update(
            {
                "received_reaction_emoji": "Get",
                "processing_reaction_emoji": "OnIt",
            }
        )
    else:
        reply["received_reaction_emoji"] = ""
    config.write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_config_v0",
                "enabled": True,
                "inbox_dir": ".loopx/inbox/feedback",
                "capture_scope": "configured_chat_all",
                "reply": reply,
            }
        ),
        encoding="utf-8",
    )
    message_id = "om_reaction_fixture"
    (inbox / f"{message_id}.json").write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_event_v0",
                "event_id": "evt-reaction-fixture",
                "message_id": message_id,
                "create_time": "2026-08-11T00:00:00Z",
                "content": "@Project Review Bot please handle this",
            }
        ),
        encoding="utf-8",
    )
    return config, inbox, tmp_path


class ReactionRunner:
    def __init__(
        self,
        *,
        fail_delete: bool = False,
        reaction_still_present: bool = True,
    ) -> None:
        self.calls: list[list[str]] = []
        self.fail_delete = fail_delete
        self.reaction_still_present = reaction_still_present

    def __call__(self, args: Sequence[str]) -> dict[str, Any]:
        call = list(args)
        self.calls.append(call)
        if "create" in call:
            emoji_payload = json.loads(call[call.index("--data") + 1])
            emoji_type = emoji_payload["reaction_type"]["emoji_type"]
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "ok": True,
                        "data": {"reaction_id": f"reaction_{emoji_type}"},
                    }
                ),
                "stderr": "",
            }
        if "delete" in call:
            return {
                "returncode": int(self.fail_delete),
                "stdout": json.dumps({"ok": not self.fail_delete}),
                "stderr": "",
            }
        if "list" in call:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "items": (
                                [{"reaction_id": "reaction_Get"}]
                                if self.reaction_still_present
                                else []
                            )
                        },
                    }
                ),
                "stderr": "",
            }
        raise AssertionError(call)


def test_received_reaction_boundary_acknowledges_pending_message_once(
    tmp_path: Path,
) -> None:
    config, inbox, project = _fixture(tmp_path)
    created: list[tuple[str, str]] = []

    def create(message_id: str, emoji_type: str) -> str:
        created.append((message_id, emoji_type))
        return "reaction_Get"

    def delete(_message_id: str, _reaction_id: str) -> bool:
        return True

    event = {"message_id": "om_reaction_fixture"}
    first = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event=event,
        create_reaction=create,
        delete_reaction=delete,
    )
    duplicate = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event=event,
        create_reaction=create,
        delete_reaction=delete,
    )

    assert first["status"] == "received"
    assert duplicate["status"] == "already_received"
    assert created == [("om_reaction_fixture", "Get")]
    assert (
        lark_inbox_reaction_receipts(
            inbox=inbox,
            message_id="om_reaction_fixture",
        )["received"]["reaction_id"]
        == "reaction_Get"
    )


def test_received_reaction_boundary_is_independent_of_attention_kind(
    tmp_path: Path,
) -> None:
    config, _inbox, project = _fixture(tmp_path)
    created: list[tuple[str, str]] = []

    result = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event={
            "message_id": "om_reaction_fixture",
            "mentions": [{"name": "Another Bot"}],
        },
        create_reaction=lambda message_id, emoji_type: (
            created.append((message_id, emoji_type)) or "reaction_Get"
        ),
        delete_reaction=lambda _message_id, _reaction_id: True,
    )

    assert result["status"] == "received"
    assert result["captured_pending"] is True
    assert created == [("om_reaction_fixture", "Get")]


def test_received_reaction_boundary_does_not_react_after_settlement(
    tmp_path: Path,
) -> None:
    config, inbox, project = _fixture(tmp_path)
    (inbox / "processed.json").write_text(
        json.dumps(
            {
                "schema_version": "lark_event_inbox_processed_v0",
                "message_ids": ["om_reaction_fixture"],
            }
        ),
        encoding="utf-8",
    )
    created: list[tuple[str, str]] = []

    result = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event={
            "message_id": "om_reaction_fixture",
            "mentions": [{"name": "Project Review Bot"}],
        },
        create_reaction=lambda message_id, emoji_type: (
            created.append((message_id, emoji_type)) or "reaction_Get"
        ),
        delete_reaction=lambda _message_id, _reaction_id: True,
    )

    assert result["status"] == "already_settled"
    assert result["external_writes_performed"] is False
    assert created == []


def test_received_reaction_receipt_failure_reports_provider_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _inbox, project = _fixture(tmp_path)
    real_record = inbox_reactions_module.record_lark_inbox_reaction
    monkeypatch.setattr(
        "loopx.extensions.lark.inbox_reactions.record_lark_inbox_reaction",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("fixture receipt failure")),
    )

    result = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event={
            "message_id": "om_reaction_fixture",
            "mentions": [{"name": "Project Review Bot"}],
        },
        create_reaction=lambda _message_id, _emoji_type: "reaction_Get",
        delete_reaction=lambda _message_id, _reaction_id: True,
    )

    assert result["status"] == "receipt_failed"
    assert result["blocker"] == "lark_inbox_received_reaction_receipt_failed"
    assert result["created_count"] == 1
    assert result["external_writes_performed"] is True
    monkeypatch.setattr(
        "loopx.extensions.lark.inbox_reactions.record_lark_inbox_reaction",
        real_record,
    )
    created: list[tuple[str, str]] = []
    recovered = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event={"message_id": "om_reaction_fixture"},
        create_reaction=lambda message_id, emoji_type: (
            created.append((message_id, emoji_type)) or "reaction_duplicate"
        ),
        delete_reaction=lambda _message_id, _reaction_id: True,
    )

    assert recovered["status"] == "receipt_recovered"
    assert recovered["external_writes_performed"] is False
    assert created == []


def test_received_reaction_uncertain_operation_never_repeats_provider_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, _inbox, project = _fixture(tmp_path)
    real_write = inbox_reactions_module._write_received_operation
    write_count = 0

    def fail_created_receipt(**kwargs: object) -> None:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("fixture operation receipt failure")
        real_write(**kwargs)

    monkeypatch.setattr(
        inbox_reactions_module,
        "_write_received_operation",
        fail_created_receipt,
    )
    created: list[tuple[str, str]] = []
    first = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event={"message_id": "om_reaction_fixture"},
        create_reaction=lambda message_id, emoji_type: (
            created.append((message_id, emoji_type)) or "reaction_Get"
        ),
        delete_reaction=lambda _message_id, _reaction_id: False,
    )
    second = ensure_lark_event_inbox_received_reaction(
        project=project,
        config_path=config,
        event={"message_id": "om_reaction_fixture"},
        create_reaction=lambda message_id, emoji_type: (
            created.append((message_id, emoji_type)) or "reaction_duplicate"
        ),
        delete_reaction=lambda _message_id, _reaction_id: False,
    )

    assert first["status"] == "operation_receipt_failed"
    assert first["blocker"] == "lark_inbox_received_reaction_provider_outcome_uncertain"
    assert second["status"] == "provider_outcome_uncertain"
    assert second["external_writes_performed"] is False
    assert created == [("om_reaction_fixture", "Get")]


class ReplyRunner:
    def __init__(
        self,
        *,
        matching_readback: bool = True,
        fail_reaction_delete: bool = False,
        readback_text: str | None = None,
        readback_mentions: list[dict[str, Any]] | None = None,
        include_mentioned_member: bool = True,
    ) -> None:
        self.calls: list[list[str]] = []
        self.matching_readback = matching_readback
        self.fail_reaction_delete = fail_reaction_delete
        self.readback_text = readback_text
        self.readback_mentions = readback_mentions
        self.include_mentioned_member = include_mentioned_member

    def __call__(self, args: Sequence[str]) -> dict[str, Any]:
        call = list(args)
        self.calls.append(call)
        if call[3:6] == ["auth", "status", "--verify"]:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "identities": {
                            "bot": {
                                "available": True,
                                "verified": True,
                                "appName": "Project Review Bot",
                            }
                        }
                    }
                ),
                "stderr": "",
            }
        if call[3:6] == ["im", "chats", "get"]:
            return {"returncode": 0, "stdout": "{}", "stderr": ""}
        if "chat.members" in call and "get" in call:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "items": [
                            {
                                "member_id": (
                                    "ou_public_reviewer"
                                    if self.include_mentioned_member
                                    else "ou_someone_else"
                                )
                            }
                        ]
                    }
                ),
                "stderr": "",
            }
        if "+messages-reply" in call or "+messages-send" in call:
            if "--dry-run" in call:
                reply_text = call[call.index("--text") + 1]
                return {
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "data": {
                                "api": [
                                    {
                                        "body": {
                                            "content": json.dumps(
                                                {"text": reply_text},
                                                ensure_ascii=False,
                                            )
                                        }
                                    }
                                ]
                            }
                        },
                        ensure_ascii=False,
                    ),
                    "stderr": "",
                }
            return {
                "returncode": 0,
                "stdout": json.dumps({"message_id": "om_reply_fixture"}),
                "stderr": "",
            }
        if "+messages-mget" in call:
            message: dict[str, Any] = {
                "message_id": "om_reply_fixture",
                "content": (
                    self.readback_text
                    if self.readback_text is not None
                    else "处理完成"
                    if self.matching_readback
                    else "provider returned different text"
                ),
            }
            if self.readback_mentions is not None:
                message["mentions"] = self.readback_mentions
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {"items": [message]},
                    ensure_ascii=False,
                ),
                "stderr": "",
            }
        if "reactions" in call and "delete" in call:
            return {
                "returncode": int(self.fail_reaction_delete),
                "stdout": json.dumps({"ok": not self.fail_reaction_delete}),
                "stderr": "",
            }
        if "reactions" in call and "list" in call:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "ok": True,
                        "data": {
                            "items": (
                                [{"reaction_id": "reaction_OnIt"}]
                                if self.fail_reaction_delete
                                else []
                            )
                        },
                    }
                ),
                "stderr": "",
            }
        raise AssertionError(call)


def test_processing_replaces_received_reaction(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    record_lark_inbox_reaction(
        inbox=inbox,
        message_id="om_reaction_fixture",
        phase="received",
        reaction_id="reaction_Get",
        emoji_type="Get",
    )
    runner = ReactionRunner()

    result = mark_lark_event_inbox_processing(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["status"] == "processing"
    assert result["created_count"] == 1
    assert result["deleted_count"] == 1
    assert ["create" in call for call in runner.calls] == [True, False]
    assert runner.calls[1][runner.calls[1].index("--reaction-id") + 1] == (
        "reaction_Get"
    )
    assert lark_inbox_reaction_receipts(
        inbox=inbox,
        message_id="om_reaction_fixture",
    ) == {
        "processing": {
            "reaction_id": "reaction_OnIt",
            "emoji_type": "OnIt",
        }
    }


def test_processing_delete_failure_is_retryable(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    record_lark_inbox_reaction(
        inbox=inbox,
        message_id="om_reaction_fixture",
        phase="received",
        reaction_id="reaction_Get",
        emoji_type="Get",
    )
    failed_runner = ReactionRunner(fail_delete=True)

    failed = mark_lark_event_inbox_processing(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        execute=True,
        runner=failed_runner,
    )

    assert failed["ok"] is False
    assert failed["status"] == "cleanup_pending"
    assert failed["blocker"] == "lark_inbox_received_reaction_delete_failed"
    assert set(
        lark_inbox_reaction_receipts(
            inbox=inbox,
            message_id="om_reaction_fixture",
        )
    ) == {"received", "processing"}

    retry_runner = ReactionRunner()
    retried = mark_lark_event_inbox_processing(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        execute=True,
        runner=retry_runner,
    )

    assert retried["ok"] is True
    assert retried["created_count"] == 0
    assert len(retry_runner.calls) == 1
    assert "delete" in retry_runner.calls[0]


def test_delete_retry_accepts_already_absent_reaction(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    record_lark_inbox_reaction(
        inbox=inbox,
        message_id="om_reaction_fixture",
        phase="received",
        reaction_id="reaction_Get",
        emoji_type="Get",
    )
    runner = ReactionRunner(
        fail_delete=True,
        reaction_still_present=False,
    )

    result = mark_lark_event_inbox_processing(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["status"] == "processing"
    assert any("list" in call for call in runner.calls)
    assert set(
        lark_inbox_reaction_receipts(
            inbox=inbox,
            message_id="om_reaction_fixture",
        )
    ) == {"processing"}


def test_completion_removes_only_recorded_bot_reactions(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    for phase, reaction_id, emoji_type in (
        ("received", "reaction_Get", "Get"),
        ("processing", "reaction_OnIt", "OnIt"),
    ):
        record_lark_inbox_reaction(
            inbox=inbox,
            message_id="om_reaction_fixture",
            phase=phase,
            reaction_id=reaction_id,
            emoji_type=emoji_type,
        )
    runner = ReactionRunner()

    result = complete_lark_event_inbox_reactions(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["deleted_count"] == 2
    assert all("delete" in call for call in runner.calls)
    assert {call[call.index("--reaction-id") + 1] for call in runner.calls} == {
        "reaction_Get",
        "reaction_OnIt",
    }
    assert (
        lark_inbox_reaction_receipts(
            inbox=inbox,
            message_id="om_reaction_fixture",
        )
        == {}
    )


def test_lifecycle_is_quiet_when_not_configured(tmp_path: Path) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReactionRunner()

    result = mark_lark_event_inbox_processing(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["status"] == "not_configured"
    assert result["external_writes_performed"] is False
    assert runner.calls == []


def test_verified_reply_removes_processing_reaction(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    record_lark_inbox_reaction(
        inbox=inbox,
        message_id="om_reaction_fixture",
        phase="processing",
        reaction_id="reaction_OnIt",
        emoji_type="OnIt",
    )
    runner = ReplyRunner()

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="处理完成",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["status"] == "sent_verified"
    assert result["reply_verified"] is True
    assert result["reaction_cleanup_verified"] is True
    assert result["placement"] == "source_thread"
    delete_call = next(call for call in runner.calls if "delete" in call)
    assert delete_call[delete_call.index("--reaction-id") + 1] == ("reaction_OnIt")
    assert (
        lark_inbox_reaction_receipts(
            inbox=inbox,
            message_id="om_reaction_fixture",
        )
        == {}
    )


def test_source_context_reply_uses_chat_root_for_top_level_message(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["reply"].update(
        {
            "placement_policy": "source_context",
            "editorial_style": "bullet_points_preferred",
        }
    )
    config.write_text(json.dumps(payload), encoding="utf-8")
    runner = ReplyRunner(readback_text="进展：\n- 第一项\n- 第二项")

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="进展：\n- 第一项\n- 第二项",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["format_preflight_passed"] is True
    assert result["provider_preview_verified"] is True
    assert result["placement"] == "chat_root"
    preview_call = next(call for call in runner.calls if "--dry-run" in call)
    assert preview_call[preview_call.index("--text") + 1] == (
        "进展：\n- 第一项\n- 第二项"
    )
    send_call = next(
        call
        for call in runner.calls
        if "+messages-send" in call and "--dry-run" not in call
    )
    assert "--reply-in-thread" not in send_call
    assert send_call[send_call.index("--chat-id") + 1] == "oc_project_review"
    assert send_call[send_call.index("--text") + 1] == "进展：\n- 第一项\n- 第二项"


def test_source_context_reply_stays_in_existing_topic(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path, lifecycle=False)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["reply"]["placement_policy"] = "source_context"
    config.write_text(json.dumps(payload), encoding="utf-8")
    event_path = inbox / "om_reaction_fixture.json"
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["parent_id"] = "om_topic_root_fixture"
    event["root_id"] = "om_topic_root_fixture"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    runner = ReplyRunner()

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="处理完成",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["placement"] == "source_thread"
    send_call = next(call for call in runner.calls if "+messages-reply" in call)
    assert "--reply-in-thread" in send_call
    assert not any("+messages-send" in call for call in runner.calls)


def test_reply_preview_verifies_provider_without_writing(tmp_path: Path) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(readback_text="line one\nline two")

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="line one\nline two",
        execute=False,
        provider_preflight=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["status"] == "preview_ready"
    assert result["external_write_performed"] is False
    assert result["sender_identity_verified"] is True
    assert result["sender_chat_membership_verified"] is True
    assert result["provider_preview_performed"] is True
    assert result["provider_preview_verified"] is True
    provider_calls = [
        call
        for call in runner.calls
        if "+messages-reply" in call or "+messages-send" in call
    ]
    assert len(provider_calls) == 1
    assert "--dry-run" in provider_calls[0]


def test_reply_rejects_literal_backslash_n_before_provider(tmp_path: Path) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner()

    try:
        reply_lark_event_inbox(
            project=project,
            config_path=config,
            message_id="om_reaction_fixture",
            text=r"status:\n- first\n- second",
            execute=False,
            runner=runner,
        )
    except ValueError as exc:
        assert "literal backslash-n" in str(exc)
    else:
        raise AssertionError("literal backslash-n must fail before provider calls")
    assert runner.calls == []


def test_reply_rejects_literal_notification_mention_before_provider(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner()

    try:
        reply_lark_event_inbox(
            project=project,
            config_path=config,
            message_id="om_reaction_fixture",
            text="@PublicReviewer please review",
            execute=False,
            runner=runner,
        )
    except ValueError as exc:
        assert "structured <at ...> node" in str(exc)
    else:
        raise AssertionError(
            "literal notification mention must fail before provider calls"
        )
    assert runner.calls == []


def test_multiline_readback_must_preserve_line_structure(tmp_path: Path) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(readback_text="line one line two")

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="line one\nline two",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "sent_unverified"
    assert result["provider_preview_verified"] is True
    assert result["reply_verified"] is False


def test_verified_reply_accepts_provider_token_or_rendered_mention_name(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    for readback_text in (
        "@_user_1 please review",
        "@Public Reviewer please review",
    ):
        runner = ReplyRunner(
            readback_text=readback_text,
            readback_mentions=[
                {
                    "key": "@_user_1",
                    "name": "Public Reviewer",
                    "id": {"open_id": "ou_public_reviewer"},
                }
            ],
        )

        result = reply_lark_event_inbox(
            project=project,
            config_path=config,
            message_id="om_reaction_fixture",
            text=(
                '<at open_id="ou_public_reviewer">Public Reviewer</at> please review'
            ),
            execute=True,
            runner=runner,
        )

        assert result["ok"] is True
        assert result["status"] == "sent_verified"
        assert result["reply_verified"] is True


def test_rendered_mention_name_does_not_override_identity_mismatch(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(
        readback_text="@Public Reviewer please review",
        readback_mentions=[
            {
                "key": "@_user_1",
                "name": "Public Reviewer",
                "id": {"open_id": "ou_different_reviewer"},
            }
        ],
    )

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text=('<at open_id="ou_public_reviewer">Public Reviewer</at> please review'),
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "sent_unverified"
    assert result["reply_verified"] is False


def test_structured_mention_requires_exact_chat_member_before_send(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(include_mentioned_member=False)

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text='<at open_id="ou_public_reviewer">Public Reviewer</at> please review',
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "gate_required"
    assert result["blocker"] == "lark_inbox_reply_mention_identity_unresolved"
    assert not any(
        "+messages-send" in call or "+messages-reply" in call for call in runner.calls
    )


def test_structured_mention_queries_the_declared_member_identity_kind(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(
        readback_text="@_user_1 please review",
        readback_mentions=[
            {
                "key": "@_user_1",
                "name": "Public Reviewer",
                "id": {"open_id": "ou_public_reviewer"},
            }
        ],
    )

    result = send_lark_inbox_message(
        project=project,
        config_path=config,
        text='<at open_id="ou_public_reviewer">Public Reviewer</at> please review',
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    member_call = next(call for call in runner.calls if "chat.members" in call)
    assert member_call[member_call.index("--member-id-type") + 1] == "open_id"


def test_plain_reply_rejects_unexpected_provider_mention(tmp_path: Path) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(
        readback_text="please review",
        readback_mentions=[
            {
                "key": "@_user_1",
                "name": "Unexpected Reviewer",
                "id": {"open_id": "ou_unexpected_reviewer"},
            }
        ],
    )

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="please review",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "sent_unverified"
    assert result["reply_verified"] is False


def test_top_level_send_uses_same_mention_safe_delivery_contract(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner(
        readback_text="@_user_1 please review",
        readback_mentions=[
            {
                "key": "@_user_1",
                "name": "Public Reviewer",
                "id": {"open_id": "ou_public_reviewer"},
            }
        ],
    )

    result = send_lark_inbox_message(
        project=project,
        config_path=config,
        text='<at open_id="ou_public_reviewer">Public Reviewer</at> please review',
        execute=True,
        runner=runner,
    )

    assert result["ok"] is True
    assert result["schema_version"] == "lark_outbound_message_v0"
    assert result["status"] == "sent_verified"
    assert result["placement"] == "chat_root"
    assert any(
        "+messages-send" in call and "--dry-run" not in call for call in runner.calls
    )
    assert not any("+messages-reply" in call for call in runner.calls)


def test_top_level_send_rejects_literal_mention_before_provider(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner()

    with pytest.raises(ValueError, match="structured <at"):
        send_lark_inbox_message(
            project=project,
            config_path=config,
            text="@PublicReviewer please review",
            execute=True,
            runner=runner,
        )

    assert runner.calls == []


@pytest.mark.parametrize(
    "text",
    [
        '<at email="reviewer@example.com">Public Reviewer</at> please review',
        '<at open_id="ou_public_reviewer">Public Reviewer',
        "Public Reviewer</at> please review",
    ],
)
def test_top_level_send_rejects_malformed_or_unsupported_mention_nodes(
    tmp_path: Path,
    text: str,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner()

    with pytest.raises(ValueError, match="malformed or unsupported <at> node"):
        send_lark_inbox_message(
            project=project,
            config_path=config,
            text=text,
            execute=True,
            runner=runner,
        )

    assert runner.calls == []


def test_top_level_send_rejects_overlong_text_instead_of_truncating_mention(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path, lifecycle=False)
    runner = ReplyRunner()
    text = (
        "x" * 1160
        + '<at open_id="ou_public_reviewer">Public Reviewer</at> please review'
    )

    with pytest.raises(ValueError, match="exceeds the 1200-character"):
        send_lark_inbox_message(
            project=project,
            config_path=config,
            text=text,
            execute=True,
            runner=runner,
        )

    assert runner.calls == []


def test_unverified_reply_preserves_processing_reaction(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    record_lark_inbox_reaction(
        inbox=inbox,
        message_id="om_reaction_fixture",
        phase="processing",
        reaction_id="reaction_OnIt",
        emoji_type="OnIt",
    )
    runner = ReplyRunner(matching_readback=False)

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="处理完成",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "sent_unverified"
    assert result["reply_verified"] is False
    assert result["reaction_cleanup_verified"] is False
    assert not any("delete" in call for call in runner.calls)
    assert "processing" in lark_inbox_reaction_receipts(
        inbox=inbox,
        message_id="om_reaction_fixture",
    )


def test_verified_reply_reports_retryable_cleanup_failure(
    tmp_path: Path,
) -> None:
    config, inbox, project = _fixture(tmp_path)
    record_lark_inbox_reaction(
        inbox=inbox,
        message_id="om_reaction_fixture",
        phase="processing",
        reaction_id="reaction_OnIt",
        emoji_type="OnIt",
    )
    runner = ReplyRunner(fail_reaction_delete=True)

    result = reply_lark_event_inbox(
        project=project,
        config_path=config,
        message_id="om_reaction_fixture",
        text="处理完成",
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "sent_verified_cleanup_pending"
    assert result["reply_verified"] is True
    assert result["reaction_cleanup_verified"] is False
    assert result["blocker"] == "lark_inbox_reply_reaction_cleanup_pending"
    assert "processing" in lark_inbox_reaction_receipts(
        inbox=inbox,
        message_id="om_reaction_fixture",
    )


def test_processing_config_requires_distinct_received_reaction(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["reply"]["processing_reaction_emoji"] = "Get"
    config.write_text(json.dumps(payload), encoding="utf-8")

    try:
        load_lark_event_inbox_config(project=project, config_path=config)
    except ValueError as exc:
        assert "must differ" in str(exc)
    else:
        raise AssertionError("equal lifecycle reactions must fail closed")

    payload["reply"]["received_reaction_emoji"] = ""
    payload["reply"]["processing_reaction_emoji"] = "OnIt"
    config.write_text(json.dumps(payload), encoding="utf-8")
    try:
        load_lark_event_inbox_config(project=project, config_path=config)
    except ValueError as exc:
        assert "requires received_reaction_emoji" in str(exc)
    else:
        raise AssertionError("processing without received must fail closed")


def test_received_reaction_defaults_to_get_and_can_be_explicitly_disabled(
    tmp_path: Path,
) -> None:
    config, _, project = _fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["reply"].pop("received_reaction_emoji")
    payload["reply"].pop("processing_reaction_emoji")
    config.write_text(json.dumps(payload), encoding="utf-8")

    defaulted = load_lark_event_inbox_config(project=project, config_path=config)
    assert defaulted["reply"]["received_reaction_emoji"] == "Get"

    payload["reply"]["received_reaction_emoji"] = ""
    config.write_text(json.dumps(payload), encoding="utf-8")
    disabled = load_lark_event_inbox_config(project=project, config_path=config)
    assert disabled["reply"]["received_reaction_emoji"] == ""


def test_malformed_receipt_ledger_fails_closed(tmp_path: Path) -> None:
    config, inbox, project = _fixture(tmp_path)
    receipt_path = inbox / "reactions" / "receipts.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text("{not-json", encoding="utf-8")
    runner = ReactionRunner()

    try:
        complete_lark_event_inbox_reactions(
            project=project,
            config_path=config,
            message_id="om_reaction_fixture",
            execute=True,
            runner=runner,
        )
    except ValueError as exc:
        assert "unreadable" in str(exc)
    else:
        raise AssertionError("malformed reaction receipts must fail closed")
    assert runner.calls == []


def test_reaction_module_uses_cross_platform_lock_fallback(
    tmp_path: Path,
) -> None:
    script = """
import builtins
import tempfile
from pathlib import Path

original_import = builtins.__import__

def without_fcntl(name, *args, **kwargs):
    if name == "fcntl":
        raise ImportError("simulated non-POSIX platform")
    return original_import(name, *args, **kwargs)

builtins.__import__ = without_fcntl
from loopx.extensions.lark.inbox_reactions import lark_inbox_reaction_lock

with tempfile.TemporaryDirectory() as raw:
    inbox = Path(raw) / ".loopx" / "inbox" / "feedback"
    with lark_inbox_reaction_lock(
        inbox=inbox,
        message_id="om_cross_platform_fixture",
    ):
        pass
print("cross-platform reaction lock: ok")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "cross-platform reaction lock: ok"

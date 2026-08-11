from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from loopx.extensions.lark.inbox_reactions import (
    complete_lark_event_inbox_reactions,
    lark_inbox_reaction_receipts,
    mark_lark_event_inbox_processing,
    record_lark_inbox_reaction,
)
from loopx.extensions.lark.event_inbox import load_lark_event_inbox_config
from loopx.extensions.lark.inbox_reply import reply_lark_event_inbox


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


class ReplyRunner:
    def __init__(
        self,
        *,
        matching_readback: bool = True,
        fail_reaction_delete: bool = False,
    ) -> None:
        self.calls: list[list[str]] = []
        self.matching_readback = matching_readback
        self.fail_reaction_delete = fail_reaction_delete

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
        if "+messages-reply" in call:
            return {
                "returncode": 0,
                "stdout": json.dumps({"message_id": "om_reply_fixture"}),
                "stderr": "",
            }
        if "+messages-mget" in call:
            return {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "items": [
                            {
                                "message_id": "om_reply_fixture",
                                "content": (
                                    "处理完成"
                                    if self.matching_readback
                                    else "provider returned different text"
                                ),
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                "stderr": "",
            }
        if "reactions" in call and "delete" in call:
            return {
                "returncode": int(self.fail_reaction_delete),
                "stdout": json.dumps(
                    {"ok": not self.fail_reaction_delete}
                ),
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
    assert {
        call[call.index("--reaction-id") + 1] for call in runner.calls
    } == {"reaction_Get", "reaction_OnIt"}
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
    delete_call = next(call for call in runner.calls if "delete" in call)
    assert delete_call[delete_call.index("--reaction-id") + 1] == (
        "reaction_OnIt"
    )
    assert (
        lark_inbox_reaction_receipts(
            inbox=inbox,
            message_id="om_reaction_fixture",
        )
        == {}
    )


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

    payload["reply"].pop("received_reaction_emoji")
    payload["reply"]["processing_reaction_emoji"] = "OnIt"
    config.write_text(json.dumps(payload), encoding="utf-8")
    try:
        load_lark_event_inbox_config(project=project, config_path=config)
    except ValueError as exc:
        assert "requires received_reaction_emoji" in str(exc)
    else:
        raise AssertionError("processing without received must fail closed")


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

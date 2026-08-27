from __future__ import annotations

import json
import subprocess

from loopx.extensions.lark.event_collector_runtime import (
    _run_json_with_status,
    enrich_lark_event_reply_context,
    lark_event_requires_reply_context_lookup,
)


def test_reply_context_lookup_does_not_trust_unrelated_text_mentions() -> None:
    bot_name = "Context Bot"

    assert lark_event_requires_reply_context_lookup(
        {"content": "@Alice can LoopX handle this?"},
        bot_display_name=bot_name,
    )
    assert lark_event_requires_reply_context_lookup(
        {
            "content": "@Alice can LoopX handle this?",
            "mentions": [{"name": "Alice"}],
            "mentioned": False,
        },
        bot_display_name=bot_name,
    )
    assert not lark_event_requires_reply_context_lookup(
        {
            "mentions": [{"name": bot_name}],
            "mentioned": True,
        },
        bot_display_name=bot_name,
    )


def test_json_status_reads_nested_provider_code_from_stderr() -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["lark-cli"],
            returncode=1,
            stdout="",
            stderr=json.dumps(
                {
                    "ok": False,
                    "identity": "bot",
                    "error": {"code": 230027, "message": "permission denied"},
                }
            ),
        )

    payload, status = _run_json_with_status(runner, ["lark-cli", "im", "messages"])

    assert payload == {}
    assert status == "message_context_permission_required"


def test_json_status_preserves_success_payload_from_stdout() -> None:
    expected = {"ok": True, "data": {"items": []}}

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["lark-cli"],
            returncode=0,
            stdout=json.dumps(expected),
            stderr="",
        )

    payload, status = _run_json_with_status(runner, ["lark-cli", "im", "messages"])

    assert payload == expected
    assert status == "message_context_available"


def test_reply_context_hydration_preserves_provider_sender_type() -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        message = {
            "message_id": "om_self_fixture",
            "chat_id": "oc_fixture",
            "content": "Bot delivery status",
            "sender": {
                "sender_type": "app",
                "id": "cli_fixture_bot",
            },
        }
        return subprocess.CompletedProcess(
            args=["lark-cli"],
            returncode=0,
            stdout=json.dumps({"ok": True, "data": {"messages": [message]}}),
            stderr="",
        )

    enriched = enrich_lark_event_reply_context(
        {
            "message_id": "om_self_fixture",
            "chat_id": "oc_fixture",
        },
        runner=runner,
        command_prefix=["lark-cli"],
        profile="fixture-bot",
        profile_app_id="cli_fixture_bot",
        configured_chat_id="oc_fixture",
        sleeper=lambda _seconds: None,
    )

    assert enriched["sender_type"] == "app"
    assert enriched["sender_id"] == "cli_fixture_bot"

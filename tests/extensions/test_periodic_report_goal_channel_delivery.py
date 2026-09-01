from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.capabilities.periodic_report import (
    build_periodic_report_document,
    build_periodic_report_generation_bundle,
    build_periodic_report_source_result,
)
from loopx.extensions.lark.goal_channel_contracts import (
    GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
    write_goal_channel_binding,
)
from loopx.extensions.lark.periodic_report_delivery import (
    DELIVERY_INTENT_SCHEMA,
    GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA,
    deliver_periodic_report_to_goal_channel,
)
from loopx.extensions.lark import periodic_report_cli
from loopx.presentation.renderers.periodic_report_markdown import (
    periodic_report_markdown_renderer_adapter,
)


GOAL_ID = "goal-public-fixture"
CHAT_ID = "oc_public_fixture"
APP_ID = "cli_public_fixture"
MESSAGE_ID = "om_periodic_report_fixture"


def _generation_bundle() -> dict[str, Any]:
    source = build_periodic_report_source_result(
        source_id="project_progress",
        source_kind="project_progress",
        status="complete",
        observed_at="2026-08-30T09:00:00Z",
        sections=[],
    )
    document = build_periodic_report_document(
        title="阶段分析周报",
        generated_at="2026-08-30T09:00:00Z",
        period_window={
            "start_at": "2026-08-29T11:24:00Z",
            "end_at": "2026-08-30T01:55:00Z",
        },
        profile={"profile_id": "weekly_progress", "profile_version": "v1"},
        sources=[source],
    )
    return build_periodic_report_generation_bundle(
        document=document,
        artifacts=[periodic_report_markdown_renderer_adapter().render(document)],
    )


def _request() -> dict[str, Any]:
    return {
        "schema_version": GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA,
        "generation_bundle": _generation_bundle(),
        "delivery_intent": {
            "schema_version": DELIVERY_INTENT_SCHEMA,
            "kind": "goal_channel",
            "sink_id": "lark_delivery",
            "sink_kind": "lark_message",
            "idempotency_key": "periodic-report:goal-public-fixture:stage-1",
            "announcements": [
                {
                    "kind": "hosted_report",
                    "title": "阶段周报",
                    "url": "https://example.com/reports/stage-1",
                },
                {
                    "kind": "lark_document",
                    "title": "配套 Lark 文档",
                    "url": "https://example.larksuite.com/docx/stage-1",
                },
            ],
        },
    }


def _extension_activation() -> dict[str, Any]:
    return {
        "schema_version": "loopx_extension_activation_v0",
        "extension_id": "loopx-lark",
        "provider_version": "1.5.0",
        "revision": "publicfixture123",
        "enabled": True,
        "doctor_verified": True,
        "required_permissions": ["lark.goal_channel.manage"],
    }


def _write_binding(
    registry_path: Path,
    *,
    mode: str = "project_bot",
    app_id: str = APP_ID,
) -> None:
    write_goal_channel_binding(
        registry_path.parent / "goal-channel.json",
        {
            "schema_version": GOAL_CHANNEL_BINDING_SCHEMA_VERSION,
            "bindings": {
                GOAL_ID: {
                    "goal_id": GOAL_ID,
                    "provider": "lark",
                    "enabled": True,
                    "channel": {"chat_id": CHAT_ID},
                    "identity": {
                        "mode": mode,
                        "sender_profile": "project-reporter",
                        "sender_identity": "bot",
                        "bot_app_id": app_id,
                        "bot_display_name": "Project Reporter",
                        "cli_bin": "lark-cli",
                    },
                }
            },
        },
    )


def _runner(calls: list[list[str]], *, normalized_readback: bool = False):
    sent_cards: dict[str, dict[str, Any]] = {}

    def run(
        args: list[str],
        _cwd: Path | None,
        _timeout: float | None,
    ) -> dict[str, Any]:
        calls.append(args)
        assert args[:3] == ["lark-cli", "--profile", "project-reporter"]
        if "auth" in args and "status" in args:
            payload = {
                "ok": True,
                "appId": APP_ID,
                "identities": {
                    "bot": {
                        "available": True,
                        "verified": True,
                        "appName": "Project Reporter",
                    }
                },
            }
        elif "chats" in args and "get" in args:
            payload = {"ok": True, "data": {"chat_id": CHAT_ID}}
        elif "+chat-members-list" in args:
            payload = {
                "ok": True,
                "data": {"bots": [{"app_id": APP_ID}]},
            }
        elif "+messages-send" in args:
            message_id = f"{MESSAGE_ID}_{len(sent_cards) + 1}"
            sent_cards[message_id] = json.loads(args[args.index("--content") + 1])
            payload = {"ok": True, "data": {"message_id": message_id}}
        elif "+messages-mget" in args:
            message_id = args[args.index("--message-ids") + 1]
            card = sent_cards[message_id]
            if normalized_readback:
                title = card["header"]["title"]["content"]
                markdown = card["elements"][0]["text"]["content"]
                footer = card["elements"][2]["elements"][0]["content"]
                message_content = (
                    f'<card title="{title}">\n{markdown}\n---\n'
                    f"📝 {footer}\n</card>"
                )
            payload = {
                "ok": True,
                "data": {
                    "items": [
                        {
                            "message_id": message_id,
                            "chat_id": CHAT_ID,
                            "sender": {
                                "sender_type": "app",
                                "id": APP_ID,
                            },
                            "msg_type": "interactive",
                            **(
                                {"content": message_content}
                                if normalized_readback
                                else {
                                    "body": {
                                        "content": json.dumps(sent_cards[message_id])
                                    }
                                }
                            ),
                        }
                    ]
                },
            }
        else:  # pragma: no cover - makes new provider calls fail loudly
            raise AssertionError(args)
        return {
            "returncode": 0,
            "stdout": json.dumps(payload),
            "stderr": "",
        }

    return run


def test_goal_channel_delivery_accepts_normalized_cli_card_readback(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    runtime_root = tmp_path / "runtime"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    _write_binding(registry_path)
    calls: list[list[str]] = []

    result = deliver_periodic_report_to_goal_channel(
        _request(),
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        extension_activation=_extension_activation(),
        execute=True,
        runner=_runner(calls, normalized_readback=True),
    )

    assert result["ok"] is True
    assert result["status"] == "satisfied"
    assert result["sink_result"]["readback_verified"] is True
    assert len(result["sink_result"]["message_results"]) == 2


def test_goal_channel_delivery_uses_only_the_bound_project_bot(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    _write_binding(registry_path)
    calls: list[list[str]] = []

    preview = deliver_periodic_report_to_goal_channel(
        _request(),
        registry_path=registry_path,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        extension_activation=_extension_activation(),
    )
    sent = deliver_periodic_report_to_goal_channel(
        _request(),
        registry_path=registry_path,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        extension_activation=_extension_activation(),
        execute=True,
        runner=_runner(calls),
    )

    assert preview["status"] == "pending_execution"
    assert preview["boundary"]["caller_identity_override_allowed"] is False
    assert sent["status"] == "satisfied"
    assert sent["sink_result"]["sender_identity_verified"] is True
    sends = [args for args in calls if "+messages-send" in args]
    assert len(sends) == 2
    assert len(sent["sink_result"]["message_results"]) == 2
    assert [item["kind"] for item in sent["sink_result"]["message_results"]] == [
        "hosted_report",
        "lark_document",
    ]
    for send in sends:
        assert send[send.index("--chat-id") + 1] == CHAT_ID
        assert send[send.index("--as") + 1] == "bot"
        assert "--profile" in send
        assert "project-reporter" in send


def test_goal_channel_delivery_requires_native_message_sender_readback(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    _write_binding(registry_path)
    calls: list[list[str]] = []
    base_runner = _runner(calls)

    def runner(
        args: list[str],
        cwd: Path | None,
        timeout: float | None,
    ) -> dict[str, Any]:
        result = base_runner(args, cwd, timeout)
        if "+messages-mget" not in args:
            return result
        payload = json.loads(result["stdout"])
        payload["data"]["items"][0]["sender"]["id"] = "cli_other_fixture"
        return {**result, "stdout": json.dumps(payload)}

    result = deliver_periodic_report_to_goal_channel(
        _request(),
        registry_path=registry_path,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        extension_activation=_extension_activation(),
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "readback_unverified"
    assert result["sink_result"]["sender_identity_verified"] is False


def test_goal_channel_delivery_requires_two_distinct_message_receipts(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    _write_binding(registry_path)
    calls: list[list[str]] = []
    base_runner = _runner(calls)
    last_send_receipts: list[str] = []

    def runner(
        args: list[str],
        cwd: Path | None,
        timeout: float | None,
    ) -> dict[str, Any]:
        if "+messages-send" in args:
            result = base_runner(args, cwd, timeout)
            payload = json.loads(result["stdout"])
            last_send_receipts.append(payload["data"]["message_id"])
            payload["data"]["message_id"] = f"{MESSAGE_ID}_same"
            return {**result, "stdout": json.dumps(payload)}
        if "+messages-mget" in args:
            original = list(args)
            original[original.index("--message-ids") + 1] = last_send_receipts.pop(0)
            result = base_runner(original, cwd, timeout)
            payload = json.loads(result["stdout"])
            payload["data"]["items"][0]["message_id"] = f"{MESSAGE_ID}_same"
            return {**result, "stdout": json.dumps(payload)}
        return base_runner(args, cwd, timeout)

    result = deliver_periodic_report_to_goal_channel(
        _request(),
        registry_path=registry_path,
        runtime_root=tmp_path / "runtime",
        goal_id=GOAL_ID,
        extension_activation=_extension_activation(),
        execute=True,
        runner=runner,
    )

    assert result["ok"] is False
    assert result["status"] == "readback_unverified"


def test_goal_channel_delivery_fails_closed_before_send_on_identity_drift(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    _write_binding(registry_path, mode="local_user")
    with pytest.raises(ValueError, match="project_bot Goal Channel identity"):
        deliver_periodic_report_to_goal_channel(
            _request(),
            registry_path=registry_path,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            extension_activation=_extension_activation(),
            execute=True,
            runner=_runner(calls),
        )
    assert calls == []

    _write_binding(registry_path, app_id="cli_different_fixture")
    with pytest.raises(ValueError, match="sender identity could not be verified"):
        deliver_periodic_report_to_goal_channel(
            _request(),
            registry_path=registry_path,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            extension_activation=_extension_activation(),
            execute=True,
            runner=_runner(calls),
        )
    assert not any("+messages-send" in args for args in calls)


def test_goal_channel_delivery_rejects_caller_route_overrides(tmp_path: Path) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    _write_binding(registry_path)
    request = _request()
    request["delivery_intent"]["sender_profile"] = "environment-default"

    with pytest.raises(ValueError, match="caller overrides are forbidden"):
        deliver_periodic_report_to_goal_channel(
            request,
            registry_path=registry_path,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            extension_activation=_extension_activation(),
        )


def test_goal_channel_delivery_requires_two_ordered_https_announcements(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    registry_path.parent.mkdir()
    registry_path.write_text("{}", encoding="utf-8")
    _write_binding(registry_path)
    request = _request()
    request["delivery_intent"]["announcements"] = request["delivery_intent"][
        "announcements"
    ][:1]

    with pytest.raises(ValueError, match="exactly two announcements"):
        deliver_periodic_report_to_goal_channel(
            request,
            registry_path=registry_path,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            extension_activation=_extension_activation(),
        )

    request = _request()
    request["delivery_intent"]["announcements"][1]["url"] = "file:///tmp/report"
    with pytest.raises(ValueError, match="must be an https URL"):
        deliver_periodic_report_to_goal_channel(
            request,
            registry_path=registry_path,
            runtime_root=tmp_path / "runtime",
            goal_id=GOAL_ID,
            extension_activation=_extension_activation(),
        )


def test_goal_channel_delivery_cli_forwards_registry_and_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry_path = tmp_path / ".loopx" / "registry.json"
    runtime_root = tmp_path / "runtime"
    request_path = tmp_path / "request.json"
    registry_path.parent.mkdir()
    registry_path.write_text(
        json.dumps({"common_runtime_root": str(runtime_root)}),
        encoding="utf-8",
    )
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        periodic_report_cli,
        "resolve_extension_activation",
        lambda *_args, **_kwargs: _extension_activation(),
    )

    def deliver(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        assert request["schema_version"] == GOAL_CHANNEL_DELIVERY_REQUEST_SCHEMA
        return {
            "ok": True,
            "schema_version": "periodic_report_goal_channel_delivery_result_v0",
            "status": "pending_execution",
        }

    monkeypatch.setattr(
        periodic_report_cli,
        "deliver_periodic_report_to_goal_channel",
        deliver,
    )
    from loopx.cli import build_parser

    args = build_parser().parse_args(
        [
            "periodic-report",
            "deliver-goal-channel",
            "--goal-id",
            GOAL_ID,
            "--request-json",
            str(request_path),
        ]
    )
    printed: list[dict[str, object]] = []

    result = periodic_report_cli.handle_lark_periodic_report_command(
        args,
        runtime_root_arg=None,
        registry_path=registry_path,
        output_format=lambda _args: "json",
        print_payload=lambda payload, _format, _renderer: printed.append(payload),
    )

    assert result == 0
    assert printed[0]["status"] == "pending_execution"
    assert captured["registry_path"] == registry_path.resolve()
    assert captured["runtime_root"] == runtime_root.resolve()
    assert captured["goal_id"] == GOAL_ID
    assert captured["execute"] is False

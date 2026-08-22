from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.extensions.external_connector_provider import (
    build_document_comment_connector_registration,
    capture_document_comment_provider_page,
    reply_and_settle_document_comment_event,
)
from loopx.extensions.external_connector_runtime import (
    EFFECT_RECEIPT_SCHEMA_VERSION,
    ExternalCapturePolicy,
    ExternalConnectorCapability,
    ExternalConnectorLifecycle,
    ExternalEffectKind,
    ExternalIngressPolicy,
    ExternalResponsePolicy,
    ExternalSourceKind,
    build_external_connector_binding,
    drain_external_connector_inbox,
    inspect_external_connector_inbox,
)
from loopx.extensions.lark.document_comment_provider import (
    LARK_DOCUMENT_COMMENT_CREATE_SCOPE,
    LARK_DOCUMENT_COMMENT_READ_SCOPE,
    LarkCliDocumentCommentProvider,
    LarkDocumentCommentProviderError,
    LarkDocumentCommentTarget,
)


def _completed(payload: dict[str, Any], *, returncode: int = 0) -> dict[str, Any]:
    return {
        "returncode": returncode,
        "stdout": json.dumps(payload) if returncode == 0 else "",
        "stderr": json.dumps(payload) if returncode != 0 else "",
    }


def _connector() -> dict[str, Any]:
    return build_external_connector_binding(
        goal_ref="goal-alpha",
        agent_ref="agent-alpha",
        provider_kind="loopx-lark",
        source_kind=ExternalSourceKind.DOCUMENT_COMMENT.value,
        source_ref="document-alpha",
        capture_policy=ExternalCapturePolicy.INCREMENTAL.value,
        ingress_policy=ExternalIngressPolicy.ASYNC_INBOX.value,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        cursor_ref=".loopx/inbox/lark-comments/cursor.json",
        lifecycle=ExternalConnectorLifecycle.CONNECTED.value,
        capabilities=[
            ExternalConnectorCapability.HISTORY_CATCH_UP.value,
            ExternalConnectorCapability.RESPONSE_WRITE.value,
            ExternalConnectorCapability.RESPONSE_READBACK.value,
            ExternalConnectorCapability.ACKNOWLEDGE.value,
        ],
        inbox_ref=".loopx/inbox/lark-comments",
    )


def _target() -> LarkDocumentCommentTarget:
    return LarkDocumentCommentTarget(
        source_ref="document-alpha",
        document_url="https://example.larksuite.com/docx/document-alpha",
        provider_identity="fixture-profile",
        profile="fixture-profile",
        identity="bot",
    )


def _comment_page(*, whole: bool = False) -> dict[str, Any]:
    return {
        "ok": True,
        "identity": "bot",
        "data": {
            "file_token": "document-alpha",
            "file_type": "docx",
            "items": [
                {
                    "comment_id": "comment-alpha",
                    "create_time": 1_787_377_486,
                    "is_solved": False,
                    "is_whole": whole,
                    "quote": "Selected paragraph",
                    "reply_list": {
                        "replies": [
                            {
                                "reply_id": "reply-human-alpha",
                                "create_time": 1_787_377_486,
                                "content": {
                                    "elements": [
                                        {
                                            "type": "text_run",
                                            "text_run": {
                                                "text": "Please validate this comment."
                                            },
                                        }
                                    ]
                                },
                            }
                        ]
                    },
                }
            ],
            "has_more": False,
            "page_token": "",
            "count": 1,
        },
    }


def _reply_page(text: str) -> dict[str, Any]:
    return {
        "ok": True,
        "identity": "bot",
        "data": {
            "items": [
                {
                    "reply_id": "reply-agent-alpha",
                    "create_time": 1_787_377_500,
                    "content": {
                        "elements": [
                            {
                                "type": "text_run",
                                "text_run": {"text": text},
                            }
                        ]
                    },
                }
            ],
            "has_more": False,
            "page_token": "",
        },
    }


def test_lark_permission_probe_binds_exact_comment_scopes(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(args, _cwd, _timeout):
        calls.append(list(args))
        if args[-3:] == ["auth", "status", "--json"]:
            return _completed({"identity": "bot"})
        return _completed(
            {
                "ok": False,
                "missing": [
                    LARK_DOCUMENT_COMMENT_CREATE_SCOPE,
                    LARK_DOCUMENT_COMMENT_READ_SCOPE,
                ],
            }
        )

    provider = LarkCliDocumentCommentProvider(
        target=_target(),
        reply_store=tmp_path / "reply-receipts.json",
        runner=runner,
    )
    guidance = provider.permission_guidance(
        response_enabled=True,
        published=True,
    )

    assert guidance["ready"] is False
    assert guidance["missing_requirement_count"] == 3
    assert calls == [
        [
            "lark-cli",
            "--profile",
            "fixture-profile",
            "auth",
            "status",
            "--json",
        ],
        [
            "lark-cli",
            "--profile",
            "fixture-profile",
            "auth",
            "check",
            "--scope",
            (
                f"{LARK_DOCUMENT_COMMENT_CREATE_SCOPE} "
                f"{LARK_DOCUMENT_COMMENT_READ_SCOPE}"
            ),
            "--json",
        ],
    ]


def test_lark_permission_probe_rejects_identity_mismatch(tmp_path: Path) -> None:
    provider = LarkCliDocumentCommentProvider(
        target=_target(),
        reply_store=tmp_path / "reply-receipts.json",
        runner=lambda *_: _completed({"identity": "user"}),
    )

    try:
        provider.permission_guidance(response_enabled=True, published=True)
    except LarkDocumentCommentProviderError as error:
        assert error.code == (
            "lark_document_comment_permission_probe_identity_mismatch"
        )
    else:
        raise AssertionError("permission probes must use the configured identity")


def test_lark_provider_filters_unreplyable_comment_cards(tmp_path: Path) -> None:
    provider = LarkCliDocumentCommentProvider(
        target=_target(),
        reply_store=tmp_path / "reply-receipts.json",
        runner=lambda *_: _completed(_comment_page(whole=True)),
    )

    page = provider.page_reader(_connector(), None, 100)

    assert page["events"] == []
    assert page["has_more"] is False
    assert page["next_cursor"].startswith("lark-comment-v0.")


def test_lark_document_comment_callsite_runs_read_effect_reply_readback_ack(
    tmp_path: Path,
) -> None:
    call_order: list[str] = []
    created_reply_text = "Accepted after durable writeback."

    def runner(args, _cwd, _timeout):
        command = list(args)
        if command[-3:] == ["auth", "status", "--json"]:
            call_order.append("identity_probe")
            return _completed({"identity": "bot"})
        if command[-3:] == [
            "--scope",
            (
                f"{LARK_DOCUMENT_COMMENT_CREATE_SCOPE} "
                f"{LARK_DOCUMENT_COMMENT_READ_SCOPE}"
            ),
            "--json",
        ]:
            call_order.append("permission_probe")
            return _completed(
                {
                    "ok": True,
                    "granted": [
                        LARK_DOCUMENT_COMMENT_CREATE_SCOPE,
                        LARK_DOCUMENT_COMMENT_READ_SCOPE,
                    ],
                    "missing": [],
                }
            )
        if "+list-comments" in command:
            call_order.append("provider_read")
            assert command[command.index("--page-size") + 1] == "1"
            return _completed(_comment_page())
        if (
            "file.comment.replys" in command
            and command[command.index("file.comment.replys") + 1] == "create"
        ):
            call_order.append("provider_reply")
            payload = json.loads(command[command.index("--data") + 1])
            assert payload["extra"].startswith("sha256:")
            assert payload["content"]["elements"][0]["text_run"]["text"] == (
                created_reply_text
            )
            return _completed(
                {
                    "ok": True,
                    "identity": "bot",
                    "data": {"reply_id": "reply-agent-alpha"},
                }
            )
        if (
            "file.comment.replys" in command
            and command[command.index("file.comment.replys") + 1] == "list"
        ):
            call_order.append("provider_readback")
            return _completed(_reply_page(created_reply_text))
        raise AssertionError(f"unexpected lark-cli call: {command}")

    reply_store = tmp_path / "reply-receipts.json"
    provider = LarkCliDocumentCommentProvider(
        target=_target(),
        reply_store=reply_store,
        runner=runner,
    )
    requirements = provider.permission_requirements(response_enabled=True)
    guidance = provider.permission_guidance(
        response_enabled=True,
        published=True,
    )
    registration = build_document_comment_connector_registration(
        connector=_connector(),
        authority_material_ref="material-alpha",
        project_materials={
            "material-alpha": {"id": "material-alpha", "source_kind": "document"}
        },
        permission_requirements=requirements,
    )
    capture = capture_document_comment_provider_page(
        project=str(tmp_path),
        registration=registration,
        permission_guidance=guidance,
        page_reader=provider.page_reader,
        expected_cursor=None,
        execute=True,
    )
    assert capture["accepted_count"] == 1

    event = drain_external_connector_inbox(
        project=tmp_path,
        binding=registration["connector"],
        limit=1,
    )["items"][0]
    call_order.append("durable_effect")
    settlement = reply_and_settle_document_comment_event(
        project=str(tmp_path),
        registration=registration,
        permission_guidance=guidance,
        event_id=event["event_id"],
        effect_receipt={
            "schema_version": EFFECT_RECEIPT_SCHEMA_VERSION,
            "event_id": event["event_id"],
            "effect_id": "effect-alpha",
            "effect_kind": ExternalEffectKind.TODO_UPDATE.value,
            "status": "committed",
        },
        reply_text=created_reply_text,
        response_writer=provider.response_writer,
        execute=True,
    )

    assert settlement["status"] == "acknowledged"
    assert settlement["response_readback_verified"] is True
    assert call_order == [
        "identity_probe",
        "permission_probe",
        "provider_read",
        "durable_effect",
        "provider_reply",
        "provider_readback",
    ]
    assert (
        inspect_external_connector_inbox(
            project=tmp_path,
            binding=registration["connector"],
        )["pending_count"]
        == 0
    )
    receipt_text = reply_store.read_text(encoding="utf-8")
    assert created_reply_text not in receipt_text
    assert "pending_readback" not in receipt_text
    assert '"status": "verified"' in receipt_text

    receipt = json.loads(receipt_text)
    idempotency_key = next(iter(receipt["entries"]))
    second = provider.response_writer(
        registration["connector"],
        event,
        created_reply_text,
        idempotency_key,
    )
    assert second["readback_verified"] is True
    assert call_order.count("provider_reply") == 1
    assert call_order.count("provider_readback") == 2


def test_lark_provider_rejects_connector_target_mismatch(tmp_path: Path) -> None:
    provider = LarkCliDocumentCommentProvider(
        target=_target(),
        reply_store=tmp_path / "reply-receipts.json",
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("must not call CLI")),
    )
    connector = _connector()
    connector["source_ref"] = "different-document"

    try:
        provider.page_reader(connector, None, 10)
    except LarkDocumentCommentProviderError as error:
        assert error.code == "connector_source_ref_mismatch"
    else:
        raise AssertionError("target mismatch must fail closed")


def test_lark_provider_rejects_unconfigured_address_inference(tmp_path: Path) -> None:
    provider = LarkCliDocumentCommentProvider(
        target=_target(),
        reply_store=tmp_path / "reply-receipts.json",
        runner=lambda *_: (_ for _ in ()).throw(AssertionError("must not call CLI")),
    )
    connector = _connector()
    connector["capture_policy"] = ExternalCapturePolicy.ADDRESSED_ONLY.value

    try:
        provider.page_reader(connector, None, 10)
    except LarkDocumentCommentProviderError as error:
        assert error.code == "connector_address_filter_unsupported"
    else:
        raise AssertionError("unsupported address inference must fail closed")

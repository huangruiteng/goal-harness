from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

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
    build_external_connector_event,
    build_external_event_response_receipt,
    capture_external_connector_events,
    decide_external_event_ack,
    drain_external_connector_inbox,
    inspect_external_connector_inbox,
    project_external_connector_status,
    record_external_connector_failure,
    settle_external_connector_event,
)


def _binding(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "goal_ref": "goal-alpha",
        "agent_ref": "agent-alpha",
        "provider_kind": "provider-fixture",
        "source_kind": ExternalSourceKind.GROUP_MESSAGE.value,
        "source_ref": "source-fixture",
        "capture_policy": ExternalCapturePolicy.ADDRESSED_ONLY.value,
        "ingress_policy": ExternalIngressPolicy.LIVE_STEERING.value,
        "response_policy": ExternalResponsePolicy.SOURCE_THREAD.value,
        "cursor_ref": ".loopx/inbox/source-fixture/processed.json",
        "lifecycle": ExternalConnectorLifecycle.CONNECTED.value,
        "capabilities": [
            ExternalConnectorCapability.REALTIME_RECEIVE.value,
            ExternalConnectorCapability.RESPONSE_WRITE.value,
            ExternalConnectorCapability.RESPONSE_READBACK.value,
            ExternalConnectorCapability.ACKNOWLEDGE.value,
        ],
        "session_ref": "session-alpha",
    }
    values.update(overrides)
    return build_external_connector_binding(**values)  # type: ignore[arg-type]


def test_group_message_binding_targets_one_exact_working_session() -> None:
    binding = _binding()

    assert binding["source_kind"] == "group_message"
    assert binding["agent_ref"] == "agent-alpha"
    assert binding["session_ref"] == "session-alpha"
    assert binding["ingress_policy"] == "live_steering"


def test_document_comment_binding_supports_incremental_async_inbox() -> None:
    binding = _binding(
        source_kind=ExternalSourceKind.DOCUMENT_COMMENT.value,
        capture_policy=ExternalCapturePolicy.INCREMENTAL.value,
        ingress_policy=ExternalIngressPolicy.ASYNC_INBOX.value,
        session_ref=None,
        inbox_ref=".loopx/inbox/document-comments",
        capabilities=[
            ExternalConnectorCapability.HISTORY_CATCH_UP.value,
            ExternalConnectorCapability.RESPONSE_WRITE.value,
            ExternalConnectorCapability.RESPONSE_READBACK.value,
            ExternalConnectorCapability.ACKNOWLEDGE.value,
        ],
    )

    assert binding["source_kind"] == "document_comment"
    assert binding["capture_policy"] == "incremental"
    assert binding["ingress_policy"] == "async_inbox"
    assert binding["inbox_ref"] == ".loopx/inbox/document-comments"


@pytest.mark.parametrize("ingress", ["live_steering", "session_queue"])
def test_ordered_session_delivery_requires_exact_session(ingress: str) -> None:
    with pytest.raises(ValueError, match="exact session_ref"):
        _binding(ingress_policy=ingress, session_ref=None)


def test_async_delivery_requires_owner_local_inbox() -> None:
    with pytest.raises(ValueError, match="owner-local inbox_ref"):
        _binding(
            ingress_policy=ExternalIngressPolicy.ASYNC_INBOX.value,
            session_ref=None,
            inbox_ref=None,
        )

    with pytest.raises(ValueError, match="cannot bind an exact session_ref"):
        _binding(
            ingress_policy=ExternalIngressPolicy.ASYNC_INBOX.value,
            session_ref="session-alpha",
            inbox_ref=".loopx/inbox/source-fixture",
        )


@pytest.mark.parametrize(
    ("capture_policy", "capabilities"),
    [
        (
            ExternalCapturePolicy.ADDRESSED_ONLY.value,
            [ExternalConnectorCapability.HISTORY_CATCH_UP.value],
        ),
        (
            ExternalCapturePolicy.INCREMENTAL.value,
            [],
        ),
        (
            ExternalCapturePolicy.ADDRESSED_ONLY.value,
            [ExternalConnectorCapability.ACKNOWLEDGE.value],
        ),
    ],
)
def test_cursor_advancing_operations_require_incremental_checkpoint(
    capture_policy: str,
    capabilities: list[str],
) -> None:
    with pytest.raises(ValueError, match="owner-local cursor_ref"):
        _binding(
            cursor_ref=None,
            capture_policy=capture_policy,
            capabilities=capabilities,
            response_policy=ExternalResponsePolicy.NO_RESPONSE.value,
        )


def test_response_policy_requires_write_and_readback_capabilities() -> None:
    with pytest.raises(ValueError, match="response_write and response_readback"):
        _binding(capabilities=[ExternalConnectorCapability.RESPONSE_WRITE.value])


def test_status_projection_omits_private_source_and_cursor_references() -> None:
    status = project_external_connector_status(_binding())

    assert "source_ref" not in status
    assert "cursor_ref" not in status
    assert status["private_source_ref_captured"] is False
    assert status["private_cursor_ref_captured"] is False
    assert status["session_bound"] is True


def test_ack_fails_closed_until_effect_and_response_are_verified() -> None:
    with pytest.raises(TypeError, match="proof fields must be booleans"):
        build_external_event_response_receipt(
            event_id="event-alpha",
            external_write_performed="yes",  # type: ignore[arg-type]
            verification_performed=True,
            response_verified=True,
        )

    missing_effect = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=None,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        response_receipt=build_external_event_response_receipt(
            event_id="event-alpha",
            external_write_performed=True,
            verification_performed=True,
            response_verified=True,
        ),
    )
    assert missing_effect["ack_allowed"] is False
    assert missing_effect["reason"] == "durable_effect_required"

    effect_receipt = {
        "schema_version": EFFECT_RECEIPT_SCHEMA_VERSION,
        "event_id": "event-alpha",
        "effect_id": "effect-alpha",
        "effect_kind": ExternalEffectKind.TODO_UPDATE.value,
        "status": "committed",
    }
    missing_readback = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=effect_receipt,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        response_receipt=build_external_event_response_receipt(
            event_id="event-alpha",
            external_write_performed=True,
            verification_performed=False,
            response_verified=False,
        ),
    )
    assert missing_readback["ack_allowed"] is False
    assert missing_readback["reason"] == "verified_response_required"

    ready = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=effect_receipt,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        response_receipt=build_external_event_response_receipt(
            event_id="event-alpha",
            external_write_performed=True,
            verification_performed=True,
            response_verified=True,
        ),
    )
    assert ready["ack_allowed"] is True
    assert ready["reason"] == "ready"

    replayed_response = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=effect_receipt,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        response_receipt=build_external_event_response_receipt(
            event_id="event-other",
            external_write_performed=True,
            verification_performed=True,
            response_verified=True,
        ),
    )
    assert replayed_response["ack_allowed"] is False
    assert replayed_response["reason"] == "verified_response_required"


def test_no_response_connector_still_requires_durable_effect() -> None:
    effect_receipt = {
        "schema_version": EFFECT_RECEIPT_SCHEMA_VERSION,
        "event_id": "event-alpha",
        "effect_id": "effect-alpha",
        "effect_kind": ExternalEffectKind.NO_FOLLOW_UP.value,
        "status": "committed",
    }
    ready = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=effect_receipt,
        response_policy=ExternalResponsePolicy.NO_RESPONSE.value,
    )

    assert ready["ack_allowed"] is True
    assert ready["response_required"] is False


def _document_binding() -> dict[str, object]:
    return _binding(
        source_kind=ExternalSourceKind.DOCUMENT_COMMENT.value,
        capture_policy=ExternalCapturePolicy.INCREMENTAL.value,
        ingress_policy=ExternalIngressPolicy.ASYNC_INBOX.value,
        session_ref=None,
        inbox_ref=".loopx/inbox/document-comments",
        cursor_ref=".loopx/inbox/document-comments/cursor.json",
        capabilities=[
            ExternalConnectorCapability.HISTORY_CATCH_UP.value,
            ExternalConnectorCapability.RESPONSE_WRITE.value,
            ExternalConnectorCapability.RESPONSE_READBACK.value,
            ExternalConnectorCapability.ACKNOWLEDGE.value,
        ],
    )


def _comment_event(
    event_id: str,
    *,
    addressed: bool = True,
    content: str = "Please verify this decision.",
) -> dict[str, object]:
    return build_external_connector_event(
        event_id=event_id,
        content=content,
        occurred_at="2026-08-22T10:00:00Z",
        addressed=addressed,
        event_cursor=f"cursor-{event_id}",
        anchor_ref=f"anchor-{event_id}",
        reply_chain_ref=f"thread-{event_id}",
    )


def _effect(event_id: str) -> dict[str, object]:
    return {
        "schema_version": EFFECT_RECEIPT_SCHEMA_VERSION,
        "event_id": event_id,
        "effect_id": f"effect-{event_id}",
        "effect_kind": ExternalEffectKind.DESIGN_UPDATE.value,
        "status": "committed",
    }


def _response(event_id: str) -> dict[str, object]:
    return build_external_event_response_receipt(
        event_id=event_id,
        external_write_performed=True,
        verification_performed=True,
        response_verified=True,
    )


def test_incremental_document_comment_inbox_advances_cursor_after_last_ack(
    tmp_path: Path,
) -> None:
    binding = _document_binding()
    capture = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one"), _comment_event("event-two")],
        expected_cursor=None,
        next_cursor="page-two",
        execute=True,
    )

    assert capture["accepted_count"] == 2
    assert capture["cursor_advanced"] is False
    assert capture["private_event_content_captured"] is False

    drained = drain_external_connector_inbox(
        project=tmp_path,
        binding=binding,
    )
    assert [item["event_id"] for item in drained["items"]] == [
        "event-one",
        "event-two",
    ]
    assert drained["items"][0]["content"] == "Please verify this decision."
    assert drained["items"][0]["anchor_ref"] == "anchor-event-one"
    assert drained["items"][0]["reply_chain_ref"] == "thread-event-one"
    assert drained["local_private_content_returned"] is True

    missing_effect = settle_external_connector_event(
        project=tmp_path,
        binding=binding,
        event_id="event-one",
        effect_receipt=None,
        response_receipt=_response("event-one"),
        execute=True,
    )
    assert missing_effect["status"] == "durable_effect_required"

    first = settle_external_connector_event(
        project=tmp_path,
        binding=binding,
        event_id="event-one",
        effect_receipt=_effect("event-one"),
        response_receipt=_response("event-one"),
        execute=True,
    )
    assert first["status"] == "acknowledged"
    assert first["cursor_advanced"] is False
    assert first["private_event_deleted"] is True

    second = settle_external_connector_event(
        project=tmp_path,
        binding=binding,
        event_id="event-two",
        effect_receipt=_effect("event-two"),
        response_receipt=_response("event-two"),
        execute=True,
    )
    assert second["status"] == "acknowledged"
    assert second["cursor_advanced"] is True
    assert second["private_event_deleted"] is True
    events_root = tmp_path / ".loopx/inbox/document-comments/events"
    assert list(events_root.glob("*.json")) == []

    next_page = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-three")],
        expected_cursor="page-two",
        next_cursor="page-three",
        execute=False,
    )
    assert next_page["ok"] is True
    assert next_page["accepted_count"] == 1

    status = inspect_external_connector_inbox(
        project=tmp_path,
        binding=binding,
        now=datetime(2026, 8, 22, 10, 1, tzinfo=UTC),
    )
    assert status["pending_count"] == 0
    assert "items" not in status
    assert "committed_cursor" not in status
    assert status["private_event_content_captured"] is False
    assert status["private_cursor_value_captured"] is False


def test_external_connector_settlement_is_strictly_ordered(tmp_path: Path) -> None:
    binding = _document_binding()
    capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one"), _comment_event("event-two")],
        expected_cursor=None,
        next_cursor="page-two",
        execute=True,
    )

    result = settle_external_connector_event(
        project=tmp_path,
        binding=binding,
        event_id="event-two",
        effect_receipt=_effect("event-two"),
        response_receipt=_response("event-two"),
        execute=True,
    )

    assert result["ok"] is False
    assert result["status"] == "ordered_event_required"


def test_addressed_capture_can_checkpoint_a_fully_filtered_page(
    tmp_path: Path,
) -> None:
    binding = _document_binding()
    binding["capture_policy"] = ExternalCapturePolicy.ADDRESSED_ONLY.value

    capture = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one", addressed=False)],
        expected_cursor=None,
        next_cursor="page-two",
        execute=True,
    )

    assert capture["accepted_count"] == 0
    assert capture["filtered_count"] == 1
    assert capture["cursor_advanced"] is True
    continuation = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-two")],
        expected_cursor="page-two",
        next_cursor="page-three",
        execute=False,
    )
    assert continuation["ok"] is True


def test_capture_fails_closed_on_stale_cursor(tmp_path: Path) -> None:
    binding = _document_binding()
    result = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one")],
        expected_cursor="unexpected",
        next_cursor="page-two",
        execute=True,
    )

    assert result["ok"] is False
    assert result["status"] == "cursor_mismatch"
    assert (
        drain_external_connector_inbox(
            project=tmp_path,
            binding=binding,
        )["pending_count"]
        == 0
    )


def test_failure_projection_is_content_free(tmp_path: Path) -> None:
    binding = _document_binding()
    receipt = record_external_connector_failure(
        project=tmp_path,
        binding=binding,
        error_code="provider_timeout",
        execute=True,
    )
    status = inspect_external_connector_inbox(
        project=tmp_path,
        binding=binding,
    )

    assert receipt["recorded"] is True
    assert status["failure_count"] == 1
    assert status["last_error_code"] == "provider_timeout"
    assert status["private_event_ids_captured"] is False
    assert status["private_source_ref_captured"] is False


def test_capture_backpressure_leaves_page_and_cursor_pending(tmp_path: Path) -> None:
    binding = _document_binding()
    capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one")],
        expected_cursor=None,
        next_cursor="page-two",
        max_pending=1,
        execute=True,
    )

    blocked = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-two")],
        expected_cursor=None,
        next_cursor="page-two",
        max_pending=1,
        execute=True,
    )

    assert blocked["ok"] is False
    assert blocked["status"] == "backpressure_required"
    assert blocked["pending_count"] == 1
    assert blocked["cursor_advanced"] is False


def test_replayed_acknowledged_page_can_advance_cursor(tmp_path: Path) -> None:
    binding = _document_binding()
    capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one")],
        expected_cursor=None,
        next_cursor="page-two",
        execute=True,
    )
    settle_external_connector_event(
        project=tmp_path,
        binding=binding,
        event_id="event-one",
        effect_receipt=_effect("event-one"),
        response_receipt=_response("event-one"),
        execute=True,
    )

    replay = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[_comment_event("event-one")],
        expected_cursor="page-two",
        next_cursor="page-three",
        execute=True,
    )

    assert replay["duplicate_count"] == 1
    assert replay["cursor_advanced"] is True
    continuation = capture_external_connector_events(
        project=tmp_path,
        binding=binding,
        events=[],
        expected_cursor="page-three",
        next_cursor="page-four",
        execute=False,
    )
    assert continuation["ok"] is True

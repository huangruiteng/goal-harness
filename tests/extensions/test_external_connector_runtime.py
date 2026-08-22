from __future__ import annotations

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
    decide_external_event_ack,
    project_external_connector_status,
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
    missing_effect = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=None,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        response_receipt={
            "external_write_performed": True,
            "verification_performed": True,
            "response_verified": True,
        },
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
        response_receipt={
            "external_write_performed": True,
            "verification_performed": False,
        },
    )
    assert missing_readback["ack_allowed"] is False
    assert missing_readback["reason"] == "verified_response_required"

    ready = decide_external_event_ack(
        event_id="event-alpha",
        effect_receipt=effect_receipt,
        response_policy=ExternalResponsePolicy.SOURCE_THREAD.value,
        response_receipt={
            "external_write_performed": True,
            "verification_performed": True,
            "reply_verified": True,
        },
    )
    assert ready["ack_allowed"] is True
    assert ready["reason"] == "ready"


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

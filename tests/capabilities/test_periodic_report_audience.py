from __future__ import annotations

from typing import Any

import pytest

from loopx.capabilities.periodic_report import (
    PeriodicReportAdapterRegistry,
    build_periodic_report_activation,
    build_periodic_report_announcement_plan,
    build_periodic_report_document,
    build_periodic_report_source_result,
)
from loopx.extensions.lark.presentation.periodic_report import (
    periodic_report_lark_sink_adapter,
)
from loopx.presentation.renderers.periodic_report_markdown import (
    periodic_report_markdown_renderer_adapter,
)


def _goal_channel_binding(goal_id: str) -> dict[str, Any]:
    return {
        "goal_id": goal_id,
        "provider": "lark",
        "enabled": True,
        "channel": {"chat_id": "oc_weekly_progress"},
        "identity": {
            "mode": "project_bot",
            "sender_profile": "weekly-progress-bot",
            "sender_identity": "bot",
            "bot_app_id": "cli_weekly_progress",
            "bot_display_name": "Weekly Progress",
        },
    }


def _document() -> dict[str, Any]:
    source = build_periodic_report_source_result(
        source_id="project_progress",
        source_kind="validated_progress",
        status="complete",
        observed_at="2026-08-20T09:00:00Z",
        sections=[
            {
                "section_id": "progress",
                "title": "Progress",
                "order": 10,
                "items": [
                    {
                        "item_id": "routing_ready",
                        "title": "Routing contract ready",
                        "summary": "The typed routing contract passed focused tests.",
                        "value_rank": 10,
                        "content_kind": "outcome",
                        "domains": ["model_routing"],
                    },
                    {
                        "item_id": "runtime_risk",
                        "title": "Runtime check remains",
                        "summary": "One runtime check remains before broad activation.",
                        "value_rank": 20,
                        "content_kind": "risk",
                        "domains": ["runtime"],
                        "tags": ["urgent"],
                    },
                    {
                        "item_id": "delivery_receipt",
                        "title": "Delivery verified",
                        "summary": "Exact provider readback matched.",
                        "value_rank": 30,
                        "content_kind": "delivery_receipt",
                        "visibility": "supporting",
                        "domains": ["model_routing"],
                    },
                ],
            }
        ],
    )
    return build_periodic_report_document(
        title="Weekly progress",
        generated_at="2026-08-20T10:00:00Z",
        period_window={
            "start_at": "2026-08-13T00:00:00Z",
            "end_at": "2026-08-20T00:00:00Z",
        },
        profile={"profile_id": "weekly_progress", "profile_version": "v1"},
        sources=[source],
    )


def _audience_policy() -> dict[str, Any]:
    return {
        "schema_version": "periodic_report_audience_policy_v0",
        "recipients": [
            {
                "recipient_id": "routing_owner",
                "owned_domains": ["model_routing"],
            },
            {
                "recipient_id": "incident_owner",
                "routing_rules": [
                    {
                        "rule_id": "urgent_runtime",
                        "domains_any": ["runtime"],
                        "tags_any": ["urgent"],
                    }
                ],
            },
            {
                "recipient_id": "unrelated_owner",
                "owned_domains": ["documentation"],
            },
        ],
    }


def _registry(
    *,
    sent_cards: list[dict[str, Any]],
    rendered_recipient_ids: list[str],
    with_renderer: bool = True,
) -> PeriodicReportAdapterRegistry:
    registry = PeriodicReportAdapterRegistry()

    def send(card: dict[str, Any], _key: str, _route: dict[str, Any]) -> dict[str, str]:
        sent_cards.append(card)
        return {"message_id": "om_report_example"}

    def render(recipient_id: str) -> str:
        rendered_recipient_ids.append(recipient_id)
        return f'<at user_id="{recipient_id}">{recipient_id}</at>'

    registry.register_sink(
        periodic_report_lark_sink_adapter(
            send=send,
            readback=lambda ref: {
                "verified": True,
                "message_id": ref,
                "chat_id": "oc_weekly_progress",
                "sender_app_id": "cli_weekly_progress",
                "sender_identity": "bot",
                "sender_evidence_source": "message_readback",
            },
            resolve_goal_channel=_goal_channel_binding,
            verify_goal_channel=lambda _route: True,
            render_recipient_mention=render if with_renderer else None,
        )
    )
    return registry


def test_audience_plan_matches_owned_domains_and_typed_rules_only() -> None:
    plan = build_periodic_report_announcement_plan(
        document=_document(),
        audience_policy=_audience_policy(),
    )

    assert plan["mentioned_recipient_ids"] == [
        "incident_owner",
        "routing_owner",
    ]
    by_id = {item["recipient_id"]: item for item in plan["recipients"]}
    assert by_id["routing_owner"]["matching_item_count"] == 1
    assert by_id["routing_owner"]["matching_item_refs"][0]["item_id"] == (
        "routing_ready"
    )
    assert by_id["incident_owner"]["matching_item_refs"][0]["reasons"] == [
        {"kind": "routing_rule", "rule_id": "urgent_runtime"}
    ]
    assert by_id["unrelated_owner"]["mention"] is False
    assert plan["boundary"]["title_or_summary_text_inference"] is False


def test_profile_owns_normalized_audience_policy() -> None:
    activation = build_periodic_report_activation(
        {
            "schema_version": "periodic_report_profile_v0",
            "profile_id": "weekly_progress",
            "profile_version": "v1",
            "audience_policy": _audience_policy(),
        }
    )

    policy = activation["profile"]["audience_policy"]
    assert policy["eligible_visibilities"] == ["primary"]
    assert [item["recipient_id"] for item in policy["recipients"]] == [
        "incident_owner",
        "routing_owner",
        "unrelated_owner",
    ]


@pytest.mark.parametrize(
    ("recipient", "message"),
    [
        ({"recipient_id": "owner"}, "requires at least one"),
        (
            {
                "recipient_id": "owner",
                "routing_rules": [{"rule_id": "text_guess", "summary": "routing"}],
            },
            "unsupported fields",
        ),
        (
            {
                "recipient_id": "owner",
                "routing_rules": [{"rule_id": "empty"}],
            },
            "typed selector",
        ),
    ],
)
def test_audience_policy_rejects_implicit_or_empty_relevance(
    recipient: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_periodic_report_announcement_plan(
            document=_document(),
            audience_policy={
                "schema_version": "periodic_report_audience_policy_v0",
                "recipients": [recipient],
            },
        )


def test_lark_preview_exposes_plan_without_render_or_send() -> None:
    sent_cards: list[dict[str, Any]] = []
    rendered_recipient_ids: list[str] = []
    registry = _registry(
        sent_cards=sent_cards,
        rendered_recipient_ids=rendered_recipient_ids,
    )
    document = _document()
    artifact = periodic_report_markdown_renderer_adapter().render(document)

    result = registry.deliver(
        "lark_delivery",
        artifact,
        {
            "execute": False,
            "goal_id": "project-goal",
            "idempotency_key": "audience-preview",
            "document": document,
            "audience_policy": _audience_policy(),
        },
    )

    assert result["status"] == "pending"
    assert result["announcement_plan"]["mentioned_recipient_count"] == 2
    assert sent_cards == []
    assert rendered_recipient_ids == []


def test_lark_execute_renders_only_relevant_recipients() -> None:
    sent_cards: list[dict[str, Any]] = []
    rendered_recipient_ids: list[str] = []
    registry = _registry(
        sent_cards=sent_cards,
        rendered_recipient_ids=rendered_recipient_ids,
    )
    document = _document()
    artifact = periodic_report_markdown_renderer_adapter().render(document)

    result = registry.deliver(
        "lark_delivery",
        artifact,
        {
            "execute": True,
            "goal_id": "project-goal",
            "idempotency_key": "audience-live",
            "document": document,
            "audience_policy": _audience_policy(),
        },
    )

    assert result["status"] == "sent"
    assert rendered_recipient_ids == ["incident_owner", "routing_owner"]
    card_markdown = sent_cards[0]["elements"][0]["text"]["content"]
    assert '<at user_id="incident_owner">' in card_markdown
    assert '<at user_id="routing_owner">' in card_markdown
    assert "unrelated_owner" not in card_markdown


def test_lark_unrelated_report_sends_without_mentions() -> None:
    sent_cards: list[dict[str, Any]] = []
    rendered_recipient_ids: list[str] = []
    registry = _registry(
        sent_cards=sent_cards,
        rendered_recipient_ids=rendered_recipient_ids,
    )
    document = _document()
    artifact = periodic_report_markdown_renderer_adapter().render(document)
    policy = {
        "schema_version": "periodic_report_audience_policy_v0",
        "recipients": [
            {"recipient_id": "docs_owner", "owned_domains": ["documentation"]}
        ],
    }

    result = registry.deliver(
        "lark_delivery",
        artifact,
        {
            "execute": True,
            "goal_id": "project-goal",
            "idempotency_key": "unrelated-live",
            "document": document,
            "audience_policy": policy,
        },
    )

    assert result["status"] == "sent"
    assert result["announcement_plan"]["status"] == "no_relevant_recipient"
    assert rendered_recipient_ids == []
    assert "<at" not in sent_cards[0]["elements"][0]["text"]["content"]


def test_lark_matched_recipient_without_renderer_fails_before_send() -> None:
    sent_cards: list[dict[str, Any]] = []
    rendered_recipient_ids: list[str] = []
    registry = _registry(
        sent_cards=sent_cards,
        rendered_recipient_ids=rendered_recipient_ids,
        with_renderer=False,
    )
    document = _document()
    artifact = periodic_report_markdown_renderer_adapter().render(document)

    with pytest.raises(ValueError, match="require render_recipient_mention"):
        registry.deliver(
            "lark_delivery",
            artifact,
            {
                "execute": True,
                "goal_id": "project-goal",
                "idempotency_key": "missing-renderer",
                "document": document,
                "audience_policy": _audience_policy(),
            },
        )
    assert sent_cards == []


def test_lark_manual_mention_markup_cannot_bypass_audience_policy() -> None:
    sent_cards: list[dict[str, Any]] = []
    rendered_recipient_ids: list[str] = []
    registry = _registry(
        sent_cards=sent_cards,
        rendered_recipient_ids=rendered_recipient_ids,
    )
    artifact = periodic_report_markdown_renderer_adapter().render(_document())

    with pytest.raises(ValueError, match="must not contain Lark mention markup"):
        registry.deliver(
            "lark_delivery",
            artifact,
            {
                "execute": True,
                "goal_id": "project-goal",
                "idempotency_key": "manual-mention",
                "title": '<at user_id="unrelated_owner">owner</at>',
            },
        )
    assert sent_cards == []

"""Thin pytest: content ops item lifecycle — stable identity, state machine,
revision-bound approval, delivery/readback receipts, supersession, idempotency.

Covers GH-C78 core assertions.
"""

from __future__ import annotations

import json
import re

import pytest

from loopx.capabilities.content_ops.item_lifecycle import (
    apply_content_ops_item_event,
    build_content_ops_item,
    build_content_ops_item_packet,
    build_content_ops_queue_projection,
    build_content_ops_queue_status_packet,
    project_content_ops_item,
    render_content_ops_item_packet_markdown,
    render_content_ops_queue_status_markdown,
    validate_content_ops_item,
)

DIGEST_V1 = "sha256:" + "1" * 64
DIGEST_V2 = "sha256:" + "2" * 64

_PRIVATE_RE = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\bBearer" + r"\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def _public_safe(obj: object) -> bool:
    text = json.dumps(obj, sort_keys=True) if not isinstance(obj, str) else obj
    return not any(p.search(text) for p in _PRIVATE_RE)


def _item(**kw):
    defaults = {
        "item_id": "test-item", "item_kind": "reply", "channel": "x",
        "content_digest": DIGEST_V1, "content_ref": "draft:test-item",
        "source_refs": ["source:test"], "created_at": "2026-08-03T09:00:00+08:00",
    }
    defaults.update(kw)
    return build_content_ops_item(**defaults)


def _event(item, event_id, action, payload=None, occurred_at="2026-08-03T09:05:00+08:00"):
    return {"event_id": event_id, "action": action,
            "expected_state": item["state"], "expected_revision": item["revision"],
            "occurred_at": occurred_at, "payload": payload or {}}


def _apply(item, event_id, action, payload=None, **kw):
    packet = apply_content_ops_item_event(item, _event(item, event_id, action, payload, **kw))
    assert packet["external_writes_performed"] is False
    assert packet["autopublish_allowed"] is False
    return packet["item"]


class TestStableItemIdentity:
    def test_created_item_has_all_identity_fields(self):
        item = _item()
        assert item["schema_version"].startswith("content_ops_item_v")
        assert item["item_id"] == "test-item"
        assert item["item_kind"] == "reply"
        assert item["state"] == "captured"
        assert item["revision"] == 1
        assert item["content_digest"] == DIGEST_V1
        assert item["approval"] is None
        assert item["delivery_intent"] is None
        assert item["delivery_receipt"] is None
        assert item["readback_receipt"] is None
        assert item["autopublish_allowed"] is False
        assert item["created_at"] == item["updated_at"]
        assert _public_safe(item)

    def test_item_packet_boundary_flags(self):
        packet = build_content_ops_item_packet(
            item_id="p1", item_kind="post", channel="x",
            content_digest=DIGEST_V1, content_ref="draft:p1",
            created_at="2026-08-03T09:00:00+08:00")
        assert packet["ok"] is True
        assert packet["external_reads_performed"] is False
        assert packet["external_writes_performed"] is False
        assert packet["autopublish_allowed"] is False
        assert packet["projection"]["state"] == "captured"
        assert "revise" in packet["projection"]["next_actions"]
        assert _public_safe(packet)


class TestLifecycleStateMachine:
    def test_full_lifecycle_to_readback(self):
        item = _apply(_item(), "ev1", "submit_review")
        assert item["state"] == "review_ready"

        item = _apply(item, "ev2", "approve", {
            "approval_ref": "decision:test", "revision": 1,
            "content_digest": DIGEST_V1, "effect_kind": "reply"})
        assert item["state"] == "approved"
        assert item["approval"]["effect_kind"] == "reply"

        item = _apply(item, "ev3", "set_delivery_intent", {
            "provider_id": "p", "effect_kind": "reply",
            "account_ref": "account:maintainer"})
        assert item["state"] == "delivery_ready"

        item = _apply(item, "ev4", "record_delivery", {
            "provider_id": "p", "effect_kind": "reply",
            "content_digest": DIGEST_V1,
            "public_url": "https://x.com/example/status/123",
            "receipt_ref": "receipt:x-123"},
            occurred_at="2026-08-03T10:00:00+08:00")
        assert item["state"] == "published"
        assert item["delivery_receipt"]["public_url"] == "https://x.com/example/status/123"

        item = _apply(item, "ev5", "verify_readback", {
            "public_url": "https://x.com/example/status/123",
            "content_digest": DIGEST_V1, "readback_ref": "rb:x-123"},
            occurred_at="2026-08-03T10:01:00+08:00")
        assert item["state"] == "readback_verified"

        proj = project_content_ops_item(item)
        assert proj["terminal"] is True
        assert proj["readback_verified"] is True
        assert proj["next_actions"] == []

    def test_skip_from_captured(self):
        item = _apply(_item(), "ev-skip", "skip", {"reason": "No longer relevant."})
        assert item["state"] == "skipped"
        assert item["terminal_reason"] == "No longer relevant."
        assert project_content_ops_item(item)["terminal"] is True

    def test_revoke_approval(self):
        item = _apply(_item(), "ev1", "submit_review")
        item = _apply(item, "ev2", "approve", {
            "approval_ref": "d:test", "revision": 1,
            "content_digest": DIGEST_V1, "effect_kind": "reply"})
        item = _apply(item, "ev3", "revoke_approval", {"reason": "Window expired."})
        assert item["state"] == "review_ready"
        assert item["approval"] is None
        assert item["delivery_receipt"] is None


class TestRevisionInvalidation:
    def test_revise_clears_approval_and_delivery(self):
        item = _apply(_item(), "ev1", "submit_review")
        item = _apply(item, "ev2", "approve", {
            "approval_ref": "d:test", "revision": 1,
            "content_digest": DIGEST_V1, "effect_kind": "reply"})
        assert item["approval"] is not None

        item = _apply(item, "ev3", "revise", {
            "content_digest": DIGEST_V2, "content_ref": "draft:test-v2"})
        assert item["state"] == "draft"
        assert item["revision"] == 2
        assert item["content_digest"] == DIGEST_V2
        assert item["approval"] is None
        assert item["delivery_intent"] is None
        assert item["delivery_receipt"] is None
        assert item["readback_receipt"] is None


class TestSupersession:
    def test_superseded_is_terminal_and_rejects_further_events(self):
        item = _apply(_item(), "ev-s", "supersede", {
            "successor_item_id": "item-v2",
            "reason": "Newer draft replaces this."})
        assert item["state"] == "superseded"
        assert item["superseded_by"] == "item-v2"
        assert project_content_ops_item(item)["terminal"] is True

        with pytest.raises(ValueError, match="submit_review is not allowed from superseded"):
            _apply(item, "ev-x", "submit_review")


class TestFailClosed:
    def test_approval_wrong_revision_fails(self):
        item = _apply(_item(), "ev1", "submit_review")
        with pytest.raises(ValueError, match="revision"):
            _apply(item, "ev-bad", "approve", {
                "approval_ref": "d:test", "revision": 99,
                "content_digest": DIGEST_V1, "effect_kind": "reply"})

    def test_approval_wrong_digest_fails(self):
        item = _apply(_item(), "ev1", "submit_review")
        with pytest.raises(ValueError, match="content_digest"):
            _apply(item, "ev-bad", "approve", {
                "approval_ref": "d:test", "revision": 1,
                "content_digest": DIGEST_V2, "effect_kind": "reply"})

    def test_validation_rejects_forged_state(self):
        forged = _item()
        forged["state"] = "published"
        v = validate_content_ops_item(forged)
        assert v["ok"] is False
        assert "published item requires approval" in v["errors"][0]

    def test_validation_rejects_embedded_bodies(self):
        embedded = _item()
        embedded["post_body"] = "private draft body"
        v = validate_content_ops_item(embedded)
        assert v["ok"] is False
        assert "unsupported fields" in v["errors"][0]


class TestIdempotency:
    def test_same_event_returns_already_applied(self):
        item = _item()
        event = _event(item, "ev-r", "submit_review")
        first = apply_content_ops_item_event(item, event)
        assert first["receipt"]["status"] == "applied"
        retried = apply_content_ops_item_event(first["item"], event)
        assert retried["receipt"]["status"] == "already_applied"

    def test_same_event_id_different_body_rejected(self):
        item = _item()
        event = _event(item, "ev-r", "submit_review")
        first = apply_content_ops_item_event(item, event)
        changed = dict(event)
        changed["occurred_at"] = "2026-08-03T09:06:00+08:00"
        with pytest.raises(ValueError, match="different content"):
            apply_content_ops_item_event(first["item"], changed)


class TestQueueProjection:
    def test_queue_ordering_and_counts(self):
        a = _item(item_id="item-a")
        b = _item(item_id="item-b")
        c = _apply(_item(item_id="item-c"), "ev1", "submit_review")
        proj = build_content_ops_queue_projection(
            items=[a, b, c], queue_id="q",
            generated_at="2026-08-03T10:00:00+08:00")
        assert proj["item_count"] == 3
        assert proj["terminal_count"] == 0
        assert proj["counts"]["captured"] == 2
        assert proj["counts"]["review_ready"] == 1
        assert proj["items"][0]["priority_index"] == 1
        assert proj["next_action"]["item_id"] == "item-a"
        assert proj["truth_contract"]["projection_is_writable"] is False
        assert _public_safe(proj)

    def test_queue_status_packet_read_only(self):
        item = _item(item_id="t1")
        packet = build_content_ops_queue_status_packet(items=[item], queue_id="q")
        assert packet["ok"] is True
        assert packet["external_reads_performed"] is False
        assert packet["external_writes_performed"] is False
        assert _public_safe(packet)


class TestMarkdownRendering:
    def test_item_markdown_public_safe(self):
        packet = build_content_ops_item_packet(
            item_id="md-test", item_kind="article", channel="x",
            content_digest=DIGEST_V1, content_ref="draft:md-test",
            created_at="2026-08-03T09:00:00+08:00")
        md = render_content_ops_item_packet_markdown(packet)
        assert "md-test" in md
        assert "captured" in md
        assert _public_safe(md)

    def test_queue_markdown_public_safe(self):
        queue = build_content_ops_queue_status_packet(items=[_item(item_id="q-item")])
        md = render_content_ops_queue_status_markdown(queue)
        assert "q-item" in md
        assert _public_safe(md)

#!/usr/bin/env python3
"""Synthetic walkthrough for content_ops_item_v0 lifecycle.

GH-C78: Prove stable item identity, revision-bound approval invalidation,
delivery/readback receipts, and supersession.
Keep provider calls, draft bodies, credentials, private locators, and
publish authority outside the fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.content_ops.item_lifecycle import (  # noqa: E402
    apply_content_ops_item_event,
    build_content_ops_item,
    project_content_ops_item,
    validate_content_ops_item,
)

DIGEST_V1 = "sha256:" + "1" * 64
DIGEST_V2 = "sha256:" + "2" * 64


def _event(
    item: dict[str, object],
    event_id: str,
    action: str,
    payload: dict[str, object] | None = None,
    occurred_at: str = "2026-08-03T09:05:00+08:00",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "action": action,
        "expected_state": item["state"],
        "expected_revision": item["revision"],
        "occurred_at": occurred_at,
        "payload": payload or {},
    }


def _apply(
    item: dict[str, object],
    event_id: str,
    action: str,
    payload: dict[str, object] | None = None,
    occurred_at: str = "2026-08-03T09:05:00+08:00",
) -> dict[str, object]:
    packet = apply_content_ops_item_event(
        item,
        _event(item, event_id, action, payload, occurred_at),
    )
    assert packet["external_writes_performed"] is False
    return packet["item"]


def main() -> None:
    # ── 1. Item identity: build and validate ────────────────────────────
    item = build_content_ops_item(
        item_id="partner-launch-reply-v1",
        item_kind="reply",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:partner-launch-reply-v1",
        source_refs=["source:partner-launch-post"],
        created_at="2026-08-03T09:00:00+08:00",
    )

    assert item["item_id"] == "partner-launch-reply-v1"
    assert item["item_kind"] == "reply"
    assert item["state"] == "captured"
    assert item["revision"] == 1
    assert item["content_digest"] == DIGEST_V1
    assert item["content_ref"] == "draft:partner-launch-reply-v1"
    assert item["approval"] is None
    assert item["delivery_intent"] is None
    assert item["delivery_receipt"] is None
    assert item["readback_receipt"] is None
    print("  1. Stable item identity and initial state: ok")

    # Initial validation passes
    initial_validation = validate_content_ops_item(item)
    assert initial_validation["ok"] is True, initial_validation
    print("  2. Initial validation passes: ok")

    # ── 3. Submit review ────────────────────────────────────────────────
    item = _apply(item, "event-review", "submit_review")
    assert item["state"] == "review_ready"
    projection = project_content_ops_item(item)
    assert projection["state"] == "review_ready"
    assert projection["terminal"] is False
    print("  3. Submit review → review_ready: ok")

    # ── 4. Approve with content-digest binding ──────────────────────────
    item = _apply(
        item,
        "event-approve",
        "approve",
        {
            "approval_ref": "decision:partner-launch-reply-v1",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
            "account_ref": "account:maintainer",
            "valid_from": "2026-08-03T09:00:00+08:00",
            "valid_until": "2026-08-03T12:00:00+08:00",
        },
    )
    assert item["state"] == "approved"
    assert item["approval"] is not None
    assert item["approval"]["content_digest"] == DIGEST_V1
    assert item["approval"]["valid_until"] is not None
    print("  4. Approval bound to exact content-digest and revision: ok")

    # ── 5. Set delivery intent ──────────────────────────────────────────
    item = _apply(
        item,
        "event-intent",
        "set_delivery_intent",
        {
            "provider_id": "ego-lite",
            "effect_kind": "reply",
            "account_ref": "account:maintainer",
            "not_before": "2026-08-03T09:30:00+08:00",
            "not_after": "2026-08-03T11:00:00+08:00",
        },
    )
    assert item["state"] == "delivery_ready"
    assert item["delivery_intent"]["provider_id"] == "ego-lite"
    print("  5. Delivery intent set → delivery_ready: ok")

    # ── 6. Record delivery ──────────────────────────────────────────────
    item = _apply(
        item,
        "event-delivery",
        "record_delivery",
        {
            "provider_id": "ego-lite",
            "effect_kind": "reply",
            "account_ref": "account:maintainer",
            "content_digest": DIGEST_V1,
            "public_url": "https://x.com/example/status/123",
            "receipt_ref": "receipt:x-reply-123",
        },
        occurred_at="2026-08-03T10:00:00+08:00",
    )
    assert item["state"] == "published"
    assert item["delivery_receipt"]["public_url"] == "https://x.com/example/status/123"
    print("  6. Delivery receipt → published: ok")

    # ── 7. Verify readback ──────────────────────────────────────────────
    item = _apply(
        item,
        "event-readback",
        "verify_readback",
        {
            "public_url": "https://x.com/example/status/123",
            "content_digest": DIGEST_V1,
            "readback_ref": "readback:x-reply-123",
        },
        occurred_at="2026-08-03T10:01:00+08:00",
    )
    assert item["state"] == "readback_verified"
    assert item["readback_receipt"]["content_digest"] == DIGEST_V1

    projection = project_content_ops_item(item)
    assert projection["terminal"] is True
    final_validation = validate_content_ops_item(item)
    assert final_validation["ok"] is True, final_validation
    print("  7. Readback verified → terminal state: ok")

    # ── 8. Revision invalidates prior approval ──────────────────────────
    # Start a new item to test revision invalidation
    item2 = build_content_ops_item(
        item_id="revision-test-v1",
        item_kind="reply",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:revision-test-v1",
        source_refs=[],
        created_at="2026-08-03T09:00:00+08:00",
    )
    item2 = _apply(item2, "ev-rev-review", "submit_review")
    item2 = _apply(
        item2,
        "ev-rev-approve",
        "approve",
        {
            "approval_ref": "decision:revision-test",
            "revision": 1,
            "content_digest": DIGEST_V1,
            "effect_kind": "reply",
        },
    )
    assert item2["state"] == "approved"
    assert item2["approval"] is not None

    # Revise: new content invalidates the old approval
    item2 = _apply(
        item2,
        "ev-rev-revise",
        "revise",
        {
            "content_digest": DIGEST_V2,
            "content_ref": "draft:revision-test-v2",
        },
    )
    assert item2["state"] == "draft"
    assert item2["revision"] == 2
    assert item2["approval"] is None
    assert item2["delivery_intent"] is None
    print("  8. Revision invalidates prior approval and delivery intent: ok")

    # ── 9. Idempotent event replay ──────────────────────────────────────
    item3 = build_content_ops_item(
        item_id="idempotent-test",
        item_kind="reply",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:idempotent-test",
        source_refs=[],
        created_at="2026-08-03T09:00:00+08:00",
    )
    event = _event(item3, "ev-idem-review", "submit_review")
    first = apply_content_ops_item_event(item3, event)
    assert first["receipt"]["status"] == "applied"

    # Replay same event
    retried = apply_content_ops_item_event(first["item"], event)
    assert retried["receipt"]["status"] == "already_applied"
    print("  9. Event replay is idempotent: ok")

    # ── 10. Supersede: terminal with successor link ─────────────────────
    item4 = build_content_ops_item(
        item_id="supersede-test-v1",
        item_kind="reply",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:supersede-test-v1",
        source_refs=[],
        created_at="2026-08-03T09:00:00+08:00",
    )
    item4 = _apply(
        item4,
        "ev-supersede",
        "supersede",
        {
            "successor_item_id": "supersede-test-v2",
            "reason": "A newer draft replaces this review packet.",
        },
    )
    assert item4["state"] == "superseded"
    assert item4["superseded_by"] == "supersede-test-v2"
    projection = project_content_ops_item(item4)
    assert projection["terminal"] is True
    assert projection["next_actions"] == []
    print("  10. Supersede → terminal with successor link: ok")

    # ── 11. Public-safety: validate rejects embedded bodies and forged state ──
    forged = build_content_ops_item(
        item_id="forged-test",
        item_kind="reply",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:forged-test",
        source_refs=[],
        created_at="2026-08-03T09:00:00+08:00",
    )
    forged["state"] = "published"
    forged_validation = validate_content_ops_item(forged)
    assert forged_validation["ok"] is False
    assert any("published item requires approval" in e for e in forged_validation["errors"])

    embedded = build_content_ops_item(
        item_id="embedded-test",
        item_kind="reply",
        channel="x",
        content_digest=DIGEST_V1,
        content_ref="draft:embedded-test",
        source_refs=[],
        created_at="2026-08-03T09:00:00+08:00",
    )
    embedded["post_body"] = "private draft body"
    emb_validation = validate_content_ops_item(embedded)
    assert emb_validation["ok"] is False
    assert any("unsupported fields" in e for e in emb_validation["errors"])
    print("  11. Validation rejects forged state and embedded bodies: ok")

    print("\ncontent-ops-item-lifecycle-walkthrough ok")


if __name__ == "__main__":
    main()

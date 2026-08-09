from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from loopx.capabilities.content_ops.item_lifecycle import (
    apply_content_ops_item_event,
    build_content_ops_item,
    build_content_ops_queue_status_packet,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "a" * 64


def _item(item_id: str, item_kind: str = "post") -> dict[str, object]:
    return build_content_ops_item(
        item_id=item_id,
        item_kind=item_kind,
        channel="x",
        content_digest=DIGEST,
        content_ref=f"draft:{item_id}",
        source_refs=["source:public-feed"],
        created_at="2026-08-10T02:00:00+08:00",
    )


def _review_ready(item: dict[str, object]) -> dict[str, object]:
    return apply_content_ops_item_event(
        item,
        {
            "event_id": f"review:{item['item_id']}",
            "action": "submit_review",
            "expected_state": item["state"],
            "expected_revision": item["revision"],
            "occurred_at": "2026-08-10T02:05:00+08:00",
            "payload": {},
        },
    )["item"]


def _draft(item: dict[str, object]) -> dict[str, object]:
    return apply_content_ops_item_event(
        item,
        {
            "event_id": f"draft:{item['item_id']}",
            "action": "revise",
            "expected_state": item["state"],
            "expected_revision": item["revision"],
            "occurred_at": "2026-08-10T02:04:00+08:00",
            "payload": {
                "content_digest": item["content_digest"],
                "content_ref": item["content_ref"],
            },
        },
    )["item"]


def test_queue_projection_orders_actionable_items_and_counts_states() -> None:
    review = _review_ready(_item("community-recap-v1"))
    draft = _draft(_item("runta-post-v1"))
    packet = build_content_ops_queue_status_packet(
        items=[review, draft],
        queue_id="x-test-queue",
        generated_at="2026-08-10T02:10:00+08:00",
    )

    projection = packet["projection"]
    assert projection["queue_id"] == "x-test-queue"
    assert projection["item_count"] == 2
    assert projection["counts"] == {"review_ready": 1, "draft": 1}
    assert projection["terminal_count"] == 0
    assert projection["next_action"]["item_id"] == "community-recap-v1"
    assert projection["items"][0]["priority_index"] == 1
    assert projection["items"][1]["priority_index"] == 2
    assert packet["external_reads_performed"] is False
    assert packet["external_writes_performed"] is False
    assert packet["autopublish_allowed"] is False


def test_queue_projection_is_idle_when_all_items_are_terminal() -> None:
    item = apply_content_ops_item_event(
        _item("old-post-v1"),
        {
            "event_id": "skip:old-post-v1",
            "action": "skip",
            "expected_state": "captured",
            "expected_revision": 1,
            "occurred_at": "2026-08-10T02:05:00+08:00",
            "payload": {"reason": "Superseded by a newer draft."},
        },
    )["item"]

    projection = build_content_ops_queue_status_packet(
        items=[item],
        queue_id="x-test-queue",
        generated_at="2026-08-10T02:10:00+08:00",
    )["projection"]

    assert projection["terminal_count"] == 1
    assert projection["next_action"] is None


def test_queue_projection_rejects_unknown_item_fields() -> None:
    item = dict(_item("bad-item-v1"))
    item["draft_body"] = "must stay outside LoopX state"

    with pytest.raises(ValueError, match="unsupported fields"):
        build_content_ops_queue_status_packet(
            items=[item],
            queue_id="x-test-queue",
            generated_at="2026-08-10T02:10:00+08:00",
        )


def test_queue_status_cli_projects_items_without_external_effects(
    tmp_path: Path,
) -> None:
    item = _review_ready(_item("community-recap-v1"))
    item_path = tmp_path / "item.json"
    item_path.write_text(json.dumps(item), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--format",
            "json",
            "content-ops",
            "queue-status",
            "--item-json",
            str(item_path),
            "--queue-id",
            "x-test-queue",
            "--generated-at",
            "2026-08-10T02:10:00+08:00",
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["projection"]["next_action"]["item_id"] == "community-recap-v1"
    assert payload["external_writes_performed"] is False

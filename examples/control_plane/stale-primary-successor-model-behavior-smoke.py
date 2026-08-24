#!/usr/bin/env python3
"""Qualify that the live weak/default model leaves a stale open primary."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from loopx.control_plane.testing.selected_todo_tool_behavior import (
    SELECTED_TODO_TOOL_FIXTURE_TODO_ID,
    DoubaoSelectedTodoToolBehaviorActor,
)

ATTEMPTS_REQUIRED = 3


def main() -> int:
    actor = DoubaoSelectedTodoToolBehaviorActor.from_environment()
    with tempfile.TemporaryDirectory(prefix="loopx-stale-primary-") as root:
        receipts = [
            actor.qualify(
                qualification_id=(
                    "stale-done-primary-visible-successor-live-v0-"
                    f"attempt-{attempt}"
                ),
                fixture_root=Path(root) / f"attempt-{attempt}",
                stale_done_primary_successor=True,
            )
            for attempt in range(1, ATTEMPTS_REQUIRED + 1)
        ]
    passed = all(
        receipt.get("qualification_passed") is True
        and receipt.get("selected_todo_id") == SELECTED_TODO_TOOL_FIXTURE_TODO_ID
        for receipt in receipts
    )
    summary = {
        "schema_version": "stale_primary_successor_model_behavior_smoke_v0",
        "qualification_passed": passed,
        "attempts_required": ATTEMPTS_REQUIRED,
        "attempts_completed": len(receipts),
        "actor_refs": sorted({str(receipt["actor_ref"]) for receipt in receipts}),
        "selected_todo_ids": [receipt.get("selected_todo_id") for receipt in receipts],
        "observed_tool_sequences": [
            receipt.get("observed_tool_sequence") for receipt in receipts
        ],
        "failure_codes": [
            receipt.get("failure_code")
            for receipt in receipts
            if receipt.get("failure_code") is not None
        ],
        "boundary": {
            "raw_prompts_persisted": False,
            "raw_provider_responses_persisted": False,
            "external_writes_executed": False,
            "fixture_writes_temporary": True,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

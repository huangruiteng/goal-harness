#!/usr/bin/env python3
"""Smoke-test the public quota allocation contract wording."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
QUOTA_DOC = REPO_ROOT / "docs" / "quota-allocation.md"
STATUS_CONTRACT = REPO_ROOT / "docs" / "status-data-contract.md"
SLOT_SPEND_FIXTURE = REPO_ROOT / "examples" / "quota-slot-spend-event.example.json"


def compact(text: str) -> str:
    return " ".join(text.split())


def assert_contains(text: str, needle: str, *, label: str) -> None:
    assert needle in text, f"{label} missing: {needle!r}"


def main() -> int:
    readme = compact(README.read_text(encoding="utf-8"))
    quota_doc = compact(QUOTA_DOC.read_text(encoding="utf-8"))
    status_contract = compact(STATUS_CONTRACT.read_text(encoding="utf-8"))

    assert_contains(quota_doc, "## Allocation Contract", label="quota doc")
    assert_contains(
        quota_doc,
        "`quota plan` reports an advisory next automatic turn",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "It does not grant permission, clear an operator gate, record human reward",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "keep `blocked_health`, `operator_gate`, `waiting`, `throttled`, and `paused` goals in their own lanes",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "only goals with `state=eligible` enter the eligible lane",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "sort eligible goals by effective `quota.compute`, highest first",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "set `summary.next_automatic_turn` to the first eligible goal, or `none`",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "If the guard returns `should_run=false`, the executor should skip delivery work",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "## Slot Spend Event Contract",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "`classification=quota_slot_spent` with a nested `quota_event` object",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "write only after a fresh `quota should-run` returned `should_run=true`",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "`after.spent_slots` must equal `before.spent_slots + slots`",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "do not include human reward, operator-gate approval, write-control, private evidence",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "Post-turn accounting protocol",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "append exactly one `quota spend-slot --execute` event for that completed turn",
        label="quota doc",
    )
    assert_contains(
        quota_doc,
        "do not append spend for `should_run=false` skips, preflight failures, pure dry-run previews",
        label="quota doc",
    )

    assert_contains(
        readme,
        "The `next_automatic_turn` reported by `quota plan` is only an advisory scheduling hint",
        label="README",
    )
    assert_contains(
        readme,
        "it chooses the highest-compute eligible goal",
        label="README",
    )
    assert_contains(
        readme,
        "operator-gated, waiting, throttled, paused, and health-blocked goals stay out of the eligible lane",
        label="README",
    )
    assert_contains(
        readme,
        "See `docs/quota-allocation.md` for the full allocation contract",
        label="README",
    )
    assert_contains(
        readme,
        "After an automatic turn actually spends delivery compute, append one spend event",
        label="README",
    )
    assert_contains(
        readme,
        "Do not append spend for `should_run=false` skips, preflight failures, or pure dry-run previews",
        label="README",
    )
    assert_contains(
        status_contract,
        "`goal-harness quota status` and `goal-harness quota plan` derive an agent-facing grouping from this same status payload",
        label="status contract",
    )
    assert_contains(
        status_contract,
        "`goal-harness quota should-run --goal-id <goal-id>` derives a per-goal automation guard from that grouping",
        label="status contract",
    )
    assert_contains(
        status_contract,
        "These are read-only views, not a separate source of truth",
        label="status contract",
    )
    assert_contains(
        status_contract,
        "Scripts should treat `summary.next_automatic_turn` in the quota-plan JSON as advisory",
        label="status contract",
    )
    assert_contains(
        status_contract,
        "still respect the displayed health, operator, and evidence gates",
        label="status contract",
    )
    assert_contains(
        status_contract,
        "In lane terms, `next_automatic_turn` may only name the first eligible goal",
        label="status contract",
    )
    assert_contains(
        status_contract,
        "operator-gated, waiting, throttled, paused, and health-blocked goals must stay out of the eligible lane",
        label="status contract",
    )

    fixture = json.loads(SLOT_SPEND_FIXTURE.read_text(encoding="utf-8"))
    quota_event = fixture["quota_event"]
    before = quota_event["before"]
    after = quota_event["after"]
    assert fixture["classification"] == "quota_slot_spent", fixture
    assert quota_event["event_type"] == "quota_slot_spent", fixture
    assert quota_event["source"] in {"heartbeat", "controller", "adapter"}, fixture
    assert quota_event["slots"] > 0, fixture
    assert before["should_run"] is True, fixture
    assert before["state"] == "eligible", fixture
    assert after["spent_slots"] == before["spent_slots"] + quota_event["slots"], fixture
    assert after["allowed_slots"] == before["allowed_slots"], fixture
    assert after["state"] == "throttled", fixture
    assert after["should_run"] is False, fixture
    forbidden = {"human_reward", "operator_gate", "write_control", "private_evidence", "agent_command"}
    assert forbidden.isdisjoint(fixture), fixture
    assert forbidden.isdisjoint(quota_event), fixture

    print("quota-contract-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

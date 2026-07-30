from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

from loopx.capabilities.issue_fix.candidate_evidence import (
    build_public_github_candidate_preflight_input,
    collect_public_github_candidate_preflight_input,
)
from loopx.capabilities.issue_fix.candidate_preflight import (
    build_issue_fix_candidate_preflight_packet,
)
from loopx.cli import build_parser, main as cli_main
from loopx.domain_packs.issue_fix import (
    upsert_issue_fix_candidate_preflight_ledger_jsonl,
)

GENERATED_AT = "2026-07-30T12:00:00Z"


def _source_receipts() -> dict[str, dict[str, object]]:
    return {
        field: {
            "provider": "github_graphql",
            "observed_at": GENERATED_AT,
            "query_fingerprint": f"sha256:{field}",
            "page_count": 1,
            "result_count": 0,
            "complete": True,
            "truncated": False,
            "raw_provider_payload_captured": False,
        }
        for field in ("numeric_pr_evidence", "semantic_pr_evidence")
    }


def test_candidate_evidence_distinguishes_closing_refs_from_cross_refs() -> None:
    payload = build_public_github_candidate_preflight_input(
        repo="volcengine/OpenViking",
        issue_ref="#3274",
        issue_state="OPEN",
        closing_pull_requests=[
            {
                "number": 3281,
                "state": "OPEN",
                "url": "https://github.com/volcengine/OpenViking/pull/3281",
                "headRefOid": "a" * 40,
            }
        ],
        cross_referenced_pull_requests=[
            {
                "source": {
                    "__typename": "PullRequest",
                    "number": 3281,
                    "state": "OPEN",
                    "url": "https://github.com/volcengine/OpenViking/pull/3281",
                    "headRefOid": "a" * 40,
                }
            },
            {
                "source": {
                    "__typename": "PullRequest",
                    "number": 3582,
                    "state": "OPEN",
                    "url": "https://github.com/volcengine/OpenViking/pull/3582",
                    "headRefOid": "b" * 40,
                }
            },
        ],
        maintainer_comments=[],
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )

    numeric = payload["numeric_pr_evidence"]["rows"]
    semantic = payload["semantic_pr_evidence"]["rows"]
    assert [row["pr_ref"] for row in numeric] == ["#3281"]
    assert [row["pr_ref"] for row in semantic] == ["#3582"]
    assert semantic[0]["current_revision_verified"] is False
    assert semantic[0]["revision"] == "b" * 40

    preflight = build_issue_fix_candidate_preflight_packet(
        repo="volcengine/OpenViking",
        issue_ref="#3274",
        input_payload=payload,
        generated_at=GENERATED_AT,
    )
    assert preflight["decision"]["route"] == "reuse_existing_pr"
    assert preflight["decision"]["existing_pr_refs"] == ["#3281"]
    assert (
        preflight["evidence"]["semantic_pr_candidates_unverified"][0]["pr_ref"]
        == "#3582"
    )
    assert preflight["evidence"]["source_receipt"]["provider"] == "github_graphql"


def test_maintainer_comment_requires_disposition_without_copying_body() -> None:
    payload = build_public_github_candidate_preflight_input(
        repo="volcengine/OpenViking",
        issue_ref="#1139",
        issue_state="OPEN",
        closing_pull_requests=[],
        cross_referenced_pull_requests=[],
        maintainer_comments=[
            {
                "authorAssociation": "COLLABORATOR",
                "url": (
                    "https://github.com/volcengine/OpenViking/issues/1139"
                    "#issuecomment-1"
                ),
                "body": "must not enter the receipt",
            }
        ],
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )

    assert payload["domain_state"]["route"] == "comment_only"
    assert "body" not in str(payload)
    preflight = build_issue_fix_candidate_preflight_packet(
        repo="volcengine/OpenViking",
        issue_ref="#1139",
        input_payload=payload,
        generated_at=GENERATED_AT,
    )
    assert preflight["decision"]["route"] == "comment_only"
    assert preflight["decision"]["reason_codes"] == [
        "maintainer_comment_requires_disposition"
    ]


def test_unverified_semantic_candidate_fails_closed() -> None:
    payload = build_public_github_candidate_preflight_input(
        repo="volcengine/OpenViking",
        issue_ref="#3305",
        issue_state="OPEN",
        closing_pull_requests=[],
        cross_referenced_pull_requests=[
            {
                "source": {
                    "__typename": "PullRequest",
                    "number": 3310,
                    "state": "OPEN",
                    "url": "https://github.com/volcengine/OpenViking/pull/3310",
                    "headRefOid": None,
                }
            }
        ],
        maintainer_comments=[],
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )

    preflight = build_issue_fix_candidate_preflight_packet(
        repo="volcengine/OpenViking",
        issue_ref="#3305",
        input_payload=payload,
        generated_at=GENERATED_AT,
    )
    assert preflight["decision"]["route"] == "comment_only"
    assert preflight["decision"]["reason_codes"] == [
        "semantic_candidate_requires_current_revision_verification"
    ]
    assert (
        preflight["evidence"]["semantic_pr_candidates_unverified"][0]["pr_ref"]
        == "#3310"
    )


def test_public_collector_requires_complete_paginated_queries() -> None:
    def pages(**kwargs: object) -> list[dict[str, object]]:
        operation = str(kwargs["operation"])
        if "closing" in operation:
            connection = "closedByPullRequestsReferences"
        elif "cross-reference" in operation:
            connection = "timelineItems"
        else:
            connection = "comments"
        return [
            {
                "data": {
                    "repository": {
                        "issue": {
                            "state": "OPEN",
                            connection: {
                                "nodes": [],
                                "pageInfo": {
                                    "hasNextPage": False,
                                    "endCursor": None,
                                },
                            },
                        }
                    }
                }
            }
        ]

    with patch(
        "loopx.capabilities.issue_fix.candidate_evidence._run_graphql_pages",
        side_effect=pages,
    ) as runner:
        payload = collect_public_github_candidate_preflight_input(
            repo="volcengine/OpenViking",
            issue_ref="#3305",
            generated_at=GENERATED_AT,
        )

    assert runner.call_count == 3
    assert payload["source_receipt"]["external_reads_performed"] is True
    assert payload["numeric_pr_evidence"]["rows"] == []
    assert payload["semantic_pr_evidence"]["rows"] == []


def test_workflow_cli_exposes_canonical_candidate_collector() -> None:
    args = build_parser().parse_args(
        [
            "issue-fix",
            "workflow-plan",
            "--url",
            "https://github.com/volcengine/OpenViking/issues/3305",
            "--fetch-candidate-evidence",
        ]
    )
    assert args.fetch_candidate_evidence is True
    assert args.candidate_evidence_timeout_seconds == 30


def test_workflow_cli_persists_non_proceed_candidate_receipt(
    tmp_path: Path,
) -> None:
    collected = build_public_github_candidate_preflight_input(
        repo="volcengine/OpenViking",
        issue_ref="#3274",
        issue_state="OPEN",
        closing_pull_requests=[
            {
                "number": 3281,
                "state": "OPEN",
                "url": "https://github.com/volcengine/OpenViking/pull/3281",
                "headRefOid": "a" * 40,
            }
        ],
        cross_referenced_pull_requests=[],
        maintainer_comments=[],
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )
    output = io.StringIO()
    with (
        patch(
            "loopx.capabilities.issue_fix.cli.collect_public_github_candidate_preflight_input",
            return_value=collected,
        ),
        contextlib.redirect_stdout(output),
    ):
        exit_code = cli_main(
            [
                "--registry",
                str(tmp_path / "registry.json"),
                "--format",
                "json",
                "issue-fix",
                "workflow-plan",
                "--url",
                "https://github.com/volcengine/OpenViking/issues/3274",
                "--fetch-candidate-evidence",
                "--goal-id",
                "issue-fix-goal",
                "--project",
                str(tmp_path),
            ]
        )

    assert exit_code == 0
    packet = json.loads(output.getvalue())
    preflight = packet["candidate_preflight"]
    assert preflight["decision"]["route"] == "reuse_existing_pr"
    assert preflight["domain_state_projection"]["write_performed"] is True
    ledger = (
        tmp_path
        / ".loopx"
        / "domain-state"
        / "issue-fix-goal"
        / "issue_fix"
        / "candidate-preflight.jsonl"
    )
    rows = ledger.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    durable = json.loads(rows[0])
    assert durable["decision"]["route"] == "reuse_existing_pr"
    assert durable["decision"]["existing_pr_refs"] == ["#3281"]
    second_write = upsert_issue_fix_candidate_preflight_ledger_jsonl(
        ledger,
        durable,
    )
    assert second_write["status"] == "updated"
    assert second_write["row_count"] == 1
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
    assert not ledger.with_name("feasibility.jsonl").exists()

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from loopx.capabilities.issue_fix.candidate_evidence import (
    _connection_projection,
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
REPO = "volcengine/OpenViking"
ISSUE = "#3305"
COMMENT_REF = f"https://github.com/{REPO}/issues/3305#comment"
_NO_CROSS_REF = object()


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
        for field in (
            "numeric_pr_evidence",
            "semantic_pr_evidence",
            "maintainer_comment_evidence",
        )
    }


def _resolution(
    *,
    repo: str,
    issue_ref: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": "issue_fix_candidate_resolution_v0",
        "repo": repo,
        "issue_ref": issue_ref,
        "rows": rows,
        "raw_content_captured": False,
    }


def _candidate_input(
    *,
    issue_ref: str = ISSUE,
    cross_revision: str | None | object = _NO_CROSS_REF,
    comment_ref: str | None = None,
) -> dict[str, object]:
    cross_refs = []
    if cross_revision is not _NO_CROSS_REF:
        cross_refs = [
            {
                "source": {
                    "__typename": "PullRequest",
                    "number": 3310,
                    "state": "OPEN",
                    "url": f"https://github.com/{REPO}/pull/3310",
                    "headRefOid": cross_revision,
                }
            }
        ]
    comments = (
        [
            {
                "authorAssociation": "OWNER",
                "url": comment_ref,
                "updatedAt": GENERATED_AT,
            }
        ]
        if comment_ref
        else []
    )
    return build_public_github_candidate_preflight_input(
        repo=REPO,
        issue_ref=issue_ref,
        issue_state="OPEN",
        closing_pull_requests=[],
        cross_referenced_pull_requests=cross_refs,
        maintainer_comments=comments,
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )


def _preflight(
    payload: dict[str, object] | None,
    *,
    issue_ref: str = ISSUE,
) -> dict[str, object]:
    return build_issue_fix_candidate_preflight_packet(
        repo=REPO,
        issue_ref=issue_ref,
        input_payload=payload,
        generated_at=GENERATED_AT,
    )


def _workflow_cli(
    args: list[str],
    *,
    collected: dict[str, object] | object = _NO_CROSS_REF,
) -> dict[str, object]:
    provider = (
        contextlib.nullcontext()
        if collected is _NO_CROSS_REF
        else patch(
            "loopx.capabilities.issue_fix.cli.collect_public_github_candidate_preflight_input",
            return_value=collected,
        )
    )
    output = io.StringIO()
    with provider, contextlib.redirect_stdout(output):
        assert cli_main(args) == 0
    return json.loads(output.getvalue())


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

    preflight = _preflight(payload, issue_ref="#3274")
    assert preflight["decision"]["route"] == "reuse_existing_pr"
    assert preflight["decision"]["existing_pr_refs"] == ["#3281"]
    assert (
        preflight["evidence"]["semantic_pr_candidates_unverified"][0]["pr_ref"]
        == "#3582"
    )
    assert (
        payload["maintainer_comment_evidence"]["source"]["provider"]
        == "github_graphql"
    )


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
                "updatedAt": GENERATED_AT,
                "body": "must not enter the receipt",
            }
        ],
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )

    assert payload["domain_state"]["route"] is None
    assert "body" not in str(payload)
    preflight = _preflight(payload, issue_ref="#1139")
    assert preflight["admission"]["state"] == "verification_required"
    assert preflight["decision"]["route"] is None
    assert preflight["decision"]["candidate_runnable"] is False
    assert preflight["decision"]["reason_codes"] == [
        "maintainer_comment_requires_disposition"
    ]
    assert preflight["admission"]["successors"][0]["action_kind"] == (
        "issue_fix_read_maintainer_disposition"
    )


def test_unverified_semantic_candidate_fails_closed() -> None:
    payload = _candidate_input(cross_revision="a" * 40)

    preflight = _preflight(payload)
    assert preflight["admission"]["state"] == "verification_required"
    assert preflight["decision"]["route"] is None
    assert preflight["decision"]["reason_codes"] == [
        "semantic_candidate_requires_current_revision_verification"
    ]
    assert (
        preflight["evidence"]["semantic_pr_candidates_unverified"][0]["pr_ref"]
        == "#3310"
    )
    assert preflight["evidence"]["semantic_implementation_checked"] is False
    assert preflight["evidence"]["maintainer_comments_checked"] is True
    assert preflight["admission"]["successors"][0]["action_kind"] == (
        "issue_fix_verify_pr_current_revision"
    )


def test_unconfigured_preflight_requires_evidence_and_is_not_runnable() -> None:
    preflight = _preflight(None)

    assert preflight["admission"]["state"] == "evidence_required"
    assert preflight["decision"]["route"] is None
    assert preflight["decision"]["candidate_runnable"] is False
    successor = preflight["admission"]["successors"][0]
    assert successor["action_kind"] == "issue_fix_collect_candidate_evidence"
    assert successor["target_key"] == (
        "volcengine/OpenViking:issues_3305:issue_fix_collect_candidate_evidence"
    )


def test_semantic_resolution_is_bound_to_the_current_pr_revision() -> None:
    payload = _candidate_input(cross_revision="a" * 40)
    payload["candidate_resolution"] = _resolution(
        repo=REPO,
        issue_ref=ISSUE,
        rows=[
            {
                "kind": "pr_revision",
                "ref": "#3310",
                "revision": "a" * 40,
                "outcome": "implementation",
            }
        ],
    )

    admitted = _preflight(payload)
    assert admitted["admission"]["state"] == "admitted"
    assert admitted["decision"]["route"] == "reuse_existing_pr"
    assert (
        admitted["evidence"]["semantic_pr_matches"][0]["verified_revision"] == "a" * 40
    )
    assert admitted["evidence"]["semantic_implementation_checked"] is True

    payload["semantic_pr_evidence"]["rows"][0]["revision"] = "b" * 40
    with pytest.raises(ValueError, match="current source revision"):
        _preflight(payload)


def test_non_implementation_and_non_blocking_comment_restore_admission() -> None:
    payload = _candidate_input(
        cross_revision="a" * 40,
        comment_ref=COMMENT_REF,
    )
    payload["candidate_resolution"] = _resolution(
        repo=REPO,
        issue_ref=ISSUE,
        rows=[
            {
                "kind": "pr_revision",
                "ref": "#3310",
                "revision": "a" * 40,
                "outcome": "not_implementation",
            },
            {
                "kind": "maintainer_comment",
                "ref": COMMENT_REF,
                "revision": GENERATED_AT,
                "outcome": "non_blocking",
            },
        ],
    )

    admitted = _preflight(payload)
    assert admitted["admission"] == {
        "state": "admitted",
        "evidence_complete": True,
        "final_decision_available": True,
        "successors": [],
    }
    assert admitted["decision"]["route"] == "proceed"
    assert admitted["decision"]["candidate_runnable"] is True
    assert {
        (row["kind"], row["outcome"])
        for row in admitted["evidence"]["candidate_resolutions"]
    } == {
        ("pr_revision", "not_implementation"),
        ("maintainer_comment", "non_blocking"),
    }


def test_maintainer_resolution_is_bound_to_comment_revision() -> None:
    payload = _candidate_input(comment_ref=COMMENT_REF)
    payload["candidate_resolution"] = _resolution(
        repo=REPO,
        issue_ref=ISSUE,
        rows=[
            {
                "kind": "maintainer_comment",
                "ref": COMMENT_REF,
                "revision": GENERATED_AT,
                "outcome": "non_blocking",
            }
        ],
    )

    admitted = _preflight(payload)
    assert admitted["decision"]["route"] == "proceed"

    payload["maintainer_comment_evidence"]["rows"][0]["revision"] = (
        "2026-07-30T01:00:00Z"
    )
    with pytest.raises(ValueError, match="current source comment revision"):
        _preflight(payload)


def test_maintainer_comment_blocks_reuse_until_disposition() -> None:
    payload = build_public_github_candidate_preflight_input(
        repo=REPO,
        issue_ref=ISSUE,
        issue_state="OPEN",
        closing_pull_requests=[
            {
                "number": 3311,
                "state": "OPEN",
                "url": f"https://github.com/{REPO}/pull/3311",
                "headRefOid": "c" * 40,
            }
        ],
        cross_referenced_pull_requests=[],
        maintainer_comments=[
            {
                "authorAssociation": "OWNER",
                "url": COMMENT_REF,
                "updatedAt": GENERATED_AT,
            }
        ],
        generated_at=GENERATED_AT,
        source_receipts=_source_receipts(),
    )

    preflight = _preflight(payload)
    assert preflight["admission"]["state"] == "verification_required"
    assert preflight["decision"]["route"] is None
    assert [row["action_kind"] for row in preflight["admission"]["successors"]] == [
        "issue_fix_read_maintainer_disposition"
    ]


@pytest.mark.parametrize(
    "rows,error",
    [
        ([{}], "repo must match"),
        (
            [
                {
                    "repo": "volcengine/OpenViking",
                    "pr_ref": "#3310",
                    "state": "UNKNOWN",
                    "closing_issue_refs": ["#3305"],
                }
            ],
            "state must be",
        ),
    ],
)
def test_malformed_source_rows_cannot_prove_a_negative(
    rows: list[dict[str, object]],
    error: str,
) -> None:
    payload = _candidate_input()
    payload["numeric_pr_evidence"]["rows"] = rows
    with pytest.raises((TypeError, ValueError), match=error):
        _preflight(payload)


def test_graphql_null_node_invalidates_query_completeness() -> None:
    pages = [
        {
            "data": {
                "repository": {
                    "issue": {
                        "state": "OPEN",
                        "timelineItems": {
                            "nodes": [None],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        },
                    }
                }
            }
        }
    ]
    with pytest.raises(TypeError, match="unparseable node"):
        _connection_projection(
            pages,
            connection="timelineItems",
            operation="candidate cross-reference read",
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
    assert payload["maintainer_comment_evidence"]["complete"] is True
    assert payload["maintainer_comment_evidence"]["source"][
        "query_fingerprint"
    ].startswith("sha256:")
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
    packet = _workflow_cli(
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
        ],
        collected=collected,
    )
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


def test_workflow_cli_persists_evidence_required_instead_of_false_proceed(
    tmp_path: Path,
) -> None:
    packet = _workflow_cli(
        [
            "--registry",
            str(tmp_path / "registry.json"),
            "--format",
            "json",
            "issue-fix",
            "workflow-plan",
            "--repo",
            REPO,
            "--issue-ref",
            ISSUE,
            "--goal-id",
            "issue-fix-goal",
            "--project",
            str(tmp_path),
        ]
    )
    preflight = packet["candidate_preflight"]
    assert packet["candidate_fix_workflow_allowed"] is False
    assert preflight["admission"]["state"] == "evidence_required"
    assert preflight["decision"]["route"] is None
    ledger = (
        tmp_path
        / ".loopx"
        / "domain-state"
        / "issue-fix-goal"
        / "issue_fix"
        / "candidate-preflight.jsonl"
    )
    durable = json.loads(ledger.read_text(encoding="utf-8"))
    assert durable["decision"]["candidate_runnable"] is False
    assert durable["admission"]["successors"][0]["action_kind"] == (
        "issue_fix_collect_candidate_evidence"
    )


def test_maintainer_comment_projects_read_gate_and_stable_successor(
    tmp_path: Path,
) -> None:
    collected = _candidate_input(comment_ref=COMMENT_REF)

    packets: list[dict[str, object]] = []
    for _ in range(2):
        packets.append(
            _workflow_cli(
                [
                    "--registry",
                    str(tmp_path / "registry.json"),
                    "--format",
                    "json",
                    "issue-fix",
                    "workflow-plan",
                    "--url",
                    "https://github.com/volcengine/OpenViking/issues/3305",
                    "--fetch-candidate-evidence",
                    "--no-write-domain-state",
                ],
                collected=collected,
            )
        )

    previews = packets[0]["ordered_loopx_todo_writeback_preview"]
    assert [preview["action_kind"] for preview in previews] == [
        "issue_fix_read_maintainer_disposition",
        "approve_github_issue_body_or_comment_read",
    ]
    assert (
        previews[0]["target_key"]
        == packets[1]["ordered_loopx_todo_writeback_preview"][0]["target_key"]
    )
    assert "sha256:" in previews[0]["target_key"]
    assert "at evidence revision sha256:" in previews[0]["text"]
    assert packets[0]["first_screen"]["top_gate"]["gated_fields"] == ["comments"]

    changed = _candidate_input(comment_ref=COMMENT_REF)
    changed["maintainer_comment_evidence"]["rows"][0]["revision"] = (
        "2026-07-30T01:00:00Z"
    )
    changed_packet = _workflow_cli(
        [
            "--registry",
            str(tmp_path / "registry.json"),
            "--format",
            "json",
            "issue-fix",
            "workflow-plan",
            "--url",
            "https://github.com/volcengine/OpenViking/issues/3305",
            "--fetch-candidate-evidence",
            "--no-write-domain-state",
        ],
        collected=changed,
    )
    changed_preview = changed_packet["ordered_loopx_todo_writeback_preview"][0]
    assert changed_preview["target_key"] != previews[0]["target_key"]
    assert changed_preview["text"] != previews[0]["text"]

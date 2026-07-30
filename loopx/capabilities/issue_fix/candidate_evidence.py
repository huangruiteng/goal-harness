from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .candidate_preflight import (
    ISSUE_FIX_CANDIDATE_PREFLIGHT_INPUT_SCHEMA_VERSION,
)
from .metadata_preview import normalise_github_issue_reference

ISSUE_FIX_CANDIDATE_EVIDENCE_SOURCE_SCHEMA_VERSION = (
    "issue_fix_candidate_evidence_source_v0"
)
_MAINTAINER_ASSOCIATIONS = {"COLLABORATOR", "MEMBER", "OWNER"}

_CLOSING_PULL_REQUESTS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$endCursor:String) {
  repository(owner:$owner,name:$name) {
    issue(number:$number) {
      state
      closedByPullRequestsReferences(
        first:100,
        after:$endCursor,
        includeClosedPrs:true
      ) {
        nodes { number state url headRefOid }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

_CROSS_REFERENCED_PULL_REQUESTS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$endCursor:String) {
  repository(owner:$owner,name:$name) {
    issue(number:$number) {
      state
      timelineItems(
        first:100,
        after:$endCursor,
        itemTypes:[CROSS_REFERENCED_EVENT]
      ) {
        nodes {
          ... on CrossReferencedEvent {
            source {
              __typename
              ... on PullRequest { number state url headRefOid }
            }
          }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

_MAINTAINER_COMMENTS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$endCursor:String) {
  repository(owner:$owner,name:$name) {
    issue(number:$number) {
      state
      comments(first:100,after:$endCursor) {
        nodes { authorAssociation url updatedAt }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def _query_fingerprint(query: str) -> str:
    canonical = " ".join(query.split())
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _run_graphql_pages(
    *,
    query: str,
    owner: str,
    name: str,
    number: int,
    timeout_seconds: float,
    operation: str,
) -> list[dict[str, Any]]:
    gh = shutil.which("gh")
    if not gh:
        raise ValueError("public GitHub candidate evidence requires GitHub CLI `gh`")
    try:
        completed = subprocess.run(
            [
                gh,
                "api",
                "graphql",
                "--paginate",
                "--slurp",
                "-f",
                f"query={query}",
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={number}",
            ],
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(f"public GitHub {operation} failed") from None
    if completed.returncode != 0:
        raise ValueError(f"public GitHub {operation} failed")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        raise ValueError(f"public GitHub {operation} returned invalid JSON") from None
    pages = payload if isinstance(payload, list) else [payload]
    if not pages or any(not isinstance(page, Mapping) for page in pages):
        raise ValueError(f"public GitHub {operation} returned invalid pages")
    return [dict(page) for page in pages]


def _connection_projection(
    pages: Sequence[Mapping[str, Any]],
    *,
    connection: str,
    operation: str,
) -> tuple[str, list[dict[str, Any]]]:
    issue_state: str | None = None
    rows: list[dict[str, Any]] = []
    final_page_info: Mapping[str, Any] | None = None
    for page in pages:
        issue = ((page.get("data") or {}).get("repository") or {}).get("issue")
        if issue is None:
            raise ValueError(f"public GitHub {operation} did not find the issue")
        if not isinstance(issue, Mapping):
            raise TypeError(f"public GitHub {operation} returned invalid issue")
        state = str(issue.get("state") or "").strip().upper()
        if state not in {"OPEN", "CLOSED"}:
            raise ValueError(f"public GitHub {operation} returned invalid issue state")
        if issue_state not in {None, state}:
            raise ValueError(f"public GitHub {operation} changed issue state mid-read")
        issue_state = state
        projection = issue.get(connection)
        if not isinstance(projection, Mapping):
            raise TypeError(f"public GitHub {operation} omitted {connection}")
        nodes = projection.get("nodes")
        if not isinstance(nodes, list):
            raise TypeError(f"public GitHub {operation} returned invalid nodes")
        rows.extend(dict(node) for node in nodes if isinstance(node, Mapping))
        page_info = projection.get("pageInfo")
        if not isinstance(page_info, Mapping):
            raise TypeError(f"public GitHub {operation} omitted pageInfo")
        final_page_info = page_info
    if final_page_info is None or final_page_info.get("hasNextPage") is not False:
        raise ValueError(f"public GitHub {operation} was truncated")
    return issue_state or "CLOSED", rows


def _source_projection(
    *,
    query: str,
    observed_at: str,
    page_count: int,
    result_count: int,
) -> dict[str, Any]:
    return {
        "provider": "github_graphql",
        "observed_at": observed_at,
        "query_fingerprint": _query_fingerprint(query),
        "page_count": page_count,
        "result_count": result_count,
        "complete": True,
        "truncated": False,
        "raw_provider_payload_captured": False,
    }


def build_public_github_candidate_preflight_input(
    *,
    repo: str,
    issue_ref: str,
    issue_state: str,
    closing_pull_requests: Sequence[Mapping[str, Any]],
    cross_referenced_pull_requests: Sequence[Mapping[str, Any]],
    maintainer_comments: Sequence[Mapping[str, Any]],
    generated_at: str,
    source_receipts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    reference = normalise_github_issue_reference(
        repo=repo,
        issue_ref=issue_ref,
        url=None,
    )
    canonical_repo = str(reference["repo"])
    canonical_issue = str(reference["issue_ref"])
    number = reference.get("number")
    if not isinstance(number, int):
        raise TypeError("candidate evidence requires a numeric GitHub issue")
    state = str(issue_state or "").strip().upper()
    if state not in {"OPEN", "CLOSED"}:
        raise ValueError("candidate evidence issue_state must be OPEN or CLOSED")

    numeric_by_number: dict[int, dict[str, Any]] = {}
    for raw in closing_pull_requests:
        pr_number = raw.get("number")
        if not isinstance(pr_number, int) or pr_number <= 0:
            continue
        numeric_by_number[pr_number] = {
            "repo": canonical_repo,
            "pr_ref": f"#{pr_number}",
            "state": str(raw.get("state") or "UNKNOWN").upper(),
            "url": str(raw.get("url") or ""),
            "closing_issue_refs": [canonical_issue],
            "revision": str(raw.get("headRefOid") or "") or None,
        }

    semantic_by_number: dict[int, dict[str, Any]] = {}
    for raw in cross_referenced_pull_requests:
        source = raw.get("source") if isinstance(raw.get("source"), Mapping) else raw
        if source.get("__typename") not in {None, "PullRequest"}:
            continue
        pr_number = source.get("number")
        if (
            not isinstance(pr_number, int)
            or pr_number <= 0
            or pr_number in numeric_by_number
        ):
            continue
        revision = str(source.get("headRefOid") or "").strip()
        semantic_by_number[pr_number] = {
            "repo": canonical_repo,
            "pr_ref": f"#{pr_number}",
            "state": str(source.get("state") or "UNKNOWN").upper(),
            "url": str(source.get("url") or ""),
            "related_issue_refs": [canonical_issue],
            "relation": "fix_candidate",
            # A cross-reference and a current head OID prove that the candidate
            # exists, not that its current revision implements this issue.
            "current_revision_verified": False,
            "revision": revision or None,
        }

    maintainer_comment_refs = sorted(
        {
            str(comment.get("url") or "").strip()
            for comment in maintainer_comments
            if str(comment.get("authorAssociation") or "").upper()
            in _MAINTAINER_ASSOCIATIONS
            and str(comment.get("url") or "").strip()
        }
    )
    domain_route = "comment_only" if maintainer_comment_refs else "proceed"
    return {
        "schema_version": ISSUE_FIX_CANDIDATE_PREFLIGHT_INPUT_SCHEMA_VERSION,
        "domain_state": {
            "repo": canonical_repo,
            "issue_ref": canonical_issue,
            "status": state.lower(),
            "terminal": state == "CLOSED",
            "route": domain_route,
            "maintainer_comment_refs": maintainer_comment_refs,
        },
        "numeric_pr_evidence": {
            "repo": canonical_repo,
            "issue_ref": canonical_issue,
            "query_scope": "issue_specific_all_states",
            "complete": True,
            "truncated": False,
            "source": dict(source_receipts["numeric_pr_evidence"]),
            "rows": list(numeric_by_number.values()),
        },
        "semantic_pr_evidence": {
            "repo": canonical_repo,
            "issue_ref": canonical_issue,
            "query_scope": "issue_specific_current_revision",
            "complete": True,
            "truncated": False,
            "source": dict(source_receipts["semantic_pr_evidence"]),
            "rows": list(semantic_by_number.values()),
        },
        "source_receipt": {
            "schema_version": ISSUE_FIX_CANDIDATE_EVIDENCE_SOURCE_SCHEMA_VERSION,
            "provider": "github_graphql",
            "observed_at": generated_at,
            "issue_ref": canonical_issue,
            "repo": canonical_repo,
            "maintainer_comment_refs": maintainer_comment_refs,
            "external_reads_performed": True,
            "external_writes_performed": False,
            "raw_provider_payload_captured": False,
            "credentials_captured": False,
        },
    }


def collect_public_github_candidate_preflight_input(
    *,
    repo: str,
    issue_ref: str,
    generated_at: str,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if timeout_seconds < 1 or timeout_seconds > 120:
        raise ValueError("timeout_seconds must be between 1 and 120")
    deadline = time.monotonic() + timeout_seconds

    def remaining_timeout() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("public GitHub candidate evidence timed out")
        return remaining

    reference = normalise_github_issue_reference(
        repo=repo,
        issue_ref=issue_ref,
        url=None,
    )
    canonical_repo = str(reference["repo"])
    number = reference.get("number")
    if not isinstance(number, int):
        raise TypeError("candidate evidence requires a numeric GitHub issue")
    if "/" not in canonical_repo:
        raise ValueError("candidate evidence repo must use owner/name")
    owner, name = canonical_repo.split("/", 1)

    closing_pages = _run_graphql_pages(
        query=_CLOSING_PULL_REQUESTS_QUERY,
        owner=owner,
        name=name,
        number=number,
        timeout_seconds=remaining_timeout(),
        operation="candidate closing pull request read",
    )
    state, closing = _connection_projection(
        closing_pages,
        connection="closedByPullRequestsReferences",
        operation="candidate closing pull request read",
    )
    cross_ref_pages = _run_graphql_pages(
        query=_CROSS_REFERENCED_PULL_REQUESTS_QUERY,
        owner=owner,
        name=name,
        number=number,
        timeout_seconds=remaining_timeout(),
        operation="candidate cross-reference read",
    )
    cross_ref_state, cross_refs = _connection_projection(
        cross_ref_pages,
        connection="timelineItems",
        operation="candidate cross-reference read",
    )
    comment_pages = _run_graphql_pages(
        query=_MAINTAINER_COMMENTS_QUERY,
        owner=owner,
        name=name,
        number=number,
        timeout_seconds=remaining_timeout(),
        operation="candidate maintainer disposition read",
    )
    comment_state, comments = _connection_projection(
        comment_pages,
        connection="comments",
        operation="candidate maintainer disposition read",
    )
    if {state, cross_ref_state, comment_state} != {state}:
        raise ValueError("public GitHub candidate evidence returned inconsistent state")

    source_receipts = {
        "numeric_pr_evidence": _source_projection(
            query=_CLOSING_PULL_REQUESTS_QUERY,
            observed_at=generated_at,
            page_count=len(closing_pages),
            result_count=len(closing),
        ),
        "semantic_pr_evidence": _source_projection(
            query=_CROSS_REFERENCED_PULL_REQUESTS_QUERY,
            observed_at=generated_at,
            page_count=len(cross_ref_pages),
            result_count=len(cross_refs),
        ),
    }
    return build_public_github_candidate_preflight_input(
        repo=canonical_repo,
        issue_ref=str(reference["issue_ref"]),
        issue_state=state,
        closing_pull_requests=closing,
        cross_referenced_pull_requests=cross_refs,
        maintainer_comments=comments,
        generated_at=generated_at,
        source_receipts=source_receipts,
    )

"""Bounded GitHub issue + discussion collector.

Reads only public repository metadata. Authentication is read from the
environment (`GH_TOKEN` or `GITHUB_TOKEN`); the request packet never carries
credentials. Internal `[Task]`-style issues are filtered as non-community
signals; maintainer-authored items are typed separately from external
discussion so a digest can prioritize user voices.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..normalize import make_fact


API_BASE = "https://api.github.com"
USER_AGENT = "loopx-community-discussion/0.1.0"
REQUEST_TIMEOUT_SECONDS = 20

INTERNAL_ISSUE_MARKERS = (
    "[task]",
    "[benchmark]",
    "[sweep]",
    "[chore]",
)


class GitHubSourceError(RuntimeError):
    pass


def _token() -> str | None:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _rest(path: str, params: dict[str, str]) -> tuple[Any, dict[str, str]]:
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read().decode("utf-8")
            return (json.loads(body) if body else None, headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise GitHubSourceError(f"GET {path} failed with {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubSourceError(f"GET {path} unreachable: {exc.reason}") from exc


def _graphql(query: str) -> dict[str, Any]:
    token = _token()
    if not token:
        raise GitHubSourceError("GitHub Discussions collection requires GH_TOKEN or GITHUB_TOKEN")
    req = urllib.request.Request(
        f"{API_BASE}/graphql",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={**_headers(), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise GitHubSourceError(f"GraphQL failed with {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise GitHubSourceError(f"GraphQL unreachable: {exc.reason}") from exc
    data = json.loads(body)
    if data.get("errors"):
        raise GitHubSourceError(f"GraphQL errors: {data['errors'][:2]}")
    return data


def _issue_facts(owner: str, repo: str, since: str, rate_bucket: dict[str, Any]) -> list[dict[str, Any]]:
    query = f"repo:{owner}/{repo} is:issue updated:>{since}"
    data, headers = _rest(
        "/search/issues",
        {"q": query, "per_page": "100", "sort": "updated", "order": "desc"},
    )
    rate_bucket["rate_limit_remaining"] = _min_remaining(
        rate_bucket.get("rate_limit_remaining"), headers.get("x-ratelimit-remaining")
    )
    facts: list[dict[str, Any]] = []
    for item in data.get("items", []):
        title = item.get("title") or ""
        if title.lower().startswith(INTERNAL_ISSUE_MARKERS):
            continue
        author = (item.get("user") or {}).get("login") or ""
        fact_type = "maintainer_signal" if author == owner else "external_discussion"
        fact = make_fact(
            fact_type=fact_type,
            source="github",
            source_url=item.get("html_url") or "",
            title=title,
            author=author,
            published_at=item.get("created_at") or "",
            text=(item.get("body") or "")[:2000],
        )
        if fact:
            facts.append(fact)
    return facts


def _discussion_facts(owner: str, repo: str, rate_bucket: dict[str, Any]) -> list[dict[str, Any]]:
    query = """
    query {
      repository(owner: "%s", name: "%s") {
        discussions(first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
          nodes {
            title
            url
            createdAt
            updatedAt
            author { login }
            category { name }
          }
        }
      }
    }
    """ % (owner, repo)
    data = _graphql(query)
    repo_data = (data.get("data") or {}).get("repository") or {}
    nodes = ((repo_data.get("discussions") or {}).get("nodes")) or []
    facts: list[dict[str, Any]] = []
    for node in nodes:
        author = (node.get("author") or {}).get("login") or ""
        fact_type = "maintainer_signal" if author == owner else "external_discussion"
        fact = make_fact(
            fact_type=fact_type,
            source="github",
            source_url=node.get("url") or "",
            title=node.get("title") or "",
            author=author,
            published_at=node.get("createdAt") or "",
        )
        if fact:
            facts.append(fact)
    return facts


def _min_remaining(current: int | None, raw: str | None) -> int | None:
    if raw is None:
        return current
    parsed = int(raw)
    return parsed if current is None else min(current, parsed)


def collect_github(owner: str, repo: str, days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rate_bucket: dict[str, Any] = {"rate_limit_remaining": None}
    warnings: list[str] = []
    facts: list[dict[str, Any]] = []
    try:
        facts.extend(_issue_facts(owner, repo, since, rate_bucket))
    except GitHubSourceError as exc:
        warnings.append(f"github issues skipped: {exc}")
    try:
        facts.extend(_discussion_facts(owner, repo, rate_bucket))
    except GitHubSourceError as exc:
        warnings.append(f"github discussions skipped: {exc}")
    evidence = {
        "sources": ["github-rest", "github-graphql"],
        "rate_limit_remaining": rate_bucket["rate_limit_remaining"],
        "warnings": warnings,
    }
    return facts, evidence

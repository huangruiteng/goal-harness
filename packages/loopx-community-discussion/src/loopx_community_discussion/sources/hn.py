"""Exact-match Hacker News Algolia collector.

Algolia's default typo tolerance returns thousands of unrelated hits for
"loopx" (Loopxo, Looptap, looped music, CrowdStrike, 2018 crypto scams).
This collector disables typo tolerance, restricts searchable attributes, and
requires an exact substring match so only real mentions survive.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..normalize import make_fact


SEARCH_URL = "https://hn.algolia.com/api/v1/search"
USER_AGENT = "loopx-community-discussion/0.1.0"
REQUEST_TIMEOUT_SECONDS = 20


class HNSourceError(RuntimeError):
    pass


def _search(query: str, since_unix: int, limit: int = 200) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {
            "query": query,
            "tags": "story",
            "hitsPerPage": str(limit),
            "numericFilters": f"created_at_i>{since_unix}",
            "typoTolerance": "false",
            "restrictSearchableAttributes": "title,url,story_text",
        }
    )
    req = urllib.request.Request(f"{SEARCH_URL}?{params}", headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode("utf-8")
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise HNSourceError(f"HN search failed with {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            time.sleep(1.0)
    raise HNSourceError(f"HN search unreachable: {last_error}") from last_error


def collect_hn(days: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    since_unix = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp())
    warnings: list[str] = []
    facts: list[dict[str, Any]] = []
    for query, default_type in (("loopx", "external_discussion"), ("loop engineering", "ecosystem_signal")):
        try:
            data = _search(query, since_unix)
        except HNSourceError as exc:
            warnings.append(f"hn query '{query}' skipped: {exc}")
            continue
        for hit in data.get("hits", []):
            title = hit.get("title") or "(untitled)"
            item_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            text = (hit.get("story_text") or "")[:2000]
            haystack = " ".join((title, item_url, text)).lower()
            if query.lower() not in haystack:
                continue
            fact_type = default_type
            if query != "loopx" and "loopx" in haystack:
                fact_type = "external_discussion"
            fact = make_fact(
                fact_type=fact_type,
                source="hacker_news",
                source_url=item_url,
                title=title,
                author=hit.get("author") or "",
                published_at=hit.get("created_at") or "",
                text=text,
            )
            if fact:
                facts.append(fact)
    evidence = {"sources": ["hn-algolia"], "rate_limit_remaining": None, "warnings": warnings}
    return facts, evidence

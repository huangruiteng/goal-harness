"""Disambiguation and deduplication helpers for community discussion facts."""

from __future__ import annotations

from typing import Any

from .contract import dedupe_key


NOISE_TERMS = (
    "loopxo",
    "looptap",
    "looped",
    "crowdstrike",
    "loophole",
    "loopy",
    "loopear",
)

STRONG_TERMS = (
    "huangruiteng",
    "loop engineering",
    "agent control plane",
    "local-first agent",
    "github.com/huangruiteng/loopx",
    "loopx project",
    "loopx repo",
)


def classify_relevance(title: str, url: str, text: str = "") -> tuple[str, str]:
    haystack = " ".join((title, url, text)).lower()
    if any(term in haystack for term in NOISE_TERMS):
        return "noise", "matched noise term"
    if any(term in haystack for term in STRONG_TERMS):
        return "strong", "matched project disambiguation term"
    return "weak", "no explicit project disambiguation term"


def make_fact(
    *,
    fact_type: str,
    source: str,
    source_url: str,
    title: str,
    author: str,
    published_at: str,
    text: str = "",
) -> dict[str, Any] | None:
    relevance, reason = classify_relevance(title, source_url, text)
    if relevance == "noise":
        return None
    return {
        "schema_version": "discussion_fact_v0",
        "fact_type": fact_type,
        "source": source,
        "source_url": source_url,
        "title": title[:300],
        "author": author,
        "published_at": published_at,
        "relevance": relevance,
        "relevance_reason": reason,
        "dedupe_key": dedupe_key(source_url, title),
    }


def merge_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for fact in facts:
        key = fact["dedupe_key"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    return sorted(deduped, key=lambda f: f.get("published_at") or "", reverse=True)

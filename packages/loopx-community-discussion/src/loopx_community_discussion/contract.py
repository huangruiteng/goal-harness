"""Public-safe community discussion fact and scan contract.

Facts are metadata-first: title, source URL, author, timestamp, relevance.
They never carry raw provider payloads, full post bodies, credentials, local
paths, or private context.
"""

from __future__ import annotations

import hashlib
from typing import Any


FACT_SCHEMA_VERSION = "discussion_fact_v0"
SCAN_SCHEMA_VERSION = "community_discussion_scan_v0"

FACT_TYPES = {
    "external_discussion",
    "maintainer_signal",
    "ecosystem_signal",
    "packaging",
    "press",
    "unanswered_question",
    "source_error",
}
SOURCES = {"github", "hacker_news", "web", "reddit", "x"}
RELEVANCE = {"strong", "weak"}


def dedupe_key(source_url: str, title: str) -> str:
    raw = f"{source_url.strip().lower()}::{' '.join(title.split()).lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def validate_fact(fact: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if fact.get("schema_version") != FACT_SCHEMA_VERSION:
        violations.append(f"schema_version must be {FACT_SCHEMA_VERSION}")
    if fact.get("fact_type") not in FACT_TYPES:
        violations.append(f"fact_type must be one of {sorted(FACT_TYPES)}")
    if fact.get("source") not in SOURCES:
        violations.append(f"source must be one of {sorted(SOURCES)}")
    for key in ("source_url", "title", "relevance_reason"):
        if not isinstance(fact.get(key), str) or not fact[key].strip():
            violations.append(f"{key} must be a non-empty string")
    for key in ("author", "published_at"):
        if not isinstance(fact.get(key), str):
            violations.append(f"{key} must be a string")
    if fact.get("relevance") not in RELEVANCE:
        violations.append(f"relevance must be one of {sorted(RELEVANCE)}")
    key = fact.get("dedupe_key")
    if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        violations.append("dedupe_key must be a 64-char lowercase hex sha256")
    return violations


def validate_scan(scan: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if scan.get("schema_version") != SCAN_SCHEMA_VERSION:
        violations.append(f"schema_version must be {SCAN_SCHEMA_VERSION}")
    for key in ("scan_at", "repo", "stats", "facts", "evidence"):
        if key not in scan:
            violations.append(f"missing required field {key}")
    repo = scan.get("repo")
    if not isinstance(repo, dict) or not isinstance(repo.get("owner"), str) or not isinstance(repo.get("name"), str):
        violations.append("repo must be an object with string owner and name")
    stats = scan.get("stats")
    if isinstance(stats, dict):
        for metric in ("raw_facts", "deduped_facts", "source_errors", "strong"):
            if not isinstance(stats.get(metric), int) or stats[metric] < 0:
                violations.append(f"stats.{metric} must be a non-negative integer")
    else:
        violations.append("stats must be an object")
    facts = scan.get("facts")
    if not isinstance(facts, list):
        violations.append("facts must be an array")
    else:
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict):
                violations.append(f"facts[{index}] must be an object")
                continue
            violations.extend(f"facts[{index}].{v}" for v in validate_fact(fact))
    evidence = scan.get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("sources"), list) or not isinstance(
        evidence.get("warnings"), list
    ):
        violations.append("evidence must be an object with sources and warnings arrays")
    return violations

"""Deterministic markdown digest projection for a community discussion scan."""

from __future__ import annotations

from typing import Any


SECTION_CAPS = {
    "external_discussion": 8,
    "maintainer_signal": 5,
    "ecosystem_signal": 5,
    "press": 5,
    "packaging": 5,
}


def _fact_line(fact: dict[str, Any]) -> str:
    author = f" — {fact['author']}" if fact.get("author") else ""
    return f"- [{fact['title']}]({fact['source_url']}){author}"


def render_markdown(scan: dict[str, Any]) -> str:
    repo = scan["repo"]
    lines = [
        f"# Community discussion: {repo['owner']}/{repo['name']}",
        "",
        f"Window: last {scan['window_days']} days · scan at {scan['scan_at']}",
        "",
    ]
    stats = scan["stats"]
    lines.append(
        f"Facts: {stats['deduped_facts']} deduped "
        f"({stats['strong']} strong, {stats['source_errors']} source errors)"
    )
    lines.append("")

    by_type: dict[str, list[dict[str, Any]]] = {}
    for fact in scan["facts"]:
        by_type.setdefault(fact["fact_type"], []).append(fact)

    sections = [
        ("External discussions", "external_discussion"),
        ("Maintainer signals", "maintainer_signal"),
        ("Ecosystem signals", "ecosystem_signal"),
        ("Press & packaging", "press", "packaging"),
    ]
    for title, *types in sections:
        items: list[dict[str, Any]] = []
        for fact_type in types:
            items.extend(by_type.get(fact_type, []))
        if not items:
            continue
        cap = min(SECTION_CAPS.get(types[0], 5), len(items))
        lines.append(f"## {title}")
        lines.append("")
        lines.extend(_fact_line(fact) for fact in items[:cap])
        lines.append("")

    warnings = (scan.get("evidence") or {}).get("warnings") or []
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.extend(f"- {warning}" for warning in warnings[:10])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

"""Compact markdown rendering for a repo-health snapshot."""

from __future__ import annotations

from typing import Any


def _fmt_minutes(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 60:
        return f"{value:.0f} min"
    return f"{value / 60:.1f} h"


def render_markdown(snapshot: dict[str, Any]) -> str:
    counts = snapshot["counts"]
    traffic = snapshot["traffic_14d"]
    latency = snapshot["latency"]
    repo = snapshot["repo"]
    lines = [
        f"# Repo Health: {repo['owner']}/{repo['name']}",
        "",
        f"- captured_at: {snapshot['captured_at']}",
        f"- license: {repo.get('license') or 'n/a'}",
        f"- pushed_at: {repo.get('pushed_at') or 'n/a'}",
        "",
        "## Counts",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    for key in (
        "stars",
        "forks",
        "watchers",
        "open_issues",
        "releases",
        "contributors",
        "prs_total",
        "issues_total",
    ):
        lines.append(f"| {key} | {counts.get(key, 0)} |")
    lines += [
        "",
        "## Traffic (14d)",
        "",
        "| surface | count | uniques |",
        "| --- | --- | --- |",
    ]
    for surface in ("views", "clones", "docs_views"):
        item = traffic.get(surface, {})
        lines.append(f"| {surface} | {item.get('count', 0)} | {item.get('uniques', 0)} |")
    paths = traffic.get("paths") or []
    if paths:
        lines += [
            "",
            "### Top paths",
            "",
            "| path | title | count | uniques |",
            "| --- | --- | --- | --- |",
        ]
        for row in paths[:10]:
            lines.append(
                f"| {row.get('path', '')} | {row.get('title', '')} | {row.get('count', 0)} | {row.get('uniques', 0)} |"
            )
    lines += [
        "",
        "## Latency",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| PR merge p25 | {_fmt_minutes(latency.get('pr_merge_p25_min'))} |",
        f"| PR merge p75 | {_fmt_minutes(latency.get('pr_merge_p75_min'))} |",
        f"| first response p25 | {_fmt_minutes(latency.get('first_response_p25_min'))} |",
        f"| first response p75 | {_fmt_minutes(latency.get('first_response_p75_min'))} |",
        "",
        "## Recent star timeline (weekly)",
        "",
        "| week | stars |",
        "| --- | --- |",
    ]
    for row in snapshot.get("star_timeline_weekly", []):
        lines.append(f"| {row['week']} | {row['stars']} |")
    warnings = (snapshot.get("evidence") or {}).get("warnings") or []
    if warnings:
        lines += ["", "## Warnings", ""]
        lines += [f"- {w}" for w in warnings]
    return "\n".join(lines) + "\n"

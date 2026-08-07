#!/usr/bin/env python3
"""Render a public GitHub stargazer timeline as a self-hosted SVG."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any


REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _parse_date(value: str, *, field: str) -> date:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp or date") from exc


def _load_stargazers(path: Path) -> list[date]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("stargazer input must be a JSON array")
    rows: list[Any] = []
    for item in payload:
        rows.extend(item if isinstance(item, list) else [item])
    dates: list[date] = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict) or not isinstance(item.get("starred_at"), str):
            raise ValueError(f"stargazer row {index} must contain starred_at")
        dates.append(_parse_date(item["starred_at"], field="starred_at"))
    return dates


def _nice_scale(value: int, *, target_intervals: int = 7) -> tuple[int, int]:
    if value <= 1:
        return 1, 1
    rough_step = value / target_intervals
    magnitude = 10 ** math.floor(math.log10(rough_step))
    scaled_step = rough_step / magnitude
    factor = next(
        candidate for candidate in (1, 2, 2.5, 5, 10) if scaled_step <= candidate
    )
    step = max(1, int(factor * magnitude))
    return int(math.ceil(value / step) * step), step


def _format_count(value: int) -> str:
    if value < 1_000:
        return str(value)
    scaled = value / 1_000
    return f"{scaled:.0f}k" if scaled.is_integer() else f"{scaled:.1f}k"


def _format_tick_date(day: date, *, span_days: int) -> str:
    if span_days >= 730:
        return str(day.year)
    if span_days >= 120:
        return f"{day:%b} {day.year}"
    return f"{day:%b} {day.day}"


def _format_display_date(day: date) -> str:
    return f"{day:%b} {day.day}, {day.year}"


def _timeline(stars: list[date], *, as_of: date) -> list[tuple[date, int]]:
    counts = Counter(star for star in stars if star <= as_of)
    if not counts:
        return [(as_of - timedelta(days=30), 0), (as_of, 0)]
    total = 0
    points: list[tuple[date, int]] = []
    for day in sorted(counts):
        total += counts[day]
        points.append((day, total))
    if points[-1][0] < as_of:
        points.append((as_of, total))
    return points


def render_svg(repo: str, stars: list[date], *, as_of: date) -> str:
    points = _timeline(stars, as_of=as_of)
    total = points[-1][1]
    start = points[0][0]
    span_days = max((as_of - start).days, 1)
    width, height = 800, 500
    left, right, top, bottom = 76, 30, 108, 72
    plot_width = width - left - right
    plot_height = height - top - bottom
    y_max, y_step = _nice_scale(total)

    def x_for(day: date) -> float:
        return left + ((day - start).days / span_days) * plot_width

    def y_for(value: int) -> float:
        return top + plot_height - (value / y_max) * plot_height

    chart_points = [(x_for(day), y_for(value)) for day, value in points]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in chart_points)
    y_grid: list[str] = []
    value = 0
    while value <= y_max:
        y = y_for(value)
        y_grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{left - 12}" y="{y + 4:.1f}" class="axis" text-anchor="end">{_format_count(value)}</text>'
        )
        value += y_step

    x_labels: list[str] = []
    for index in range(6):
        day = start + timedelta(days=round(span_days * index / 5))
        x = x_for(day)
        anchor = "start" if index == 0 else "end" if index == 5 else "middle"
        x_labels.append(
            f'<text x="{x:.1f}" y="{top + plot_height + 28}" class="axis" text-anchor="{anchor}">{_format_tick_date(day, span_days=span_days)}</text>'
        )

    safe_repo = escape(repo)
    legend_width = min(260, max(154, 34 + len(repo) * 7))
    display_date = _format_display_date(as_of)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{safe_repo} GitHub star history</title>
  <desc id="desc">Cumulative public GitHub stars through {as_of.isoformat()}: {total}.</desc>
  <style>
    .background {{ fill: #ffffff; }}
    .grid {{ stroke: #e5e7eb; stroke-width: 1; stroke-dasharray: 3 5; }}
    .axis-line {{ stroke: #9ca3af; stroke-width: 1.5; }}
    .axis {{ fill: #667085; font: 12px ui-sans-serif, system-ui, sans-serif; }}
    .axis-title {{ fill: #667085; font: 12px ui-sans-serif, system-ui, sans-serif; }}
    .title {{ fill: #101828; font: 600 22px ui-sans-serif, system-ui, sans-serif; }}
    .meta {{ fill: #667085; font: 13px ui-sans-serif, system-ui, sans-serif; }}
    .legend-box {{ fill: #ffffff; stroke: #d0d5dd; stroke-width: 1; }}
    .legend {{ fill: #344054; font: 12px ui-sans-serif, system-ui, sans-serif; }}
    .legend-dot {{ fill: #f05235; }}
    .line {{ fill: none; stroke: #f05235; stroke-width: 3.5; stroke-linecap: round; stroke-linejoin: round; }}
    .point {{ fill: #ffffff; stroke: #f05235; stroke-width: 3; }}
    @media (prefers-color-scheme: dark) {{
      .background {{ fill: #0d1117; }}
      .grid {{ stroke: #30363d; }}
      .axis-line {{ stroke: #6e7681; }}
      .axis, .axis-title, .meta {{ fill: #8b949e; }}
      .title {{ fill: #f0f6fc; }}
      .legend-box {{ fill: #161b22; stroke: #30363d; }}
      .legend {{ fill: #c9d1d9; }}
      .point {{ fill: #0d1117; }}
    }}
  </style>
  <rect width="{width}" height="{height}" class="background"/>
  <text x="{width / 2:.0f}" y="34" class="title" text-anchor="middle">Star History</text>
  <text x="{width / 2:.0f}" y="56" class="meta" text-anchor="middle">{total:,} stars · updated {display_date}</text>
  <g transform="translate({left},72)">
    <rect width="{legend_width}" height="28" rx="6" class="legend-box"/>
    <circle cx="13" cy="14" r="4" class="legend-dot"/>
    <text x="25" y="18" class="legend">{safe_repo}</text>
  </g>
  {''.join(y_grid)}
  {''.join(x_labels)}
  <line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" class="axis-line"/>
  <line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" class="axis-line"/>
  <text x="20" y="{top + plot_height / 2:.1f}" class="axis-title" text-anchor="middle" transform="rotate(-90 20 {top + plot_height / 2:.1f})">GitHub stars</text>
  <text x="{left + plot_width / 2:.1f}" y="{height - 16}" class="axis-title" text-anchor="middle">Date</text>
  <polyline points="{line}" class="line"/>
  <circle cx="{chart_points[-1][0]:.1f}" cy="{chart_points[-1][1]:.1f}" r="5" class="point"/>
</svg>
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--as-of")
    args = parser.parse_args()

    if not isinstance(args.repo, str) or not REPO_PATTERN.fullmatch(args.repo):
        parser.error("--repo must be an owner/name GitHub repository")
    as_of = (
        _parse_date(args.as_of, field="as_of")
        if args.as_of
        else datetime.now(timezone.utc).date()
    )
    stars = _load_stargazers(args.input_json)
    if args.expected_count < 0:
        parser.error("--expected-count must be non-negative")
    if len(stars) != args.expected_count:
        parser.error(
            f"stargazer snapshot is incomplete: expected {args.expected_count}, "
            f"got {len(stars)}"
        )
    future_dates = [star for star in stars if star > as_of]
    if future_dates:
        parser.error(
            f"stargazer snapshot contains {len(future_dates)} future timestamp(s)"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_svg(args.repo, stars, as_of=as_of), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

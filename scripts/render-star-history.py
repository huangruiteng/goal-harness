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


def _nice_ceiling(value: int) -> int:
    if value <= 1:
        return 1
    rough_step = value / 4
    magnitude = 10 ** math.floor(math.log10(rough_step))
    scaled_step = rough_step / magnitude
    factor = next(
        candidate for candidate in (1, 2, 2.5, 5, 10) if scaled_step <= candidate
    )
    step = factor * magnitude
    return int(math.ceil(value / step) * step)


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
    width, height = 960, 420
    left, right, top, bottom = 78, 28, 72, 62
    plot_width = width - left - right
    plot_height = height - top - bottom
    y_max = _nice_ceiling(total)

    def x_for(day: date) -> float:
        return left + ((day - start).days / span_days) * plot_width

    def y_for(value: int) -> float:
        return top + plot_height - (value / y_max) * plot_height

    chart_points = [(x_for(day), y_for(value)) for day, value in points]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in chart_points)
    area = (
        f"{left},{top + plot_height} "
        + line
        + f" {left + plot_width},{top + plot_height}"
    )

    y_grid: list[str] = []
    for index in range(5):
        value = round(y_max * index / 4)
        y = y_for(value)
        y_grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}" class="grid"/>'
            f'<text x="{left - 14}" y="{y + 4:.1f}" class="axis" text-anchor="end">{value}</text>'
        )

    x_labels: list[str] = []
    for index in range(5):
        day = start + timedelta(days=round(span_days * index / 4))
        x = x_for(day)
        anchor = "start" if index == 0 else "end" if index == 4 else "middle"
        x_labels.append(
            f'<text x="{x:.1f}" y="{top + plot_height + 34}" class="axis" text-anchor="{anchor}">{day:%Y-%m-%d}</text>'
        )

    safe_repo = escape(repo)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{safe_repo} GitHub star history</title>
  <desc id="desc">Cumulative public GitHub stars through {as_of.isoformat()}: {total}.</desc>
  <style>
    .background {{ fill: #ffffff; }}
    .grid {{ stroke: #dbe5f3; stroke-width: 1; }}
    .axis {{ fill: #65748a; font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .title {{ fill: #0d1b2f; font: 600 22px ui-sans-serif, system-ui, sans-serif; }}
    .meta {{ fill: #65748a; font: 13px ui-sans-serif, system-ui, sans-serif; }}
    .area {{ fill: url(#area-gradient); }}
    .line {{ fill: none; stroke: #2f80ed; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }}
    .point {{ fill: #ffffff; stroke: #2f80ed; stroke-width: 3; }}
    @media (prefers-color-scheme: dark) {{
      .background {{ fill: #07101f; }}
      .grid {{ stroke: #21324a; }}
      .axis, .meta {{ fill: #91a2b9; }}
      .title {{ fill: #e8eef7; }}
      .point {{ fill: #07101f; }}
    }}
  </style>
  <defs>
    <linearGradient id="area-gradient" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#2f80ed" stop-opacity="0.32"/>
      <stop offset="100%" stop-color="#2f80ed" stop-opacity="0.03"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="12" class="background"/>
  <text x="{left}" y="36" class="title">GitHub Star History</text>
  <text x="{left}" y="57" class="meta">{safe_repo} · {total} stars · updated {as_of.isoformat()}</text>
  {''.join(y_grid)}
  {''.join(x_labels)}
  <polygon points="{area}" class="area"/>
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

#!/usr/bin/env python3
"""Render a static Goal Harness status dashboard from JSON output.

Usage:
  goal-harness --format json status > /tmp/goal-status.json
  python3 examples/render-status-dashboard.py /tmp/goal-status.json /tmp/goal-status.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


LANES = [
    ("user", "User / Controller", {"user_or_controller", "controller"}),
    ("codex", "Codex Ready", {"codex"}),
    ("watch", "Watching Evidence", {"external_evidence"}),
]


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def load_status(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("status JSON must be an object")
    return payload


def queue_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    queue = payload.get("attention_queue")
    if not isinstance(queue, dict):
        return []
    items = queue.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def severity_class(item: dict[str, Any]) -> str:
    severity = str(item.get("severity") or "action")
    return severity if severity in {"high", "action", "watch"} else "action"


def render_item(item: dict[str, Any]) -> str:
    status = esc(item.get("status"))
    waiting = esc(item.get("waiting_on"))
    source = esc(item.get("source"))
    action = esc(item.get("recommended_action"))
    return f"""
        <article class="item {severity_class(item)}">
          <div class="item-top">
            <h3>{esc(item.get("goal_id"))}</h3>
            <span>{esc(item.get("severity"))}</span>
          </div>
          <dl>
            <dt>Status</dt><dd>{status}</dd>
            <dt>Waiting</dt><dd>{waiting}</dd>
            <dt>Source</dt><dd>{source}</dd>
          </dl>
          <p>{action}</p>
        </article>
    """


def render_lane(title: str, waiting_values: set[str], items: list[dict[str, Any]]) -> str:
    lane_items = [item for item in items if str(item.get("waiting_on")) in waiting_values]
    body = "\n".join(render_item(item) for item in lane_items)
    if not body:
        body = '<p class="empty">No goals in this lane.</p>'
    return f"""
      <section class="lane">
        <header>
          <h2>{esc(title)}</h2>
          <strong>{len(lane_items)}</strong>
        </header>
        {body}
      </section>
    """


def render_dashboard(payload: dict[str, Any]) -> str:
    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else {}
    summary = contract.get("summary") if isinstance(contract.get("summary"), dict) else {}
    queue = payload.get("attention_queue") if isinstance(payload.get("attention_queue"), dict) else {}
    items = queue_items(payload)
    lanes = "\n".join(render_lane(title, values, items) for _, title, values in LANES)
    errors = contract.get("errors") if isinstance(contract.get("errors"), list) else []
    warnings = contract.get("warnings") if isinstance(contract.get("warnings"), list) else []
    health_details = "\n".join(
        f"<li>{esc(kind)}: {esc(entry)}</li>"
        for kind, entries in (("error", errors), ("warning", warnings))
        for entry in entries
    )
    if not health_details:
        health_details = "<li>No contract errors or warnings.</li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Goal Harness Status</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f4;
      --ink: #1f2520;
      --muted: #657068;
      --line: #d9ded8;
      --panel: #ffffff;
      --green: #3d7c54;
      --blue: #386b8f;
      --amber: #9a6a22;
      --red: #aa3f3f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.45;
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 32px auto;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 24px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
      margin-bottom: 20px;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 28px; font-weight: 720; }}
    .meta {{ color: var(--muted); margin-top: 6px; }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(4, minmax(88px, 1fr));
      gap: 10px;
      min-width: min(520px, 100%);
    }}
    .metric {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .metric span {{ color: var(--muted); font-size: 12px; display: block; }}
    .metric strong {{ font-size: 22px; }}
    .lanes {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .lane {{
      background: rgba(255, 255, 255, 0.55);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 220px;
    }}
    .lane header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }}
    .lane h2 {{ font-size: 16px; }}
    .lane header strong {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 28px;
      height: 28px;
      border-radius: 999px;
      background: var(--ink);
      color: white;
      font-size: 13px;
    }}
    .item {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 5px solid var(--blue);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 10px;
    }}
    .item.high {{ border-left-color: var(--red); }}
    .item.action {{ border-left-color: var(--amber); }}
    .item.watch {{ border-left-color: var(--green); }}
    .item-top {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
    }}
    .item h3 {{ font-size: 15px; overflow-wrap: anywhere; }}
    .item-top span {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    dl {{
      display: grid;
      grid-template-columns: 78px 1fr;
      gap: 4px 8px;
      margin: 10px 0;
      font-size: 13px;
    }}
    dt {{ color: var(--muted); }}
    dd {{ margin: 0; overflow-wrap: anywhere; }}
    .item p, .empty {{ color: var(--muted); font-size: 13px; }}
    .health {{
      margin-top: 18px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    .health h2 {{ font-size: 16px; margin-bottom: 8px; }}
    .health ul {{ margin: 0; padding-left: 18px; color: var(--muted); }}
    @media (max-width: 860px) {{
      .topbar {{ display: block; }}
      .summary {{ margin-top: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .lanes {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="topbar">
      <div>
        <h1>Goal Harness Status</h1>
        <p class="meta">Registry: {esc(payload.get("registry"))}</p>
        <p class="meta">Runtime: {esc(payload.get("runtime_root"))}</p>
      </div>
      <div class="summary">
        <div class="metric"><span>OK</span><strong>{esc(payload.get("ok"))}</strong></div>
        <div class="metric"><span>Goals</span><strong>{esc(payload.get("goal_count"))}</strong></div>
        <div class="metric"><span>Runs</span><strong>{esc(payload.get("run_count"))}</strong></div>
        <div class="metric"><span>Queue</span><strong>{esc(queue.get("item_count"))}</strong></div>
      </div>
    </section>
    <section class="lanes">
      {lanes}
    </section>
    <section class="health">
      <h2>Contract Health</h2>
      <p class="meta">ok={esc(contract.get("ok"))}, errors={esc(summary.get("errors"))}, warnings={esc(summary.get("warnings"))}, checks={esc(summary.get("checks"))}</p>
      <ul>{health_details}</ul>
    </section>
  </main>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Goal Harness status JSON as a static HTML dashboard.")
    parser.add_argument("status_json", help="Path to goal-harness --format json status output.")
    parser.add_argument("output_html", help="Path to write the rendered dashboard HTML.")
    args = parser.parse_args()

    payload = load_status(Path(args.status_json))
    output = Path(args.output_html)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard(payload), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

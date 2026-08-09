from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import platform
import sys
from urllib.parse import urlencode

from .. import __version__


PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]

FIRST_RUN_ISSUE_URL = "https://github.com/huangruiteng/loopx/issues/new"
FIRST_RUN_ISSUE_TEMPLATE = "first_run.yml"


def _issue_url(title: str) -> str:
    query = urlencode({"template": FIRST_RUN_ISSUE_TEMPLATE, "title": title})
    return f"{FIRST_RUN_ISSUE_URL}?{query}"


def collect_first_run_report() -> dict[str, object]:
    os_label = f"{platform.system()} {platform.release()}".strip()
    title = f"First run: LoopX {__version__} on {os_label} ({platform.machine()})"
    return {
        "schema_version": "first_run_report_v0",
        "loopx_version": __version__,
        "os": os_label,
        "arch": platform.machine(),
        "python": sys.version.split()[0],
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "issue_url": _issue_url(title),
        "sent": False,
    }


def render_first_run_report_markdown(payload: dict[str, object]) -> str:
    lines = [
        "LoopX first-run report (local only, nothing was sent)",
        "",
        f"- LoopX: {payload['loopx_version']}",
        f"- OS: {payload['os']}",
        f"- Arch: {payload['arch']}",
        f"- Python: {payload['python']}",
        f"- Generated: {payload['reported_at']}",
        "",
        "Create an optional public feedback issue:",
        str(payload["issue_url"]),
    ]
    return "\n".join(lines)


def register_first_run_report_command(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    return subparsers.add_parser(
        "first-run-report",
        help="Print a local first-run receipt and an optional public feedback issue link.",
    )


def handle_first_run_report_command(
    args: argparse.Namespace,
    print_payload: PrintPayload,
) -> int:
    payload = collect_first_run_report()
    print_payload(payload, args.format, render_first_run_report_markdown)
    return 0

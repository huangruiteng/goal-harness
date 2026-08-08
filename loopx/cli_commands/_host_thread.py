from __future__ import annotations

import argparse
import os


def current_host_thread_id(args: argparse.Namespace) -> str | None:
    explicit = getattr(args, "thread_id", None)
    if explicit:
        return str(explicit)
    if getattr(args, "host_surface", None) == "codex-app":
        return os.environ.get("CODEX_THREAD_ID") or None
    return None

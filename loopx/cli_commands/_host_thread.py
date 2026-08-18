from __future__ import annotations

import argparse
import os


def current_host_thread_id(args: argparse.Namespace) -> str | None:
    explicit = getattr(args, "thread_id", None)
    if explicit:
        return str(explicit)
    host_surface = getattr(args, "host_surface", None)
    if host_surface in {
        "codex-app",
        "codex-app-ssh",
        "codex-ide-plugin",
        "codex-cli-tui",
    }:
        return os.environ.get("CODEX_THREAD_ID") or None
    return None

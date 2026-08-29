from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path

from ..control_plane.runtime.status_projection_cache import (
    resolve_status_projection_cache_runtime_root,
)
from ..control_plane.turn_driver import (
    LOOPX_TURN_JOURNAL_INSPECTION_SCHEMA_VERSION,
    codex_cli_session_binding,
    inspect_loopx_turn_journal,
)
from .turn_rendering import render_loopx_turn_journal_inspection_markdown

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]


def handle_turn_journal_inspection(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    runtime_root_arg: str | None,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.turn_command != "inspect-journal":
        return None
    try:
        runtime_root = resolve_status_projection_cache_runtime_root(
            registry_path=registry_path,
            runtime_root_override=runtime_root_arg,
        )
        payload = inspect_loopx_turn_journal(
            runtime_root,
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            turn_key=args.turn_key,
            retry_failed=bool(args.retry_failed_turn),
            session_binding_resolver=(
                lambda turn_envelope: codex_cli_session_binding(
                    runtime_root,
                    turn_envelope,
                )
            ),
        )
    except Exception as exc:  # noqa: BLE001 - typed CLI failure boundary
        payload = {
            "ok": False,
            "schema_version": LOOPX_TURN_JOURNAL_INSPECTION_SCHEMA_VERSION,
            "error": str(exc),
            "effects": [],
        }
    print_payload(
        payload,
        output_format(args),
        render_loopx_turn_journal_inspection_markdown,
    )
    return 0 if payload.get("ok") else 1

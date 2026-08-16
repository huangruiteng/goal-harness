#!/usr/bin/env python3
"""Smoke-test explicit CLI management for private Chat Agent bindings."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(root: Path, *args: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--runtime-root",
            str(root / "runtime"),
            "chat-endpoint",
            *args,
            "--format",
            "json",
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    if completed.returncode not in {0, 1}:
        raise AssertionError(completed.stderr)
    return payload


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loopx-chat-endpoint-cli-") as raw_tmp:
        root = Path(raw_tmp)
        executable = root / "fixture-agent"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        config = root / "endpoint.json"
        config.write_text(
            json.dumps(
                {
                    "agent_id": "fixture-cli-acp",
                    "display_name": "Fixture CLI ACP",
                    "adapter_kind": "acp",
                    "transport": "stdio",
                    "location": "local",
                    "trust_scope": "read_only",
                    "command": [str(executable), "--private-cli-binding"],
                    "workspace_mapping": [],
                }
            ),
            encoding="utf-8",
        )
        added = run_cli(root, "add", "--config", str(config))
        assert added["ok"] is True, added
        assert "command" not in json.dumps(added), added
        assert "private-cli-binding" not in json.dumps(added), added
        listed = run_cli(root, "list")
        assert [item["agent_id"] for item in listed["endpoints"]] == ["fixture-cli-acp"], listed
        removed = run_cli(root, "remove", "--agent-id", "fixture-cli-acp")
        assert removed["ok"] is True, removed
        empty = run_cli(root, "list")
        assert empty["endpoints"] == [], empty

    print("loopx-chat-endpoint-cli-smoke: ok")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Smoke-test owner-only Agent endpoint binding and public redaction."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.chat_endpoints import AgentEndpointRegistry  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loopx-chat-endpoints-") as raw_tmp:
        root = Path(raw_tmp)
        executable = root / "fake-acp"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        local_root = root / "workspace"
        local_root.mkdir()
        registry = AgentEndpointRegistry(root / "chat")
        endpoint = registry.upsert(
            {
                "agent_id": "remote-reviewer",
                "display_name": "Remote Reviewer",
                "adapter_kind": "acp",
                "transport": "stdio",
                "location": "remote",
                "trust_scope": "read_only",
                "command": [str(executable), "--private-endpoint-reference"],
                "workspace_mapping": [
                    {"local_root": str(local_root), "agent_root": "/srv/workspace"}
                ],
            }
        )
        public = endpoint.public_summary()
        assert public["available"] is True, public
        assert "command" not in public and "workspace_mapping" not in public, public
        assert "private-endpoint-reference" not in json.dumps(public), public
        assert endpoint.mapped_work_dir(local_root / "nested") == Path("/srv/workspace/nested")
        assert registry.get("remote-reviewer") == endpoint
        mode = stat.S_IMODE(registry.path.stat().st_mode)
        assert mode == 0o600, oct(mode)
        stored = registry.path.read_text(encoding="utf-8")
        assert "private-endpoint-reference" in stored
        assert registry.delete("remote-reviewer") is True
        assert registry.list() == []
        assert registry.delete("remote-reviewer") is False
        try:
            registry.upsert(
                {
                    "agent_id": "codex",
                    "display_name": "Override",
                    "command": [str(executable)],
                }
            )
        except ValueError as exc:
            assert "reserved" in str(exc)
        else:
            raise AssertionError("built-in Agent id override was accepted")
        assert stat.S_IMODE(os.stat(registry.root).st_mode) == 0o700

    print("loopx-chat-endpoint-registry-smoke: ok")


if __name__ == "__main__":
    main()

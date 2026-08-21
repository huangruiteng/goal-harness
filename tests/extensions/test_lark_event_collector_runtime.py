from __future__ import annotations

import json
import subprocess

from loopx.extensions.lark.event_collector_runtime import _run_json_with_status


def test_json_status_reads_nested_provider_code_from_stderr() -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["lark-cli"],
            returncode=1,
            stdout="",
            stderr=json.dumps(
                {
                    "ok": False,
                    "identity": "bot",
                    "error": {"code": 230027, "message": "permission denied"},
                }
            ),
        )

    payload, status = _run_json_with_status(runner, ["lark-cli", "im", "messages"])

    assert payload == {}
    assert status == "message_context_permission_required"


def test_json_status_preserves_success_payload_from_stdout() -> None:
    expected = {"ok": True, "data": {"items": []}}

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["lark-cli"],
            returncode=0,
            stdout=json.dumps(expected),
            stderr="",
        )

    payload, status = _run_json_with_status(runner, ["lark-cli", "im", "messages"])

    assert payload == expected
    assert status == "message_context_available"

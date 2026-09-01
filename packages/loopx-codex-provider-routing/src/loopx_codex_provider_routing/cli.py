from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import (
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
    build_upgrade_plan,
    compile_catalog,
    qualify_snapshot,
    reject_private_material,
)

EXTENSION_ID = "loopx-codex-provider-routing"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=EXTENSION_ID)
    parser.add_argument(
        "--doctor", action="store_true", help="run a side-effect-free readiness check"
    )
    return parser


def _emit(payload: Mapping[str, Any]) -> None:
    json.dump(payload, sys.stdout, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


def _doctor() -> int:
    _emit(
        {
            "ok": True,
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "extension_id": EXTENSION_ID,
            "doctor": "ready",
            "operations": ["compile_catalog", "qualify_snapshot", "upgrade_plan"],
            "effect_boundary": "read_only_public_safe",
        }
    )
    return 0


def _run_request(request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise TypeError("extension input must be a JSON object")
    reject_private_material(request)
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise ValueError(f"extension input must use {REQUEST_SCHEMA_VERSION}")
    operation = request.get("operation")
    operation_fields = {
        "compile_catalog": "source",
        "qualify_snapshot": "snapshot",
        "upgrade_plan": "upgrade",
    }
    expected_field = operation_fields.get(operation)
    if expected_field is None:
        raise ValueError(f"unsupported operation: {operation!r}")
    unexpected = sorted(set(request) - {"schema_version", "operation", expected_field})
    if unexpected:
        raise ValueError(f"extension input has unsupported fields: {unexpected}")
    if operation == "compile_catalog":
        source = request.get("source")
        if not isinstance(source, Mapping):
            raise ValueError("compile_catalog requires object `source`")
        result = compile_catalog(source)
    elif operation == "qualify_snapshot":
        snapshot = request.get("snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError("qualify_snapshot requires object `snapshot`")
        result = qualify_snapshot(snapshot)
    else:
        upgrade = request.get("upgrade")
        if not isinstance(upgrade, Mapping):
            raise ValueError("upgrade_plan requires object `upgrade`")
        result = build_upgrade_plan(upgrade)
    return {
        "ok": True,
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "extension_id": EXTENSION_ID,
        "request_schema_version": REQUEST_SCHEMA_VERSION,
        "operation": operation,
        "result": result,
    }


def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.doctor:
        return _doctor()
    try:
        request = json.load(sys.stdin)
        _emit(_run_request(request))
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        _emit(
            {
                "ok": False,
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "extension_id": EXTENSION_ID,
                "error": str(exc),
            }
        )
        return 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())

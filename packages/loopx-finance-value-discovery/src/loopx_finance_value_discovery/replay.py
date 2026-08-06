from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .gates import evaluate_finance_case_gates

FINANCE_CASE_REPLAY_RECEIPT_SCHEMA_VERSION = "finance_case_replay_receipt_v1"


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_finance_case_evaluation(value: object) -> dict[str, Any]:
    evaluation = evaluate_finance_case_gates(value)
    receipt = {
        "schema_version": FINANCE_CASE_REPLAY_RECEIPT_SCHEMA_VERSION,
        "contract_sha256": canonical_sha256(evaluation["contract"]),
        "input_sha256": canonical_sha256(value),
        "evaluation_sha256": canonical_sha256(evaluation),
        "canonicalization": "json_sort_keys_compact_ascii_v1",
    }
    return {**evaluation, "replay": receipt}


def replay_finance_case_evaluation(
    value: object,
    expected: object,
) -> dict[str, Any]:
    if not isinstance(expected, Mapping):
        raise ValueError("expected evaluation must be an object")
    replayed = build_finance_case_evaluation(value)
    expected_replay = expected.get("replay")
    if not isinstance(expected_replay, Mapping):
        raise ValueError("expected evaluation requires a replay receipt")
    for field in ("contract_sha256", "input_sha256", "evaluation_sha256"):
        if expected_replay.get(field) != replayed["replay"][field]:
            raise ValueError(f"replay {field} mismatch")
    if canonical_json_bytes(expected) != canonical_json_bytes(replayed):
        raise ValueError("replay evaluation bytes mismatch")
    return {
        "ok": True,
        "schema_version": FINANCE_CASE_REPLAY_RECEIPT_SCHEMA_VERSION,
        "replay_verified": True,
        "contract_sha256": replayed["replay"]["contract_sha256"],
        "input_sha256": replayed["replay"]["input_sha256"],
        "evaluation_sha256": replayed["replay"]["evaluation_sha256"],
    }

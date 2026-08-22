"""Public-safe verifier reward contract for benchmark runners.

Pier's ``VerifierResult`` models the verifier reward as
``dict[str, float | int]``. A reward payload that carries string detail fields
or nested objects fails that schema and turns a completed evaluation into a
runner error. This module gives a runner one compact, provider-neutral check
before writing the reward file so a wiring mistake fails fast instead of after
a long agent run.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REWARD_CONTRACT_SCHEMA_VERSION = "verifier_reward_contract_v0"
REWARD_MAX_ENTRIES = 64


def _numeric(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return not (isinstance(value, float) and (math.isnan(value) or math.isinf(value)))


def verify_verifier_reward_json(reward: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one verifier reward mapping against the numeric-only contract.

    Returns a compact public-safe receipt. Raw reward values are not echoed;
    only stable counts, labels, and reason codes are emitted.
    """

    if not isinstance(reward, Mapping):
        return {
            "ok": False,
            "schema_version": REWARD_CONTRACT_SCHEMA_VERSION,
            "valid": False,
            "reason_code": "reward_not_object",
            "entry_count": 0,
            "invalid_keys": [],
        }
    entries = dict(reward)
    invalid_keys = [
        str(key) for key, value in entries.items() if not _numeric(value)
    ]
    too_many = len(entries) > REWARD_MAX_ENTRIES
    valid = not invalid_keys and not too_many
    return {
        "ok": valid,
        "schema_version": REWARD_CONTRACT_SCHEMA_VERSION,
        "valid": valid,
        "reason_code": (
            "ok"
            if valid
            else "reward_non_numeric_values"
            if invalid_keys
            else "reward_too_many_entries"
        ),
        "entry_count": len(entries),
        "invalid_keys": sorted(invalid_keys),
    }


def verify_verifier_reward_file(path: str | Path) -> dict[str, Any]:
    """Read one reward.json path and validate it against the numeric contract.

    The file content is parsed in memory and never copied into the returned
    receipt. Missing or malformed JSON is reduced to a fail-closed reason code.
    """

    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "ok": False,
            "schema_version": REWARD_CONTRACT_SCHEMA_VERSION,
            "valid": False,
            "reason_code": "reward_file_missing",
            "entry_count": 0,
            "invalid_keys": [],
        }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "ok": False,
            "schema_version": REWARD_CONTRACT_SCHEMA_VERSION,
            "valid": False,
            "reason_code": "reward_file_invalid",
            "entry_count": 0,
            "invalid_keys": [],
        }
    return verify_verifier_reward_json(payload)

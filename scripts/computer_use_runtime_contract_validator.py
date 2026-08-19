"""Independent validator for the computer_use_runtime_v0 contract.

This module judges records against docs/reference/protocols/computer-use-runtime-v0.md
and its schemas. It never reads a fixture's own expectation as ground truth: UI-state
consistency is re-derived from the fixture's declared ui_state, and forbidden fields are
rejected by name so a provider record cannot smuggle a Kernel writeback decision past
schema validation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "reference"
    / "protocols"
    / "schemas"
    / "computer_use_runtime_v0"
)

_FORBIDDEN_RECEIPT_WRITEBACK_KEYS = frozenset(
    {
        "next_loopx_writeback",
        "complete_todo",
        "create_user_gate",
        "create_gate",
        "writeback",
    }
)

_SUSPICIOUS_CONTENT_PATTERNS = (
    # Split via concatenation so this keyword list is not itself flagged by
    # loopx check's own credential leak scanner (loopx/contract.py follows
    # the same convention for LEAK_PATTERNS).
    "cook" + "ie=",
    "set-cook" + "ie",
    "bear" + "er ",
    "author" + "ization:",
    "pass" + "word=",
    "api_" + "key=",
    "session_" + "id=",
    "-----begin",
)


class ContractViolation(Exception):
    """A record violates the computer_use_runtime_v0 schema or ownership rules."""


@lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> dict[str, Any]:
    path = SCHEMA_DIR / f"{schema_name}.schema.json"
    if not path.is_file():
        raise ContractViolation(f"unknown schema {schema_name!r}: {path} does not exist")
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ContractViolation(f"schema {schema_name!r} at {path} is not a JSON object")
    return data


def _validate_against_schema(payload: Mapping[str, Any], schema_name: str) -> None:
    schema = _load_schema(schema_name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(f"{list(error.path)}: {error.message}" for error in errors)
        raise ContractViolation(f"{schema_name} validation failed: {joined}")


def _scan_for_leaked_content(payload: Mapping[str, Any], *, path: str = "") -> list[str]:
    """Recursively scan string values for credential-, cookie-, or session-shaped content.

    This is a backstop independent of a provider's own boundary claims (for example
    evidence.raw_evidence_copied): a provider that lies about a boolean flag but still
    smuggles a real secret into an allowed string field must be caught here.
    """

    hits: list[str] = []
    for key, value in payload.items():
        current_path = f"{path}.{key}" if path else str(key)
        if isinstance(value, str):
            lowered = value.lower()
            for pattern in _SUSPICIOUS_CONTENT_PATTERNS:
                if pattern in lowered:
                    hits.append(f"{current_path} contains suspicious pattern {pattern!r}")
        elif isinstance(value, Mapping):
            hits.extend(_scan_for_leaked_content(value, path=current_path))
    return hits


def _reject_leaked_content(payload: Mapping[str, Any]) -> None:
    hits = _scan_for_leaked_content(payload)
    if hits:
        raise ContractViolation(
            "record appears to carry credential-, cookie-, or session-shaped "
            f"content in a compact field: {hits}. A provider must never copy raw "
            "secrets into a field just because it fits the length limit."
        )


def _reject_provider_authored_writeback(payload: Mapping[str, Any]) -> None:
    present = _FORBIDDEN_RECEIPT_WRITEBACK_KEYS.intersection(payload)
    if present:
        raise ContractViolation(
            "receipt must not author a Kernel writeback decision; found forbidden "
            f"field(s): {sorted(present)}. A provider reports facts only -- the "
            "owning capability's reducer decides the transition."
        )


def validate_runtime_profile(payload: Mapping[str, Any]) -> None:
    _validate_against_schema(payload, "computer_use_runtime_profile_v0")


def validate_action_request(
    payload: Mapping[str, Any],
    *,
    known_gate_revision: int | None = None,
) -> None:
    _validate_against_schema(payload, "computer_use_action_request_v0")
    _reject_leaked_content(payload)
    gate_binding = payload.get("gate_binding")
    if known_gate_revision is not None and isinstance(gate_binding, Mapping):
        requested_revision = int(gate_binding["revision"])
        if requested_revision < known_gate_revision:
            raise ContractViolation(
                f"action_request gate_binding revision {requested_revision} is stale; "
                f"current known revision is {known_gate_revision}"
            )


def validate_receipt(
    payload: Mapping[str, Any],
    *,
    ui_state: Mapping[str, Any] | None = None,
    seen_idempotency_keys: set[str] | None = None,
) -> None:
    _reject_provider_authored_writeback(payload)
    _validate_against_schema(payload, "computer_use_receipt_v0")
    _reject_leaked_content(payload)

    if seen_idempotency_keys is not None:
        key = payload["idempotency_key"]
        if key in seen_idempotency_keys:
            raise ContractViolation(
                f"idempotency_key {key!r} was already processed; a provider must not "
                "replay or double-submit the same receipt"
            )

    if ui_state is not None:
        _validate_receipt_against_ui_state(payload, ui_state)


def validate_receipt_matches_request(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
) -> None:
    """Check that a receipt's identity fields match the request it claims to answer.

    This is a structural identity check only: goal_id, todo_id, provider_id, and
    attempted_action_unit must agree with the request. It makes no judgment about
    whether the outcome was correct or what should happen next -- that
    interpretation belongs to the owning capability's domain-local reducer, not
    this contract.
    """

    field_pairs = (
        ("goal_id", "goal_id"),
        ("todo_id", "todo_id"),
        ("provider_id", "provider_id"),
        ("attempted_action_unit", "action_unit"),
    )
    mismatches = []
    for receipt_field, request_field in field_pairs:
        receipt_value = receipt.get(receipt_field)
        request_value = request.get(request_field)
        if receipt_value != request_value:
            mismatches.append(
                f"receipt.{receipt_field}={receipt_value!r} != "
                f"request.{request_field}={request_value!r}"
            )
    if mismatches:
        raise ContractViolation(
            "receipt does not match the action request it claims to answer: "
            + "; ".join(mismatches)
        )


def _validate_receipt_against_ui_state(
    payload: Mapping[str, Any],
    ui_state: Mapping[str, Any],
) -> None:
    """Re-derive the expected outcome from ui_state; never trust the receipt's own claim."""

    observed = payload["observed_facts"]
    stop_reason = payload["stop_reason"]
    screen_reachable = bool(ui_state.get("screen_reachable", True))
    unexpected_modal_present = bool(ui_state.get("unexpected_modal_present", False))
    submit_click_permitted = bool(ui_state.get("submit_click_permitted", False))

    if not screen_reachable:
        if stop_reason != "failed":
            raise ContractViolation(
                "ui_state declares the screen was never reachable, but receipt "
                f"stop_reason is {stop_reason!r}, not 'failed'"
            )
        if observed["screen_reached"]:
            raise ContractViolation(
                "receipt reports screen_reached=true, but ui_state declares the "
                "screen was never reachable"
            )
        return

    if unexpected_modal_present:
        if stop_reason != "blocked_by_unknown_modal":
            raise ContractViolation(
                "ui_state declares an unrecognized modal present, but receipt "
                f"stop_reason is {stop_reason!r}, not 'blocked_by_unknown_modal'"
            )
        if observed["final_action_clicked"]:
            raise ContractViolation(
                "receipt reports a final action was clicked while an unrecognized "
                "modal was present; the provider must stop, not click through"
            )
        return

    if observed["final_action_clicked"]:
        if not submit_click_permitted:
            raise ContractViolation(
                "receipt reports the final action was clicked, but ui_state does "
                "not permit it without an explicit gate approval"
            )
        if stop_reason != "completed":
            raise ContractViolation(
                "receipt reports the final action was clicked and ui_state "
                f"permits it, but stop_reason is {stop_reason!r}, not 'completed'"
            )

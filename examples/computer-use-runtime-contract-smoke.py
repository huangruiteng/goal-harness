#!/usr/bin/env python3
"""Smoke-test the computer_use_runtime_v0 contract against declarative fixtures.

Each fixture in computer-use-runtime-contract-fixtures/ describes a scenario (a request,
a receipt, and/or a ui_state ground truth) and an expected accept/reject outcome. The
validator judges each fixture independently -- it never reads a fixture's own "expect"
field as the basis for its decision, only as the assertion this smoke checks afterward.
No real screenshots, browser/desktop session, or model call is used anywhere here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from computer_use_runtime_contract_validator import (  # noqa: E402
    ContractViolation,
    validate_action_request,
    validate_receipt,
    validate_receipt_matches_request,
    validate_runtime_profile,
)

FIXTURES_DIR = REPO_ROOT / "examples" / "computer-use-runtime-contract-fixtures"


def _run_fixture(fixture: dict[str, Any]) -> None:
    case_id = fixture["case_id"]
    expect = fixture["expect"]
    assert expect in ("accept", "reject"), fixture

    violation: ContractViolation | None = None
    try:
        request = fixture.get("request")
        if request is not None:
            validate_action_request(
                request,
                known_gate_revision=fixture.get("known_gate_revision"),
            )
        receipt = fixture.get("receipt")
        if receipt is not None:
            seen_keys = fixture.get("seen_idempotency_keys")
            validate_receipt(
                receipt,
                ui_state=fixture.get("ui_state"),
                seen_idempotency_keys=set(seen_keys) if seen_keys is not None else None,
            )
        if request is not None and receipt is not None:
            validate_receipt_matches_request(receipt, request)
    except ContractViolation as error:
        violation = error

    if expect == "accept":
        assert violation is None, f"{case_id} expected accept but got: {violation}"
    else:
        assert violation is not None, f"{case_id} expected reject but validation passed"
        expected_reason = fixture.get("expected_reason_contains")
        if expected_reason:
            assert expected_reason in str(violation), (
                f"{case_id} rejected for the wrong reason: {violation}"
            )


def assert_fixtures_pass() -> list[tuple[str, str]]:
    fixture_paths = sorted(FIXTURES_DIR.glob("*.json"))
    assert fixture_paths, f"no fixtures found under {FIXTURES_DIR}"
    cases = []
    for path in fixture_paths:
        fixture = json.loads(path.read_text())
        _run_fixture(fixture)
        cases.append((fixture["case_id"], fixture["expect"]))
    return cases


def assert_runtime_profile_boundary_is_enforced() -> None:
    profile: dict[str, Any] = {
        "schema_version": "computer_use_runtime_profile_v0",
        "provider_id": "computer_use_runtime",
        "host_kind": "browser_or_desktop_runtime",
        "visibility": "visible_or_replayable",
        "provider_primitives": {
            "screenshots": "host_owned",
            "external_write": "gated",
            "private_source_read": "gated",
        },
        "boundary": {
            "credentials_copied": False,
            "cookies_exported": False,
            "raw_screenshots_copied": False,
            "raw_private_bodies_copied": False,
            "external_write_allowed_without_gate": False,
        },
    }
    validate_runtime_profile(profile)

    tampered_boundary = dict(profile["boundary"])
    tampered_boundary["credentials_copied"] = True
    tampered = dict(profile)
    tampered["boundary"] = tampered_boundary
    try:
        validate_runtime_profile(tampered)
    except ContractViolation:
        pass
    else:
        raise AssertionError("profile claiming credentials_copied=true must be rejected")


def main() -> int:
    cases = assert_fixtures_pass()
    assert_runtime_profile_boundary_is_enforced()
    accept_count = sum(1 for _, expect in cases if expect == "accept")
    reject_count = sum(1 for _, expect in cases if expect == "reject")
    print(
        "computer-use-runtime-contract-smoke ok "
        f"cases={len(cases)} accept={accept_count} reject={reject_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

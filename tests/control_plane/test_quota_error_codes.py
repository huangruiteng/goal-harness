from __future__ import annotations

import json

import pytest

from loopx.control_plane.quota.error_codes import (
    QuotaCommandValidationError,
    QuotaIdentityPrecondition,
    QuotaIdentityPreconditionError,
    quota_error_code,
)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            QuotaCommandValidationError("bad argument"),
            "quota_invalid_arguments",
        ),
        (
            QuotaIdentityPreconditionError(
                QuotaIdentityPrecondition.REGISTERED_AGENT_ROSTER_PRESENT,
                agent_id="agent-alpha",
            ),
            "quota_agent_registry_roster_missing",
        ),
        (ValueError("bad state value"), "quota_unexpected_collection_error"),
        (OSError("state unavailable"), "quota_state_io_failed"),
        (PermissionError("state denied"), "quota_state_permission_denied"),
        (KeyError("missing"), "quota_state_missing_field"),
        (TypeError("bad shape"), "quota_state_shape_error"),
        (
            json.JSONDecodeError("invalid json", "doc", 0),
            "quota_state_invalid_json",
        ),
        (RuntimeError("unexpected"), "quota_unexpected_collection_error"),
    ],
)
def test_quota_error_code_maps_typed_exceptions(
    exc: BaseException,
    expected: str,
) -> None:
    assert quota_error_code(exc) == expected

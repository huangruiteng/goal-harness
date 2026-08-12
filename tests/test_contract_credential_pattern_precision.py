from __future__ import annotations

from pathlib import Path

import pytest

from loopx.contract import scan_public_boundary


AUTH_HEADER = "Author" + "ization:"
BEARER = "Bear" + "er"
TOKEN_ASSIGN = "tok" + "en="
PASSWORD_ASSIGN = "pass" + "word="
REAL_BEARER_VALUE = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"


def _scan_line(tmp_path: Path, line: str) -> dict[str, list[str]]:
    (tmp_path / "sample.md").write_text(f"{line}\n", encoding="utf-8")
    payload = scan_public_boundary([tmp_path])
    return {
        "hits": payload["hits"],
        "credential_reference_hits": payload.get("credential_reference_hits", []),
    }


@pytest.mark.parametrize(
    "line",
    [
        f'curl -H "{AUTH_HEADER} {BEARER} $SERVICE_TOKEN" https://example.test',
        f"{AUTH_HEADER} {BEARER} ${{SERVICE_TOKEN}}",
        f"{PASSWORD_ASSIGN}%SERVICE_SECRET%",
        f'{PASSWORD_ASSIGN}os.environ["SERVICE_SECRET"]',
        f"{TOKEN_ASSIGN}process.env.SERVICE_TOKEN",
        f'{TOKEN_ASSIGN}"$(cat "$BASE/.env")"',
        f"{AUTH_HEADER} {BEARER} <SERVICE_TOKEN>",
        f'{PASSWORD_ASSIGN}"changeme"',
        f"the API takes a {BEARER} token (JWT, 1h expiry)",
        f"{PASSWORD_ASSIGN}service_password, secure=True",
        f"{TOKEN_ASSIGN}config.token)",
        AUTH_HEADER,
        "AK" + "IAIOSFODNN7EXAMPLE",
    ],
)
def test_non_literal_credential_hits_are_downgraded(tmp_path: Path, line: str) -> None:
    payload = _scan_line(tmp_path, line)

    assert payload["hits"] == []
    assert len(payload["credential_reference_hits"]) == 1


@pytest.mark.parametrize(
    "line",
    [
        f"{AUTH_HEADER} {BEARER} {REAL_BEARER_VALUE}",
        f"{TOKEN_ASSIGN}{REAL_BEARER_VALUE}",
        f"{PASSWORD_ASSIGN}hunter2",
        f'{PASSWORD_ASSIGN}"hunter2",',
        "AK" + "IA1234567890ABCDEF",
    ],
)
def test_literal_credential_hits_stay_errors(tmp_path: Path, line: str) -> None:
    payload = _scan_line(tmp_path, line)

    assert len(payload["hits"]) == 1
    assert payload["hits"][0].endswith(": credential")
    assert payload["credential_reference_hits"] == []


def test_a_literal_on_a_line_with_references_still_fails(tmp_path: Path) -> None:
    line = f'{PASSWORD_ASSIGN}$SERVICE_SECRET {TOKEN_ASSIGN}{REAL_BEARER_VALUE}'

    payload = _scan_line(tmp_path, line)

    assert len(payload["hits"]) == 1
    assert payload["credential_reference_hits"] == []

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


FORBIDDEN_KEY_TOKENS = {
    "account",
    "auth",
    "body",
    "cookie",
    "credential",
    "holding",
    "local",
    "password",
    "portfolio",
    "private",
    "raw",
    "secret",
    "token",
    "trade",
    "transcript",
}
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+", re.IGNORECASE),
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _key_tokens(value: object) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", str(value).lower()) if part}


def reject_forbidden_material(value: object, *, path: str = "input") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            forbidden = _key_tokens(key) & FORBIDDEN_KEY_TOKENS
            if forbidden:
                raise ValueError(
                    f"{path} contains forbidden key token(s): "
                    + ", ".join(sorted(forbidden))
                )
            reject_forbidden_material(item, path=f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reject_forbidden_material(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and any(
        pattern.search(value) for pattern in FORBIDDEN_VALUE_PATTERNS
    ):
        raise ValueError(
            f"{path} contains private path, auth material, or credential-like text"
        )

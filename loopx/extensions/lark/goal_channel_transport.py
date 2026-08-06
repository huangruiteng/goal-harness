from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from typing import Any

from .presentation.kanban import CommandRunner


CHAT_ID_PATTERN = re.compile(r"oc_[A-Za-z0-9_-]+")
MESSAGE_ID_PATTERN = re.compile(r"om_[A-Za-z0-9_-]+")
APP_ID_PATTERN = re.compile(r"cli_[A-Za-z0-9_-]+")
SAFE_PROFILE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")


def json_payload(result: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = result.get("stdout")
    try:
        payload = json.loads(str(raw or ""))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def find_first_string(
    payload: Any,
    keys: set[str],
    pattern: re.Pattern[str],
) -> str | None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and pattern.fullmatch(value):
                return value
        for value in payload.values():
            found = find_first_string(value, keys, pattern)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_first_string(value, keys, pattern)
            if found:
                return found
    return None


def contains_exact_field(
    payload: Any,
    key: str,
    expected: str,
) -> bool:
    if isinstance(payload, Mapping):
        if str(payload.get(key) or "") == expected:
            return True
        return any(
            contains_exact_field(value, key, expected)
            for value in payload.values()
        )
    if isinstance(payload, list):
        return any(contains_exact_field(value, key, expected) for value in payload)
    return False


def payload_contains_text(payload: Any, expected: str) -> bool:
    if isinstance(payload, Mapping):
        return any(payload_contains_text(value, expected) for value in payload.values())
    if isinstance(payload, list):
        return any(payload_contains_text(value, expected) for value in payload)
    return isinstance(payload, str) and expected in payload


def payload_contains_exact(payload: Any, expected: str) -> bool:
    if isinstance(payload, Mapping):
        return any(payload_contains_exact(value, expected) for value in payload.values())
    if isinstance(payload, list):
        return any(payload_contains_exact(value, expected) for value in payload)
    return isinstance(payload, str) and payload == expected


def call(
    runner: CommandRunner,
    args: list[str],
) -> Mapping[str, Any]:
    try:
        return runner(args, None, 30)
    except (OSError, subprocess.SubprocessError):
        return {"returncode": 1, "stdout": "", "stderr": ""}


def profile_args(profile: str | None) -> list[str]:
    if not profile:
        return []
    if not SAFE_PROFILE_PATTERN.fullmatch(profile):
        raise ValueError("Lark profile must be a local safe-name token")
    return ["--profile", profile]


def lark_args(
    *,
    cli_bin: str,
    profile: str | None,
    tail: list[str],
) -> list[str]:
    return [cli_bin, *profile_args(profile), *tail]


def auth_verified(
    *,
    runner: CommandRunner,
    cli_bin: str,
    profile: str | None,
    identity: str,
    expected_bot_name: str | None,
) -> bool:
    auth = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=["auth", "status", "--verify", "--json"],
        ),
    )
    identities = json_payload(auth).get("identities")
    current = identities.get(identity) if isinstance(identities, Mapping) else None
    if auth.get("returncode") != 0 or not isinstance(current, Mapping):
        return False
    verified = current.get("available") is True and current.get("verified") is True
    if identity == "bot" and expected_bot_name:
        return verified and str(current.get("appName") or "") == expected_bot_name
    return verified


def verified_app_id(
    *,
    runner: CommandRunner,
    cli_bin: str,
    profile: str | None,
) -> str | None:
    auth = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=["auth", "status", "--verify", "--json"],
        ),
    )
    app_id = str(json_payload(auth).get("appId") or "")
    if auth.get("returncode") != 0 or not APP_ID_PATTERN.fullmatch(app_id):
        return None
    return app_id


def chat_verified(
    *,
    runner: CommandRunner,
    cli_bin: str,
    profile: str | None,
    identity: str,
    chat_id: str,
) -> bool:
    result = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "chats",
                "get",
                "--chat-id",
                chat_id,
                "--as",
                identity,
                "--format",
                "json",
            ],
        ),
    )
    return result.get("returncode") == 0


def bot_membership_verified(
    *,
    runner: CommandRunner,
    cli_bin: str,
    profile: str | None,
    chat_id: str,
    app_id: str,
) -> bool:
    result = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "+chat-members-list",
                "--chat-id",
                chat_id,
                "--member-types",
                "bot",
                "--as",
                "user",
                "--format",
                "json",
            ],
        ),
    )
    return bool(
        result.get("returncode") == 0
        and contains_exact_field(json_payload(result), "app_id", app_id)
    )


def message_readback_verified(
    *,
    runner: CommandRunner,
    cli_bin: str,
    profile: str | None,
    identity: str,
    message_id: str,
    expected_text: str,
) -> bool:
    result = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "+messages-mget",
                "--message-ids",
                message_id,
                "--as",
                identity,
                "--no-reactions",
                "--format",
                "json",
            ],
        ),
    )
    payload = json_payload(result)
    return bool(
        result.get("returncode") == 0
        and contains_exact_field(payload, "message_id", message_id)
        and payload_contains_text(payload, expected_text)
    )


def pin_readback_verified(
    *,
    runner: CommandRunner,
    cli_bin: str,
    profile: str | None,
    identity: str,
    chat_id: str,
    message_id: str,
) -> bool:
    result = call(
        runner,
        lark_args(
            cli_bin=cli_bin,
            profile=profile,
            tail=[
                "im",
                "pins",
                "list",
                "--chat-id",
                chat_id,
                "--as",
                identity,
                "--format",
                "json",
            ],
        ),
    )
    return bool(
        result.get("returncode") == 0
        and contains_exact_field(json_payload(result), "message_id", message_id)
    )

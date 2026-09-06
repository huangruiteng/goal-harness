"""Default bot setup must include native mention identity verification."""

from urllib.parse import parse_qs, urlparse

from loopx.extensions.lark.bot_scopes import (
    CORE_BOT_SCOPES,
    RECOMMENDED_BOT_SCOPES,
    recommended_bot_scope_apply_url,
)


def test_default_bot_scope_bundle_and_apply_url_include_member_read() -> None:
    scope = "im:chat.members:read"
    assert scope in CORE_BOT_SCOPES
    assert scope in RECOMMENDED_BOT_SCOPES
    query = parse_qs(urlparse(recommended_bot_scope_apply_url("cli_example")).query)
    assert scope in query["scopes"][0].split(",")

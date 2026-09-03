from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def turn_controller_advisory_primary(
    decision: Mapping[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Resolve the default for Turn's model-free outer-controller phase."""

    interaction = decision.get("interaction_contract")
    cli_channel = (
        interaction.get("cli_channel")
        if isinstance(interaction, Mapping)
        else None
    )
    if not isinstance(cli_channel, Mapping) or (
        cli_channel.get("selection_required") is not True
    ):
        return None
    portfolio = decision.get("action_portfolio")
    if not isinstance(portfolio, Mapping) or (
        portfolio.get("schema_version") != "quota_action_portfolio_v2"
    ):
        raise ValueError(
            "Turn action selection requires a typed advisory action portfolio"
        )
    policy = portfolio.get("selection_policy")
    primary = portfolio.get("primary")
    todo_id = (
        str(primary.get("todo_id") or "").strip()
        if isinstance(primary, Mapping)
        else ""
    )
    if (
        not isinstance(policy, Mapping)
        or policy.get("requires_explicit_turn_binding") is not True
        or not todo_id
    ):
        raise ValueError("Turn advisory action portfolio has no bindable primary")
    return todo_id, dict(portfolio)

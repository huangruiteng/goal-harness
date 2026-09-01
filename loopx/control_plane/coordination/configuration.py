"""Normalization rules for goal-level coordination configuration."""

from __future__ import annotations


def normalize_goal_write_scope(values: list[str] | None) -> list[str] | None:
    """Split comma-delimited goal scopes and preserve first-seen order.

    Goal configuration intentionally accepts a wider token vocabulary than a
    Todo's ``required_write_scopes`` contract, so its stricter normalizer is
    not interchangeable with this rule.
    """

    if values is None:
        return None
    scopes: list[str] = []
    for value in values:
        for part in str(value).split(","):
            scope = part.strip()
            if scope and scope not in scopes:
                scopes.append(scope)
    return scopes


__all__ = ["normalize_goal_write_scope"]

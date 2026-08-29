from __future__ import annotations

from enum import StrEnum


PROGRESS_OBSERVATION_SCHEMA_VERSION = "typed_progress_observation_v0"


class ProgressResultClass(StrEnum):
    """Typed result classes shared by progress writers and settlement readers."""

    ADVANCED = "advanced"
    UNCHANGED = "unchanged"
    BLOCKED = "blocked"
    EXPLORATION_EXHAUSTED = "exploration_exhausted"
    NO_FOLLOWUP = "no_followup"

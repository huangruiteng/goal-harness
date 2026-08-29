from __future__ import annotations

import re
from enum import StrEnum
from typing import Any


PROGRESS_OBSERVATION_SCHEMA_VERSION = "typed_progress_observation_v0"
_STABLE_PROGRESS_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def normalize_progress_identifier(value: Any) -> str | None:
    """Return one opaque public-safe progress identifier or ``None``."""

    normalized = str(value or "").strip()
    return normalized if _STABLE_PROGRESS_ID.fullmatch(normalized) else None


class ProgressResultClass(StrEnum):
    """Typed result classes shared by progress writers and settlement readers."""

    ADVANCED = "advanced"
    UNCHANGED = "unchanged"
    BLOCKED = "blocked"
    EXPLORATION_EXHAUSTED = "exploration_exhausted"
    NO_FOLLOWUP = "no_followup"

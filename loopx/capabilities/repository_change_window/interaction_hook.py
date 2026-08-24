from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...control_plane.capability_hooks import (
    INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
    InteractionProjectionHookRegistration,
)
from .git_hook import git_hook_provider_status
from .repository import RepositoryChangeWindowError


HOOK_ID = "repository_change_window.repository_delivery"
CAPABILITY_ID = "repository-change-window"


def repository_delivery_interaction_hook(
    *,
    repo_path: Path,
) -> InteractionProjectionHookRegistration:
    """Register the capability's path-free local delivery projection."""

    def produce() -> Mapping[str, Any]:
        try:
            status = git_hook_provider_status(repo_path=repo_path)
        except (OSError, RepositoryChangeWindowError):
            return _not_applicable_result()
        return {
            "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
            "hook_id": HOOK_ID,
            "capability_id": CAPABILITY_ID,
            "phase": "interaction_projection",
            "status": "candidate",
            "projection_slot": "repository_delivery",
            "payload": status,
        }

    return InteractionProjectionHookRegistration(
        hook_id=HOOK_ID,
        capability_id=CAPABILITY_ID,
        projection_slots=("repository_delivery",),
        requested_read_scope=("repository_status",),
        producer=produce,
    )


def _not_applicable_result() -> dict[str, Any]:
    return {
        "schema_version": INTERACTION_PROJECTION_HOOK_RESULT_SCHEMA_VERSION,
        "hook_id": HOOK_ID,
        "capability_id": CAPABILITY_ID,
        "phase": "interaction_projection",
        "status": "not_applicable",
        "projection_slot": None,
        "payload": None,
    }

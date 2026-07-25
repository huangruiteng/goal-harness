"""Thin profile-to-evidence orchestration for Decision Context."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..context_providers import build_context_provider
from ..context_providers.base import ContextProvider
from .assembler import (
    DecisionContextAssembly,
    DecisionEvidenceRebaser,
    assemble_decision_evidence,
)
from .profile import (
    DecisionContextProfile,
    resolve_decision_context_activation,
)
from .providers import build_decision_source_provider
from .sources import DecisionSourceProvider, DecisionSourceScan, DecisionSourceSpec


class _UnavailableContextProvider:
    """Preserve a public fail-open receipt when provider construction fails."""

    provider_id = "context-provider"

    def retrieve(self, **_: Any) -> Any:
        raise RuntimeError("context provider is unavailable")

    def sync(self, **_: Any) -> Any:
        raise RuntimeError("context provider is unavailable")


class _UnavailableDecisionSourceProvider:
    """Report a configured-but-invalid binding without exposing its config."""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    def scan(
        self,
        *,
        source: DecisionSourceSpec,
        after_cursor: str | None,
        before: str,
        limit: int,
        timeout_seconds: float,
        observed_at: str,
    ) -> DecisionSourceScan:
        del after_cursor, before, limit, timeout_seconds
        return DecisionSourceScan(
            provider_id=self.provider_id,
            source_id=source.source_id,
            status="unavailable",
            observed_at=observed_at,
            requested_limit=source.max_changes,
            reason_code="provider_configuration_failed",
        )

    def exact_read(self, **_: Any) -> Any:
        raise RuntimeError("decision source provider is unavailable")


def load_private_decision_cursors(
    path: Path | None,
    *,
    profile: DecisionContextProfile,
) -> dict[str, str]:
    """Load private cursors without projecting their values into public output."""

    if path is None:
        return {}
    try:
        with path.expanduser().open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("decision-context cursor state is unavailable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("decision-context cursor state must be an object")

    source_ids = {source.source_id for source in profile.sources}
    unexpected = sorted(str(key) for key in payload if str(key) not in source_ids)
    if unexpected:
        raise ValueError(
            "decision-context cursor state contains unknown source ids: "
            + ", ".join(unexpected)
        )

    cursors: dict[str, str] = {}
    for source_id, value in payload.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "decision-context cursor values must be non-empty strings"
            )
        cursor = value.strip()
        cursors[str(source_id)] = cursor
    return cursors


def _build_source_providers(
    profile: DecisionContextProfile,
    *,
    sources: Sequence[DecisionSourceSpec],
) -> dict[str, DecisionSourceProvider]:
    enabled_provider_ids = {source.provider_id for source in sources}
    providers: dict[str, DecisionSourceProvider] = {}
    for provider_id, binding in profile.provider_binding_map().items():
        if provider_id not in enabled_provider_ids:
            continue
        try:
            providers[provider_id] = build_decision_source_provider(binding)
        except Exception:
            providers[provider_id] = _UnavailableDecisionSourceProvider(provider_id)
    return providers


def _selected_sources(
    profile: DecisionContextProfile,
    *,
    source_ids: Collection[str] | None,
) -> tuple[DecisionSourceSpec, ...]:
    enabled = {source.source_id: source for source in profile.sources if source.enabled}
    if source_ids is None:
        return tuple(
            source
            for source in profile.sources
            if source.enabled and source.scan_mode != "on_demand"
        )
    if isinstance(source_ids, (str, bytes)):
        raise TypeError("source_ids must be a collection of source ids")
    selected_ids = {str(source_id).strip() for source_id in source_ids}
    unavailable = sorted(
        source_id for source_id in selected_ids if source_id not in enabled
    )
    if unavailable:
        raise ValueError(
            "requested decision sources are unknown or disabled: "
            + ", ".join(unavailable)
        )
    return tuple(enabled[source_id] for source_id in sorted(selected_ids))


def _build_advisory_context_provider(
    profile: DecisionContextProfile,
) -> ContextProvider | None:
    if profile.context_provider is None:
        return None
    private_config = profile.context_provider.get("config", {})
    binding = {
        "provider": profile.context_provider["provider"],
        **(dict(private_config) if isinstance(private_config, Mapping) else {}),
    }
    try:
        return build_context_provider(binding)
    except Exception:
        return _UnavailableContextProvider()


def assemble_profile_decision_evidence(
    *,
    goal_id: str,
    agent_id: str,
    profile_path: Path | None,
    decision_id: str,
    observed_at: str,
    before: str,
    rebase: DecisionEvidenceRebaser,
    cursor_path: Path | None = None,
    source_ids: Collection[str] | None = None,
    recall_query: str = "current decision evidence",
    recall_query_summary: str = "current decision evidence",
    timeout_seconds: float | None = None,
) -> tuple[dict[str, Any], DecisionContextAssembly | None]:
    """Resolve one enabled profile and assemble evidence without applying cursors.

    The caller owns domain reasoning through ``rebase``. Raw exact reads and
    advisory recall stay in-process, while the returned public packet contains
    only opaque refs and compact evidence. ``proposed_cursors`` remain private
    and must not be persisted until the caller validates lifecycle writeback.
    """

    activation, profile = resolve_decision_context_activation(
        goal_id=goal_id,
        agent_id=agent_id,
        profile_path=profile_path,
    )
    if activation["available"] is not True or profile is None:
        return activation, None

    context_config = profile.context_provider or {}
    configured_timeout = context_config.get("timeout_seconds", 10.0)
    effective_timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else float(configured_timeout)
    )
    cursors = load_private_decision_cursors(cursor_path, profile=profile)
    sources = _selected_sources(profile, source_ids=source_ids)
    assembly = assemble_decision_evidence(
        goal_id=goal_id,
        decision_id=decision_id,
        observed_at=observed_at,
        before=before,
        sources=sources,
        source_providers=_build_source_providers(profile, sources=sources),
        cursors=cursors,
        rebase=rebase,
        context_provider=_build_advisory_context_provider(profile),
        context_namespace=str(
            context_config.get("namespace") or "decision-context"
        ),
        context_scope_ref=str(context_config.get("scope_ref") or "goal"),
        recall_query=recall_query,
        recall_query_summary=recall_query_summary,
        recall_limit=int(context_config.get("max_results", 5)),
        timeout_seconds=effective_timeout,
    )
    return activation, assembly

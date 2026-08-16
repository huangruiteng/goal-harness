"""Provider-neutral usage capture seam for per-goal token/cost/duration.

This module is the capture layer described in
``docs/architecture/rfcs/goal-usage-token-cost-v0.md``. It defines the
normalized, public-safe per-run usage shape and the consumption side of the
seam: ``collect_usage_for_run`` reads a normalized ``usage`` block off a run
dict for the aggregate loop in ``usage_summary``. It is provider-agnostic and
performs no file IO.

The ingestion side (writing a ``usage`` block onto each runtime's run records)
is a follow-up slice and lands together with its callers and tests.

Only aggregate numeric usage lives here. Prompts, completions, tool output,
credentials, and anything that reconstructs a conversation are never captured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UsageSample:
    """Normalized, public-safe per-run LLM usage.

    Every field is aggregate numeric metadata. ``cost_usd`` and
    ``duration_ms`` may be zero when a runtime cannot measure them; the caller
    (the ingestion side) is responsible for filling them when the model id and
    wall-time are known.
    """

    input_tokens: int
    output_tokens: int
    cache_tokens: int
    cost_usd: float
    duration_ms: int
    provider: str
    model: str


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        coerced = int(value)
        return coerced if coerced >= 0 else None
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        coerced = float(value)
        return coerced if coerced >= 0 else None
    return None


def collect_usage_for_run(run: dict[str, Any]) -> UsageSample | None:
    """Return normalized usage for a run, or ``None`` if the run reports none.

    Reads an optional ``usage`` block on the run dict. Runtimes that have not
    yet been wired to report usage contribute nothing, so the aggregate
    degrades gracefully to the prior run-history behavior.
    """
    usage = run.get("usage")
    if not isinstance(usage, dict):
        return None
    input_tokens = _coerce_int(usage.get("input_tokens"))
    output_tokens = _coerce_int(usage.get("output_tokens"))
    # A run claiming zero input and zero output has nothing aggregate-worthy.
    if input_tokens is None and output_tokens is None:
        return None
    return UsageSample(
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        cache_tokens=_coerce_int(usage.get("cache_tokens")) or 0,
        cost_usd=_coerce_float(usage.get("cost_usd")) or 0.0,
        duration_ms=_coerce_int(usage.get("duration_ms")) or 0,
        provider=str(usage.get("provider") or "unknown"),
        model=str(usage.get("model") or "unknown"),
    )

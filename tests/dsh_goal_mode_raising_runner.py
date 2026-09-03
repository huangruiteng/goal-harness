"""Hermetic failing dsh runner: raises a bare transport-layer exception.

Covers the exception classification path (no structured signal, prose
fallback only). Not a pytest module (no ``test_`` prefix).
"""

from __future__ import annotations


def run_dsh_turn(**_kwargs: object) -> str:
    raise RuntimeError("selected model is at capacity")

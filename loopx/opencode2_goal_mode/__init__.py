from __future__ import annotations

from importlib import resources


def worker_source() -> str:
    return resources.files(__package__).joinpath("opencode2-goal-worker.mjs").read_text(
        encoding="utf-8"
    )

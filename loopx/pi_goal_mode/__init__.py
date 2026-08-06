from __future__ import annotations

from importlib import resources


def extension_source() -> str:
    return resources.files(__package__).joinpath("loopx-goal.ts").read_text(encoding="utf-8")


def runtime_source() -> str:
    return resources.files(__package__).joinpath("pi-goal-loop-runtime.mjs").read_text(
        encoding="utf-8"
    )

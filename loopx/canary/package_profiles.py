from __future__ import annotations

from typing import Any


PACKAGE_QUALIFICATION_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "id": "dsh-loopx-plugin",
        "title": "DeepSeek Harness LoopX plugin",
        "purpose": (
            "Validate the co-located DSH plugin's TypeScript contracts, tests, "
            "build artifact, profile lifecycle, and real runtime integration."
        ),
        "catalog_families": ["State And Boundary", "Work Routing"],
        "trigger_hints": (
            "dsh-loopx-plugin",
            "packages/dsh-loopx-plugin/",
            "deepseek harness",
            "goalbar",
        ),
        "checks": [
            {
                "command": "python3 examples/canary/dsh-loopx-plugin-validation.py --phase quality",
                "tier": "default",
                "reason": "runs package typecheck and unit/integration tests without external services",
            },
            {
                "command": "python3 examples/canary/dsh-loopx-plugin-validation.py --phase package",
                "tier": "default",
                "reason": "builds the plugin and checks packed artifact plus isolated DSH profile install/remove lifecycle",
            },
            {
                "command": "python3 examples/canary/dsh-loopx-plugin-validation.py --phase runtime",
                "tier": "default",
                "reason": (
                    "runs the real DSH runtime smoke; requires local process spawn and "
                    "loopback socket access, so restricted sandboxes must run it manually"
                ),
            },
        ],
    },
)

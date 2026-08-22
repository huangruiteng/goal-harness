from __future__ import annotations

from typing import Any


PUBLIC_SAFE_OUTBOUND_CATALOG_ENTRY: dict[str, Any] = {
    "id": "public-safe-outbound",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/public_safe_outbound",
        "site_root": "capabilities/public-safe-outbound",
        "canonical": "README.md",
    },
    "title": "Public-safe outbound scrubbing for external submissions",
    "status": "active-preview",
    "real_world_anchor": (
        "any repository content about to be pushed to an external repository or PR"
    ),
    "user_value": (
        "Fail-closed scan for company-internal info, credentials, private paths, "
        "and internal links before an external submission."
    ),
    "next_real_step": (
        "scan the staged paths or git diff with `loopx capability show public-safe-outbound` "
        "entrypoint; any hit blocks the push until fixed."
    ),
    "entry_command": (
        "python -m loopx.capabilities.public_safe_outbound.scan_cli "
        "--scan-root <repo> | --diff"
    ),
    "smokes": [
        "python -m pytest loopx/capabilities/public_safe_outbound/tests -q"
    ],
    "commands": [
        {
            "command": (
                "python -m loopx.capabilities.public_safe_outbound.scan_cli "
                "--scan-root <repo> --format json"
            ),
            "purpose": "Scan all text files under a path for outbound-public-safe violations.",
            "write_boundary": "read-only",
        },
        {
            "command": (
                "python -m loopx.capabilities.public_safe_outbound.scan_cli "
                "--diff --format json"
            ),
            "purpose": "Scan a git diff from stdin for outbound-public-safe violations.",
            "write_boundary": "read-only",
        },
    ],
}

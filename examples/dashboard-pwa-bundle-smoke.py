#!/usr/bin/env python3
"""Verify both shipped dashboard entrypoints expose the shared PWA contract."""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_BUNDLE = REPO_ROOT / "apps" / "presentation" / "dashboard" / "dist"
CHAT_BUNDLE = REPO_ROOT / "loopx" / "web" / "chat"


def assert_pwa_bundle(label: str, bundle: Path, manifest_href: str) -> None:
    index = bundle / "index.html"
    manifest_path = bundle / "manifest.webmanifest"
    icon_192 = bundle / "pwa" / "icon-192.png"
    icon_512 = bundle / "pwa" / "icon-512.png"

    assert index.is_file(), f"{label}: missing {index}"
    index_text = index.read_text(encoding="utf-8")
    assert f'<link rel="manifest" href="{manifest_href}" />' in index_text, (
        f"{label}: index does not reference {manifest_href}"
    )
    assert manifest_path.is_file(), f"{label}: missing {manifest_path}"
    assert icon_192.is_file(), f"{label}: missing {icon_192}"
    assert icon_512.is_file(), f"{label}: missing {icon_512}"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone", manifest
    assert manifest["start_url"] == "./", manifest
    assert manifest["scope"] == "./", manifest
    assert [icon["src"] for icon in manifest["icons"]] == [
        "pwa/icon-192.png",
        "pwa/icon-512.png",
    ], manifest


def main() -> int:
    assert_pwa_bundle("root dashboard", ROOT_BUNDLE, "manifest.webmanifest")
    assert_pwa_bundle("chat dashboard", CHAT_BUNDLE, "/chat/manifest.webmanifest")
    print("dashboard-pwa-bundle-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

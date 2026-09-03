#!/usr/bin/env python3
"""Validate the desktop release workflow's macOS distribution contract."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "desktop-release-artifacts.yml"


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing desktop release contract: {needle}")


def assert_absent(text: str, needle: str) -> None:
    if needle in text:
        raise AssertionError(f"desktop preview release must not require {needle}")


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    for required in [
        "github.event_name == 'pull_request'",
        "github.event_name != 'pull_request'",
        "- name: Validate desktop release workflow\n        if: github.event_name == 'pull_request'",
        'npm run build -- --bundles ${{ matrix.bundles }} --no-sign',
        'npm run build -- --bundles ${{ matrix.bundles }}',
        'RELEASE_TAG: ${{ steps.identity.outputs.release-tag }}',
        'release_version="${RELEASE_TAG#v}"',
        r'\"signingIdentity\":\"-\"',
        'codesign --verify --deep --strict --verbose=2',
        "grep -q '^Signature=adhoc$'",
        'hdiutil verify',
        'bundle/macos/LoopX.app',
        'dist/desktop/LoopX.app.zip',
        'Generate desktop checksums',
        'sha256sum',
        'DESKTOP-SHA256SUMS',
    ]:
        assert_contains(text, required)

    signed_step = text.split("- name: Build integrity-signed macOS release bundles", 1)[1].split(
        "- name:", 1
    )[0]
    if "--no-sign" in signed_step:
        raise AssertionError("integrity-signed macOS release build must not use --no-sign")

    for forbidden in [
        "APPLE_CERTIFICATE",
        "APPLE_ID",
        "KEYCHAIN_PASSWORD",
        "notarytool",
        "stapler",
        "spctl",
    ]:
        assert_absent(text, forbidden)

    print("desktop-release-workflow-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

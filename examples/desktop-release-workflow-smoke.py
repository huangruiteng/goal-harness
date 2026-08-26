#!/usr/bin/env python3
"""Validate the desktop release workflow's macOS distribution contract."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "desktop-release-artifacts.yml"


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing desktop release contract: {needle}")


def main() -> int:
    text = WORKFLOW.read_text(encoding="utf-8")

    for required in [
        'APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}',
        'APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}',
        'KEYCHAIN_PASSWORD: ${{ secrets.KEYCHAIN_PASSWORD }}',
        'APPLE_ID: ${{ secrets.APPLE_ID }}',
        'APPLE_PASSWORD: ${{ secrets.APPLE_PASSWORD }}',
        'APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}',
        "github.event_name == 'pull_request'",
        "github.event_name != 'pull_request'",
        "- name: Validate desktop release workflow\n        if: github.event_name == 'pull_request'",
        'npm run build -- --bundles ${{ matrix.bundles }} --no-sign',
        'npm run build -- --bundles ${{ matrix.bundles }}',
        'RELEASE_TAG: ${{ steps.identity.outputs.release-tag }}',
        'release_version="${RELEASE_TAG#v}"',
        r'--config "{\"version\":\"${release_version}\"}"',
        'codesign --verify --deep --strict --verbose=2',
        'spctl --assess --type execute --verbose=4',
        'xcrun notarytool submit',
        'spctl --assess --type open --context context:primary-signature --verbose=4',
        'xcrun stapler validate',
        'hdiutil verify',
        'bundle/macos/LoopX.app',
        'dist/desktop/LoopX.app.zip',
        'Generate desktop checksums',
        'sha256sum',
        'DESKTOP-SHA256SUMS',
    ]:
        assert_contains(text, required)

    signed_step = text.split("- name: Build signed macOS release bundles", 1)[1].split(
        "- name:", 1
    )[0]
    if "--no-sign" in signed_step:
        raise AssertionError("signed macOS release build must not use --no-sign")

    print("desktop-release-workflow-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

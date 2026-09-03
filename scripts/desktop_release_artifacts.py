#!/usr/bin/env python3
"""Validate a complete LoopX desktop release set and its checksums."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


MANIFEST_NAME = "DESKTOP-SHA256SUMS"


class DesktopReleaseArtifactError(ValueError):
    """Raised when desktop artifacts do not satisfy the release contract."""


def expected_artifact_names(version: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            (
                "LoopX.app.zip",
                f"LoopX_{version}_aarch64.dmg",
                f"LoopX_{version}_x64-setup.exe",
                f"LoopX_{version}_x64_en-US.msi",
            )
        )
    )


def desktop_artifacts(dist_dir: Path, version: str) -> tuple[Path, ...]:
    if not dist_dir.is_dir():
        raise DesktopReleaseArtifactError(
            f"desktop distribution directory does not exist: {dist_dir}"
        )
    expected = expected_artifact_names(version)
    observed = tuple(
        sorted(
            path.name
            for path in dist_dir.iterdir()
            if path.is_file() and path.name != MANIFEST_NAME
        )
    )
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        raise DesktopReleaseArtifactError(
            "desktop release must contain the complete rebuilt artifact set; "
            f"missing={missing}, unexpected={unexpected}"
        )
    return tuple(dist_dir / name for name in expected)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_manifest(files: tuple[Path, ...]) -> str:
    return "".join(f"{sha256(path)}  {path.name}\n" for path in files)


def write_manifest(dist_dir: Path, version: str, output: Path) -> None:
    files = desktop_artifacts(dist_dir, version)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(render_manifest(files), encoding="ascii")
    temporary.replace(output)
    print(f"wrote {output} for {len(files)} rebuilt desktop artifacts")


def verify_manifest(dist_dir: Path, version: str, checksum_file: Path) -> None:
    expected = render_manifest(desktop_artifacts(dist_dir, version))
    try:
        observed = checksum_file.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise DesktopReleaseArtifactError(
            f"cannot read desktop checksum manifest {checksum_file}: {exc}"
        ) from exc
    if observed != expected:
        raise DesktopReleaseArtifactError(
            f"desktop checksum manifest does not match rebuilt artifacts: {checksum_file}"
        )
    print(
        f"verified {checksum_file} for "
        f"{len(desktop_artifacts(dist_dir, version))} rebuilt desktop artifacts"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    write = subparsers.add_parser("write-checksums")
    write.add_argument("--dist-dir", type=Path, required=True)
    write.add_argument("--version", required=True)
    write.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify-checksums")
    verify.add_argument("--dist-dir", type=Path, required=True)
    verify.add_argument("--version", required=True)
    verify.add_argument("--checksum-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "write-checksums":
            write_manifest(args.dist_dir, args.version, args.output)
        elif args.command == "verify-checksums":
            verify_manifest(args.dist_dir, args.version, args.checksum_file)
    except DesktopReleaseArtifactError as exc:
        print(f"desktop release artifact error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

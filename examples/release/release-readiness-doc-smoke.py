#!/usr/bin/env python3
"""Validate the public release-readiness doc wiring."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "product" / "release-readiness.md"
README = ROOT / "README.md"
DOCS_INDEX = ROOT / "docs" / "README.md"
PRODUCT_INDEX = ROOT / "docs" / "product" / "README.md"

FORBIDDEN_PUBLIC_STRINGS = [
    "/Users/",
    "/private/tmp/",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "raw_thread",
    "session_history",
    "verifier_output_tail",
    "ACTIVE_GOAL_STATE.md:",
]

ENGLISH_USAGE_HEADING = "## Optional Capability Activation & Use"
CHINESE_USAGE_HEADING = "### 可选能力启用与使用"
ENGLISH_NO_CHANGES = "No new optional capability activation is introduced in this release."
CHINESE_NO_CHANGES = "本版本未新增可选能力启用入口。"
ENGLISH_USAGE_FIELDS = (
    "**Activation:**",
    "**Validation:**",
    "**Disable / rollback:**",
    "**Authority boundary:**",
    "**Docs:**",
)
CHINESE_USAGE_FIELDS = (
    "**启用：**",
    "**验证：**",
    "**停用 / 回退：**",
    "**权限边界：**",
    "**文档：**",
)


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"missing expected file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def compact(text: str) -> str:
    return " ".join(text.split())


def assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label} missing {needle!r}")


def validate_boundary(path: Path) -> None:
    text = read(path)
    try:
        label = str(path.relative_to(ROOT))
    except ValueError:
        label = path.name
    for forbidden in FORBIDDEN_PUBLIC_STRINGS:
        if forbidden in text:
            raise AssertionError(f"{label} contains forbidden string {forbidden!r}")


def heading_level(line: str) -> int | None:
    match = re.match(r"^(#+)\s+", line)
    return len(match.group(1)) if match else None


def section(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError as exc:
        raise AssertionError(f"release notes missing heading {heading!r}") from exc

    level = heading_level(heading)
    assert level is not None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        candidate_level = heading_level(lines[index])
        if candidate_level is not None and candidate_level <= level:
            end = index
            break
    return "\n".join(lines[start + 1 : end])


def validate_surface_entry(
    *,
    usage_section: str,
    heading: str,
    required_fields: tuple[str, ...],
    language: str,
) -> None:
    entry = section(usage_section, heading)
    for field in required_fields:
        assert_contains(entry, field, f"{language} usage entry {heading!r}")
    if "```bash" not in entry:
        raise AssertionError(f"{language} usage entry {heading!r} has no runnable bash example")
    docs_field = re.escape(required_fields[-1])
    if not re.search(rf"{docs_field}[^\n]*https://[^)\s]+", entry):
        raise AssertionError(
            f"{language} usage entry {heading!r} has no canonical link in its docs field"
        )


def validate_release_notes(
    path: Path,
    *,
    surfaces: list[str],
    expect_no_optional_capability_changes: bool,
) -> None:
    validate_boundary(path)
    body = read(path)
    if body.count("```") % 2:
        raise AssertionError("release notes contain an unbalanced fenced code block")

    english = section(body, ENGLISH_USAGE_HEADING)
    chinese_summary = section(body, "## 中文摘要")
    chinese = section(chinese_summary, CHINESE_USAGE_HEADING)

    if expect_no_optional_capability_changes:
        if surfaces:
            raise AssertionError(
                "--expect-no-optional-capability-changes cannot be combined with --surface"
            )
        assert_contains(english, ENGLISH_NO_CHANGES, "English no-change declaration")
        assert_contains(chinese, CHINESE_NO_CHANGES, "Chinese no-change declaration")
        return

    if not surfaces:
        raise AssertionError(
            "release-note validation requires at least one --surface or "
            "--expect-no-optional-capability-changes"
        )

    if len(set(surfaces)) != len(surfaces):
        raise AssertionError("release-note validation received duplicate --surface values")

    for surface in surfaces:
        validate_surface_entry(
            usage_section=english,
            heading=f"### {surface}",
            required_fields=ENGLISH_USAGE_FIELDS,
            language="English",
        )
        validate_surface_entry(
            usage_section=chinese,
            heading=f"#### {surface}",
            required_fields=CHINESE_USAGE_FIELDS,
            language="Chinese",
        )


def validate_release_notes_gate_self_test() -> None:
    valid = f"""# Example

{ENGLISH_USAGE_HEADING}

### Example Surface

**Activation:** Enable the example.

**Validation:** Read it back.

**Disable / rollback:** Disable the example.

**Authority boundary:** No authority is granted.

**Docs:** https://example.com/docs.

```bash
loopx example --check
```

## Validation

## 中文摘要

{CHINESE_USAGE_HEADING}

#### Example Surface

**启用：**启用示例。

**验证：**读回示例。

**停用 / 回退：**停用示例。

**权限边界：**不授予额外权限。

**文档：**https://example.com/docs。

```bash
loopx example --check
```

### 验证
"""
    invalid = valid.replace("**Disable / rollback:**", "", 1)
    no_changes = f"""# Example

{ENGLISH_USAGE_HEADING}

{ENGLISH_NO_CHANGES}

## 中文摘要

{CHINESE_USAGE_HEADING}

{CHINESE_NO_CHANGES}

### 验证
"""
    with tempfile.TemporaryDirectory() as tmp:
        valid_path = Path(tmp) / "valid.md"
        invalid_path = Path(tmp) / "invalid.md"
        no_changes_path = Path(tmp) / "no-changes.md"
        valid_path.write_text(valid, encoding="utf-8")
        invalid_path.write_text(invalid, encoding="utf-8")
        no_changes_path.write_text(no_changes, encoding="utf-8")
        validate_release_notes(
            valid_path,
            surfaces=["Example Surface"],
            expect_no_optional_capability_changes=False,
        )
        validate_release_notes(
            no_changes_path,
            surfaces=[],
            expect_no_optional_capability_changes=True,
        )
        try:
            validate_release_notes(
                invalid_path,
                surfaces=["Example Surface"],
                expect_no_optional_capability_changes=False,
            )
        except AssertionError:
            pass
        else:
            raise AssertionError("release-note gate accepted a missing rollback field")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-notes",
        type=Path,
        help="Validate an exact final GitHub release body stored in this file.",
    )
    parser.add_argument(
        "--surface",
        action="append",
        default=[],
        help="New or materially changed optional capability/workflow/host surface. Repeatable.",
    )
    parser.add_argument(
        "--expect-no-optional-capability-changes",
        action="store_true",
        help="Require explicit bilingual declarations that this release adds no optional surface.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in [DOC, README, DOCS_INDEX, PRODUCT_INDEX]:
        validate_boundary(path)

    doc = compact(read(DOC))
    for required in [
        "Status: v0.x maintainer contract.",
        "## Supported Install And Update Paths",
        "loopx update --check",
        "loopx update --dry-run",
        "loopx update --execute",
        "## Named Version Contract",
        "The version source is `loopx.__version__`, mirrored by `pyproject.toml`",
        "examples/release/release-version-contract-smoke.py",
        "## Compatibility Gate",
        "examples/release/codex-cli-no-clone-release-verification-smoke.py",
        "examples/release/release-readiness-doc-smoke.py",
        "loopx canary release-qualification",
        "exact_release_commit_qualification_manifest_v0",
        "same Git commit, Git tree id, package version, and version tag",
        "## Canary Model",
        "catalog-informed readiness slice",
        "near-E2E",
        "do not add new IPs solely to describe a validation bundle",
        "examples/canary/canary-promotion-readiness-smoke.py --no-write-evidence",
        "python3 -m loopx.cli canary smoke-suite --profile public-smoke-watch --jobs 4 --timeout-seconds 60",
        "python3 examples/run-smokes.py --suite full-public --jobs 4 --timeout-seconds 60",
        "## What Is Safe To Depend On",
        "loopx doctor",
        "quota should-run",
        "/loopx-global-summary",
        "benchmark runner behavior, scoring, upload",
        "## Release Note Checklist",
        "prominent `## Community Contributors` section",
        "after the English product groups",
        "tag-to-tag Git range and merged pull-request metadata",
        "external or first-time contributors",
        "Do not list or thank `@huangruiteng`",
        "founder stewardship is implicit",
        "Omit the section when the tag range contains no eligible community contribution",
        "`### 社区贡献者` after the Chinese product groups",
        "Omit both language sections together",
        "same people, pull-request links, and concrete contribution scope",
        "Optional capability activation",
        "If no persistent switch exists",
        "final GitHub release body",
        "--release-notes <final-release-body.md>",
        "--expect-no-optional-capability-changes",
        "**Activation:**",
        "**Validation:**",
        "**Disable / rollback:**",
        "**Authority boundary:**",
        "**Docs:**",
        "**启用：**",
        "**验证：**",
        "**停用 / 回退：**",
        "**权限边界：**",
        "**文档：**",
        "### Capability Narrative Gate",
        "**User outcome**",
        "**Shipped layer**",
        "**Last-mile boundary**",
        "A built-in capability is not an optional extension",
        "Do not overclaim a complete workflow",
        "public/private scan",
        "## 中文摘要",
        "Bilingual releases must preserve these same group boundaries",
        "mirrors the English group structure and material claims",
    ]:
        assert_contains(doc, required, "release-readiness doc")

    root_readme = read(README)
    docs_index = read(DOCS_INDEX)
    product_index = read(PRODUCT_INDEX)
    assert_contains(root_readme, "docs/product/release-readiness.md", "root README")
    assert_contains(docs_index, "product/release-readiness.md", "docs index")
    assert_contains(product_index, "release-readiness.md", "product index")

    validate_release_notes_gate_self_test()
    if args.release_notes is not None:
        validate_release_notes(
            args.release_notes,
            surfaces=args.surface,
            expect_no_optional_capability_changes=(
                args.expect_no_optional_capability_changes
            ),
        )
    elif args.surface or args.expect_no_optional_capability_changes:
        raise AssertionError(
            "--surface and --expect-no-optional-capability-changes require --release-notes"
        )

    print("release-readiness-doc-smoke ok")


if __name__ == "__main__":
    main()

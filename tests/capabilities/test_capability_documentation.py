from __future__ import annotations

from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pytest

from docs.capability_docs import (
    HTML_LINK,
    MARKDOWN_LINK,
    documentation_maps,
    render_markdown,
)
from loopx.capabilities.catalog import BUILTIN_CAPABILITIES, build_capability_registry
from loopx.capabilities.documentation import normalize_documentation_contract
from loopx.extensions.manifest import load_extension_manifest


ROOT = Path(__file__).resolve().parents[2]


def test_documentation_contract_rejects_ambiguous_ownership() -> None:
    with pytest.raises(ValueError, match="normalized repository-relative path"):
        normalize_documentation_contract(
            {
                "source_root": "../outside",
                "site_root": "capabilities/example",
                "canonical": "README.md",
            },
            context="capability `example`",
        )

    with pytest.raises(ValueError, match="duplicate documentation alias"):
        normalize_documentation_contract(
            {
                "source_root": "loopx/capabilities/example",
                "site_root": "capabilities/example",
                "canonical": "README.md",
                "aliases": [
                    {"source": "README.md", "site": "reference/example.md"},
                    {"source": "guide.md", "site": "reference/example.md"},
                ],
            },
            context="capability `example`",
        )


def test_every_builtin_capability_owns_its_documentation_and_validation() -> None:
    records = build_capability_registry().records()

    assert len(records) == len(BUILTIN_CAPABILITIES)
    for record in records:
        documentation = record["documentation"]
        source_root = ROOT / documentation["source_root"]
        canonical = source_root / documentation["canonical"]

        assert source_root.parent == ROOT / "loopx/capabilities"
        assert (source_root / "catalog_entry.py").is_file()
        assert canonical.is_file()
        assert record["canonical_doc"] == canonical.relative_to(ROOT).as_posix()
        assert record["docs"][0] == record["canonical_doc"]
        assert record["documentation_route"].startswith("capabilities/")
        assert record["smokes"]
        assert all((ROOT / path).is_file() for path in record["docs"])
        assert all(
            (ROOT / protocol["doc"]).is_file()
            for protocol in record.get("implemented_protocols", [])
            if protocol.get("doc")
        )


def test_capability_docs_have_no_second_authored_tree() -> None:
    legacy_root = ROOT / "docs/capabilities"

    assert not legacy_root.exists() or not list(legacy_root.rglob("*.md"))


def test_bundled_lark_capabilities_use_extension_owned_documentation() -> None:
    manifest_path = ROOT / "loopx/extensions/lark/extension.toml"
    manifest = load_extension_manifest(manifest_path)
    documentation = manifest["documentation"]

    assert documentation is not None
    assert documentation["source_root"] == "loopx/extensions/lark"
    assert (ROOT / documentation["source_root"] / documentation["canonical"]).is_file()
    for capability in manifest["capabilities"]:
        assert capability["documentation"] == documentation

    records = build_capability_registry([manifest_path]).records()
    lark_records = [record for record in records if record["provider_id"] == "loopx-lark"]
    assert lark_records
    assert all(
        record["canonical_doc"] == "loopx/extensions/lark/README.md"
        for record in lark_records
    )


def test_docs_projection_preserves_routes_and_rewrites_package_links() -> None:
    site_to_source, source_to_site = documentation_maps()

    assert site_to_source[PurePosixPath("capabilities/issue-fix/README.md")] == (
        ROOT / "loopx/capabilities/issue_fix/README.md"
    )
    assert site_to_source[
        PurePosixPath("reference/protocols/pr-review-command-v0.md")
    ] == (ROOT / "loopx/capabilities/pr_review_queue/README.md")
    assert site_to_source[PurePosixPath("capabilities/lark-event-inbox.md")] == (
        ROOT / "loopx/extensions/lark/docs/lark-event-inbox.md"
    )
    assert site_to_source[PurePosixPath("integrations/lark-provider/README.md")] == (
        ROOT / "loopx/extensions/lark/README.md"
    )

    source = ROOT / "loopx/capabilities/README.md"
    rendered = render_markdown(
        source.read_text(encoding="utf-8"),
        source=source,
        site=PurePosixPath("capabilities/README.md"),
        source_to_site=source_to_site,
    )
    assert "[Kernel](../architecture.md#runtime-responsibility-model)" in rendered
    assert "[issue-fix](issue-fix/README.md)" in rendered


def test_package_owned_markdown_links_resolve_in_repository() -> None:
    site_to_source, _ = documentation_maps()

    for source in set(site_to_source.values()):
        markdown = source.read_text(encoding="utf-8")
        for pattern in (MARKDOWN_LINK, HTML_LINK):
            for match in pattern.finditer(markdown):
                target = match.group("dest").strip("<>")
                split = urlsplit(target)
                if (
                    split.scheme
                    or split.netloc
                    or not split.path
                    or split.path.startswith("/")
                ):
                    continue
                assert (source.parent / split.path).resolve().exists(), (
                    f"{source.relative_to(ROOT)} links missing `{target}`"
                )

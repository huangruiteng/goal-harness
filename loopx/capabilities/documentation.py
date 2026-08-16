from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any


def _relative_markdown_path(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty repository-relative path")
    normalized = value.strip()
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or "\\" in normalized
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"{context} must be a normalized repository-relative path")
    return path.as_posix()


def normalize_documentation_contract(
    value: object,
    *,
    context: str,
) -> dict[str, Any]:
    """Validate one package-owned documentation projection contract."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} documentation must be a mapping")
    source_root = _relative_markdown_path(
        value.get("source_root"),
        context=f"{context} documentation source_root",
    ).rstrip("/")
    site_root = _relative_markdown_path(
        value.get("site_root"),
        context=f"{context} documentation site_root",
    ).rstrip("/")
    canonical = _relative_markdown_path(
        value.get("canonical"),
        context=f"{context} documentation canonical",
    )
    if not canonical.endswith(".md"):
        raise ValueError(f"{context} documentation canonical must be Markdown")

    aliases_value = value.get("aliases", [])
    if not isinstance(aliases_value, list):
        raise ValueError(f"{context} documentation aliases must be a list")
    aliases: list[dict[str, str]] = []
    seen_sites: set[str] = set()
    for index, alias in enumerate(aliases_value):
        alias_context = f"{context} documentation alias[{index}]"
        if not isinstance(alias, Mapping):
            raise ValueError(f"{alias_context} must be a mapping")
        source = _relative_markdown_path(
            alias.get("source"),
            context=f"{alias_context} source",
        )
        site = _relative_markdown_path(
            alias.get("site"),
            context=f"{alias_context} site",
        )
        if not source.endswith(".md") or not site.endswith(".md"):
            raise ValueError(f"{alias_context} must map Markdown paths")
        if site in seen_sites:
            raise ValueError(f"{context} has duplicate documentation alias `{site}`")
        seen_sites.add(site)
        aliases.append({"source": source, "site": site})

    return {
        "source_root": source_root,
        "site_root": site_root,
        "canonical": canonical,
        "aliases": aliases,
    }

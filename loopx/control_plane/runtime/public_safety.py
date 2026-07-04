from __future__ import annotations

from typing import Any, Callable, Optional


NormalizeText = Callable[..., str]
CompactText = Callable[..., Optional[str]]


def public_safe_compact_text(
    value: Any,
    *,
    limit: int = 220,
    normalize_text: NormalizeText,
    local_path_surface_pattern: Any,
    secret_like_surface_pattern: Any,
) -> str | None:
    text = normalize_text(str(value or ""), limit=limit)
    if not text:
        return None
    if local_path_surface_pattern.search(text) or secret_like_surface_pattern.search(text):
        return None
    return text


def public_safe_compact_list(
    value: Any,
    *,
    limit: int,
    compact_text: CompactText,
    item_limit: int = 160,
) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    result: list[str] = []
    for item in values:
        text = compact_text(item, limit=item_limit)
        if not text:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result

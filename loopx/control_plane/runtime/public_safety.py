from __future__ import annotations

import re
from typing import Any, Callable, Optional


NormalizeText = Callable[..., str]
CompactText = Callable[..., Optional[str]]
DEFAULT_PUBLIC_SAFE_LIST_LIMIT = 4
LOCAL_PATH_SURFACE_PATTERN = re.compile(
    r"(?<!<)/(?:Users|Volumes|var/folders|tmp|private/tmp)/[^\s`'\"<>]+"
)
SECRET_LIKE_SURFACE_PATTERN = re.compile(
    r"(?i)(?:\bbearer\s+[a-z0-9._~+/=-]{16,}|"
    r"(?<![a-z0-9_])(?:ak|sk)[-_=:][a-z0-9_=-]{10,}|"
    r"\btoken\s*[=:]\s*[^\s`'\"<>]{12,})"
)


def compact_text(text: str, *, limit: int) -> str:
    compact = " ".join(str(text or "").strip().split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def public_safe_compact_text(
    value: Any,
    *,
    limit: int = 220,
    normalize_text: NormalizeText | None = None,
    local_path_surface_pattern: Any = LOCAL_PATH_SURFACE_PATTERN,
    secret_like_surface_pattern: Any = SECRET_LIKE_SURFACE_PATTERN,
) -> str | None:
    normalize = normalize_text or compact_text
    text = normalize(str(value or ""), limit=limit)
    if not text:
        return None
    if local_path_surface_pattern.search(text) or secret_like_surface_pattern.search(text):
        return None
    return text


def public_safe_compact_list(
    value: Any,
    *,
    limit: int = DEFAULT_PUBLIC_SAFE_LIST_LIMIT,
    compact_text: CompactText | None = None,
    item_limit: int = 160,
) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    result: list[str] = []
    compact_item = compact_text or public_safe_compact_text
    for item in values:
        text = compact_item(item, limit=item_limit)
        if not text:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return result

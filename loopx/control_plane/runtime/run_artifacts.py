from __future__ import annotations

import re
from pathlib import Path


def run_file_stem(generated_at: str) -> str:
    return re.sub(r"[^0-9A-Za-z-]+", "-", generated_at).strip("-")


def unique_run_artifact_paths(runs_dir: Path, stem: str, suffix: str) -> tuple[Path, Path]:
    candidate = runs_dir / f"{stem}-{suffix}.json"
    markdown_candidate = runs_dir / f"{stem}-{suffix}.md"
    if not candidate.exists() and not markdown_candidate.exists():
        return candidate, markdown_candidate
    index = 2
    while True:
        candidate = runs_dir / f"{stem}-{suffix}-{index}.json"
        markdown_candidate = runs_dir / f"{stem}-{suffix}-{index}.md"
        if not candidate.exists() and not markdown_candidate.exists():
            return candidate, markdown_candidate
        index += 1

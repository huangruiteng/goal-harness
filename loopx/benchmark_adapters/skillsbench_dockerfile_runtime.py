from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

VENV_PIP_INVOCATION_MARKER = "# LOOPX_SKILLSBENCH_VENV_PIP_INVOCATION"
_BARE_PIP_INSTALL_RE = re.compile(
    r"(?P<prefix>^\s*(?:RUN\s+)?|(?:&&|\|\||;|\|)\s*)pip3?\s+install\b",
    re.IGNORECASE,
)


def dockerfile_heredoc_delimiter(line: str) -> str | None:
    match = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
    return match.group(1) if match else None


def _rewrite_bare_pip_installs(text: str) -> tuple[str, int]:
    lines: list[str] = []
    replaced = 0
    heredoc_delimiter: str | None = None
    for line in text.splitlines():
        if heredoc_delimiter is not None:
            lines.append(line)
            if line.strip() == heredoc_delimiter:
                heredoc_delimiter = None
            continue
        heredoc_delimiter = dockerfile_heredoc_delimiter(line)
        if line.lstrip().startswith("#"):
            lines.append(line)
            continue
        rewritten, count = _BARE_PIP_INSTALL_RE.subn(
            r"\g<prefix>python3 -m pip install", line
        )
        lines.append(rewritten)
        replaced += count
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + suffix, replaced


def _stage_activates_venv(text: str) -> bool:
    has_venv = bool(re.search(r"\bpython\S*\s+-m\s+venv\s+", text, re.IGNORECASE))
    has_venv_path = bool(
        re.search(
            r"^\s*ENV\s+PATH=.*(?:VIRTUAL_ENV|venv).*/bin",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
    )
    return has_venv and has_venv_path


def _rewrite_venv_stage_pip_installs(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    stage_starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*FROM\s+", line, re.IGNORECASE)
    ]
    if not stage_starts:
        return text, 0

    rewritten_lines = lines[: stage_starts[0]]
    replaced = 0
    for position, start in enumerate(stage_starts):
        end = stage_starts[position + 1] if position + 1 < len(stage_starts) else len(lines)
        stage_text = "\n".join(lines[start:end])
        if _stage_activates_venv(stage_text):
            stage_text, stage_replaced = _rewrite_bare_pip_installs(stage_text)
            replaced += stage_replaced
        rewritten_lines.extend(stage_text.splitlines())
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(rewritten_lines) + suffix, replaced


def needs_venv_pip_invocation_patch(dockerfile: Path) -> bool:
    if not dockerfile.exists():
        return False
    text = dockerfile.read_text(encoding="utf-8", errors="replace")
    return _rewrite_venv_stage_pip_installs(text)[1] > 0


def patch_venv_pip_invocations(dockerfile: Path) -> bool:
    """Keep pip installs bound to an explicitly activated Dockerfile venv."""

    if not needs_venv_pip_invocation_patch(dockerfile):
        return False
    original = dockerfile.read_text(encoding="utf-8")
    patched, _ = _rewrite_venv_stage_pip_installs(original)
    lines = patched.splitlines()
    from_index = next(
        (index for index, line in enumerate(lines) if line.lstrip().upper().startswith("FROM ")),
        -1,
    )
    lines.insert(from_index + 1, VENV_PIP_INVOCATION_MARKER)
    patched = "\n".join(lines).rstrip() + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=dockerfile.name, dir=dockerfile.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(patched)
        os.replace(temp_name, dockerfile)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return True

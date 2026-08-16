"""Public-safe SkillsBench verifier bootstrap attribution helpers."""

from __future__ import annotations

import os
import re
import shlex
import stat
from pathlib import Path
from typing import Any

from loopx.benchmark_adapters import skillsbench_proxy_runtime as proxy_runtime


VERIFIER_UV_BOOTSTRAP_MIRROR_BEGIN = (
    "# BEGIN LOOPX_SKILLSBENCH_VERIFIER_UV_BOOTSTRAP_MIRROR"
)
VERIFIER_UV_BOOTSTRAP_MIRROR_END = (
    "# END LOOPX_SKILLSBENCH_VERIFIER_UV_BOOTSTRAP_MIRROR"
)
DEFAULT_VERIFIER_UV_RELEASE_MIRROR_BASE = (
    "https://releases.astral.sh/github/uv/releases/download"
)
DEFAULT_VERIFIER_UV_RELEASE_MIRROR_HOST = "releases.astral.sh"
DEFAULT_DOCKER_PIP_INDEX_URL = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _strip_marker_block(text: str, begin: str, end: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == begin:
            skipping = True
            continue
        if line.strip() == end:
            skipping = False
            continue
        if not skipping:
            output.append(line)
    return "\n".join(output).rstrip() + "\n"


def _write_text_atomic(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    temporary = path.with_name(f".{path.name}.loopx-bootstrap.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def skillsbench_verifier_bootstrap_risk(task_path: Path) -> dict[str, Any]:
    """Return public-safe verifier dependency bootstrap risk flags."""

    verifier = proxy_runtime.skillsbench_verifier_script(task_path)
    result: dict[str, Any] = {
        "verifier_present": verifier.exists(),
        "verifier_bootstrap_risk_detected": False,
        "verifier_uv_bootstrap_risk_detected": False,
        "verifier_external_download_risk_detected": False,
        "verifier_package_install_risk_detected": False,
        "verifier_bootstrap_risk_categories": [],
    }
    if not verifier.exists():
        return result
    try:
        text = verifier.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result

    uv_versions = verifier_uv_bootstrap_versions(text)
    if uv_versions:
        result["verifier_uv_bootstrap_version"] = uv_versions[0]
    categories: list[str] = []
    if re.search(
        r"astral\.sh/uv|(?:^|[;&|(\s])uv(?:x|\s+add|\s+sync|\s+pip|\s+tool)",
        text,
    ):
        result["verifier_uv_bootstrap_risk_detected"] = True
        categories.append("uv_bootstrap")
    if re.search(r"(?:curl|wget)\s+[^;\n]*(?:https?://|astral\.sh)", text):
        result["verifier_external_download_risk_detected"] = True
        categories.append("external_download")
    if re.search(
        r"(?:python\s+-m\s+pip|pip3?|uv\s+pip|uv\s+add|"
        r"poetry\s+install|npm\s+install|pnpm\s+install|"
        r"yarn\s+install|apt-get\s+(?:update|install))",
        text,
    ):
        result["verifier_package_install_risk_detected"] = True
        categories.append("package_install")
    result["verifier_bootstrap_risk_categories"] = sorted(set(categories))
    result["verifier_bootstrap_risk_detected"] = bool(categories)
    return result


def verifier_uv_bootstrap_versions(text: str) -> list[str]:
    versions: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(
        r"https?://astral\.sh/uv/(?P<version>[0-9A-Za-z][0-9A-Za-z._+-]*)/install\.sh",
        text,
    ):
        version = match.group("version")
        if version and version not in seen:
            versions.append(version)
            seen.add(version)
    return versions


def patch_verifier_uv_bootstrap_mirror(verifier: Path) -> dict[str, Any]:
    """Route staged verifier uv bootstrap through package and release mirrors."""

    metadata: dict[str, Any] = {
        "verifier_uv_bootstrap_risk_detected": False,
        "verifier_uv_bootstrap_mirror_patch_required": False,
        "verifier_uv_bootstrap_mirror_patch_applied": False,
        "verifier_uv_bootstrap_pip_fallback_patch_applied": False,
        "verifier_uv_env_source_guard_patch_applied": False,
    }
    if not verifier.exists():
        return metadata
    try:
        original = verifier.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return metadata
    text = _strip_marker_block(
        original,
        VERIFIER_UV_BOOTSTRAP_MIRROR_BEGIN,
        VERIFIER_UV_BOOTSTRAP_MIRROR_END,
    )
    versions = verifier_uv_bootstrap_versions(text)
    if not versions:
        return metadata

    version = versions[0]
    block = (
        f"{VERIFIER_UV_BOOTSTRAP_MIRROR_BEGIN}\n"
        "# Prefer the PyPI uv wheel for verifier bootstrap; the official uv\n"
        "# installer release tarball remains as a bounded fallback.\n"
        f"loopx_uv_release_mirror={shlex.quote(DEFAULT_VERIFIER_UV_RELEASE_MIRROR_BASE)}\n"
        f"loopx_uv_version={shlex.quote(version)}\n"
        "if ! command -v uvx >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then\n"
        "  loopx_pip_break_system_packages=''\n"
        "  if python3 -m pip install --help 2>/dev/null | grep -q -- '--break-system-packages'; then\n"
        "    loopx_pip_break_system_packages='--break-system-packages'\n"
        "  fi\n"
        "  python3 -m pip install ${loopx_pip_break_system_packages} \\\n"
        "    --timeout 120 --retries 5 \\\n"
        f"    --index-url {shlex.quote(DEFAULT_DOCKER_PIP_INDEX_URL)} \\\n"
        "    \"uv==${loopx_uv_version}\" || true\n"
        "  unset loopx_pip_break_system_packages\n"
        "fi\n"
        "if [ -z \"${INSTALLER_DOWNLOAD_URL:-}\" ]; then\n"
        "  export INSTALLER_DOWNLOAD_URL=\"${loopx_uv_release_mirror}/${loopx_uv_version}\"\n"
        "fi\n"
        "loopx_uv_installer_timeout_sec=${LOOPX_SKILLSBENCH_UV_INSTALL_TIMEOUT_SEC:-180}\n"
        f"{VERIFIER_UV_BOOTSTRAP_MIRROR_END}"
    )
    patched_lines: list[str] = []
    inserted = False
    for line in text.splitlines():
        if not inserted and "astral.sh/uv/" in line and "install.sh" in line:
            patched_lines.extend(block.splitlines())
            inserted = True
            if "curl" in line and "|" in line:
                fallback_line = shlex.quote(line)
                patched_lines.extend(
                    [
                        "if ! command -v uvx >/dev/null 2>&1; then",
                        "  if command -v timeout >/dev/null 2>&1; then",
                        f"    timeout \"${{loopx_uv_installer_timeout_sec}}\" sh -c {fallback_line}",
                        "  else",
                        f"    sh -c {fallback_line}",
                        "  fi",
                        "fi",
                    ]
                )
                continue
        patched_lines.append(line)
    if not inserted:
        patched_lines.extend(block.splitlines())
    patched = "\n".join(patched_lines).rstrip() + "\n"
    patched, source_guard_applied = _patch_verifier_uv_env_source_guard(patched)
    if patched != original:
        _write_text_atomic(verifier, patched)
    metadata.update(
        {
            "verifier_uv_bootstrap_risk_detected": True,
            "verifier_uv_bootstrap_mirror_patch_required": True,
            "verifier_uv_bootstrap_mirror_patch_applied": True,
            "verifier_uv_bootstrap_pip_fallback_patch_applied": True,
            "verifier_uv_env_source_guard_patch_applied": source_guard_applied,
            "verifier_uv_bootstrap_version": version,
            "verifier_uv_bootstrap_mirror_host": DEFAULT_VERIFIER_UV_RELEASE_MIRROR_HOST,
        }
    )
    return metadata


def _patch_verifier_uv_env_source_guard(text: str) -> tuple[str, bool]:
    source_lines = {
        'source "$HOME/.local/bin/env"',
        "source $HOME/.local/bin/env",
        '. "$HOME/.local/bin/env"',
        ". $HOME/.local/bin/env",
    }
    replacement = [
        'if [ -f "$HOME/.local/bin/env" ]; then',
        '  . "$HOME/.local/bin/env"',
        "fi",
    ]
    patched_lines: list[str] = []
    applied = False
    for line in text.splitlines():
        if line.strip() in source_lines:
            indent = line[: len(line) - len(line.lstrip())]
            patched_lines.extend(f"{indent}{part}" for part in replacement)
            applied = True
        else:
            patched_lines.append(line)
    if not applied:
        return text, False
    return "\n".join(patched_lines).rstrip() + "\n", True

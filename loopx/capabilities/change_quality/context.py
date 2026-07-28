from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .oracles import build_change_quality_validation_plan
from .scope import resolve_git_root


CHANGE_QUALITY_REPOSITORY_CONTEXT_SCHEMA_VERSION = (
    "change_quality_repository_context_v0"
)

_DIRECTORY_INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md")
_ROOT_INSTRUCTION_FILES = (
    "CONTRIBUTING.md",
    ".github/copilot-instructions.md",
)
_OWNERSHIP_FILES = (
    "CODEOWNERS",
    ".github/CODEOWNERS",
    ".gitlab/CODEOWNERS",
)
_MANIFEST_SIGNALS: dict[str, tuple[tuple[str, ...], str]] = {
    "pyproject.toml": (("python",), "python-project"),
    "setup.py": (("python",), "python-setuptools"),
    "Cargo.toml": (("rust",), "cargo"),
    ".cargo/config.toml": (("rust",), "cargo"),
    "package.json": (("javascript", "typescript"), "node"),
    "tsconfig.json": (("typescript",), "typescript"),
    "go.mod": (("go",), "go-modules"),
    "pom.xml": (("java",), "maven"),
    "build.gradle": (("java", "kotlin"), "gradle"),
    "build.gradle.kts": (("java", "kotlin"), "gradle"),
    "Gemfile": (("ruby",), "bundler"),
    "Makefile": ((), "make"),
    "Justfile": ((), "just"),
    "WORKSPACE": ((), "bazel"),
    "MODULE.bazel": ((), "bazel"),
}
_SUFFIX_LANGUAGE_HINTS = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".m": "objective-c",
    ".mm": "objective-cpp",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
}


def _normalized_changed_paths(changed_files: list[str]) -> list[PurePosixPath]:
    paths: list[PurePosixPath] = []
    for value in changed_files:
        path = PurePosixPath(str(value).replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            continue
        paths.append(path)
    return paths


def _relevant_directories(changed_paths: list[PurePosixPath]) -> list[PurePosixPath]:
    directories = {PurePosixPath(".")}
    for path in changed_paths:
        parent = path.parent
        while parent != PurePosixPath("."):
            directories.add(parent)
            parent = parent.parent
    return sorted(directories, key=lambda item: (len(item.parts), item.as_posix()))


def _existing_repo_ref(repo_root: Path, path: PurePosixPath) -> str | None:
    candidate = repo_root / path.as_posix()
    if candidate.is_file():
        return path.as_posix()
    return None


def build_change_quality_repository_context(
    *,
    repo_path: Path,
    changed_files: list[str],
) -> dict[str, Any]:
    """Project safe, path-only repository context for provider-neutral reviewers."""
    repo_root = resolve_git_root(repo_path)
    changed_paths = _normalized_changed_paths(changed_files)
    directories = _relevant_directories(changed_paths)

    instruction_refs: set[str] = set()
    for directory in directories:
        for filename in _DIRECTORY_INSTRUCTION_FILES:
            path = directory / filename
            if ref := _existing_repo_ref(repo_root, path):
                instruction_refs.add(ref)
    for value in _ROOT_INSTRUCTION_FILES:
        if ref := _existing_repo_ref(repo_root, PurePosixPath(value)):
            instruction_refs.add(ref)

    ownership_refs = sorted(
        ref
        for value in _OWNERSHIP_FILES
        if (ref := _existing_repo_ref(repo_root, PurePosixPath(value)))
    )

    manifest_refs: set[str] = set()
    language_hints = {
        language
        for path in changed_paths
        if (language := _SUFFIX_LANGUAGE_HINTS.get(path.suffix.lower()))
    }
    build_system_hints: set[str] = set()
    for directory in directories:
        for filename, (languages, build_system) in _MANIFEST_SIGNALS.items():
            path = directory / filename
            if ref := _existing_repo_ref(repo_root, path):
                manifest_refs.add(ref)
                language_hints.update(languages)
                build_system_hints.add(build_system)

    changed_surface_roots = sorted(
        {
            path.parts[0]
            for path in changed_paths
            if path.parts and path.parts[0] not in {"", "."}
        }
    )
    sorted_instruction_refs = sorted(instruction_refs)
    sorted_manifest_refs = sorted(manifest_refs)
    return {
        "schema_version": CHANGE_QUALITY_REPOSITORY_CONTEXT_SCHEMA_VERSION,
        "instruction_refs": sorted_instruction_refs,
        "ownership_refs": ownership_refs,
        "build_manifest_refs": sorted_manifest_refs,
        "language_hints": sorted(language_hints),
        "build_system_hints": sorted(build_system_hints),
        "changed_surface_roots": changed_surface_roots,
        "validation_plan": build_change_quality_validation_plan(
            repo_root=repo_root,
            instruction_refs=sorted_instruction_refs,
            manifest_refs=sorted_manifest_refs,
        ),
        "content_included": False,
    }

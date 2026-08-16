from __future__ import annotations

from typing import Any

BENCHMARK_TOOLKIT_CATALOG_ENTRY: dict[str, Any] = {
    "id": "benchmark-toolkit",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/benchmark_toolkit",
        "site_root": "capabilities/benchmark-toolkit",
        "canonical": "README.md",
    },
    "title": "Benchmark experiment toolkit",
    "status": "active-preview",
    "real_world_anchor": (
        "provider-neutral permission, artifact, and integrity boundaries for "
        "benchmark experiments"
    ),
    "user_value": (
        "Apply fail-closed evidence boundaries without replacing benchmark-native "
        "runners, verifiers, or scoring semantics."
    ),
    "entry_command": "loopx benchmark --help",
    "commands": [
        {
            "command": (
                "loopx benchmark integrity-qualification "
                "--trajectory-json <private.json> "
                "--runtime-attestation-json <attestation.json> "
                "--require-qualified --format json"
            ),
            "purpose": (
                "Reduce private ATIF tool evidence and runner-owned isolation "
                "facts to a compact integrity qualification receipt."
            ),
            "write_boundary": (
                "read-only private local inputs; emits hashes, counts, and "
                "reason codes only"
            ),
        },
        {
            "command": "loopx benchmark classify-artifacts <paths...> --format json",
            "purpose": "Classify benchmark artifacts before reading or publishing them.",
            "write_boundary": "path classification only; no file reads or writes",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "benchmark_integrity_qualification_v0",
            "module": "loopx.capabilities.benchmark_toolkit.integrity",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_runtime_integrity_attestation_v0",
            "module": "loopx.capabilities.benchmark_toolkit.integrity",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "run_permission_policy_v0",
            "module": "loopx.capabilities.benchmark_toolkit.run_permissions",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
    ],
    "smokes": ["python -m pytest tests/capabilities/test_benchmark_toolkit.py -q"],
    "docs": ["loopx/capabilities/benchmark_toolkit/README.md"],
    "boundaries": [
        "The toolkit never grants runner, Docker, model, upload, submission, or publication authority; each effect remains separately gated.",
        "Raw trajectories are private local inputs to integrity qualification and are never copied into receipts, ledgers, docs, or PR artifacts.",
        "A clean trajectory scan is not isolation proof: runner-owned permission and verifier-order attestations are mandatory and fail closed when absent.",
        "Integrity qualification establishes countability eligibility only; an independent official result and matched experiment contract are still required.",
        "Benchmark-family runners remain outside the active capability; the toolkit owns only provider-neutral permission, artifact, and integrity policy.",
    ],
    "next_real_step": (
        "Qualify one private local run and block the paired claim when either "
        "trajectory evidence or runner isolation attestation is incomplete."
    ),
}

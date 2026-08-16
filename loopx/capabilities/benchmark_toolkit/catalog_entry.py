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
        "local no-upload agent benchmark experiments with independent scoring"
    ),
    "user_value": (
        "Prepare, qualify, compare, and record benchmark runs through one "
        "fail-closed evidence lifecycle without publishing raw tasks, "
        "trajectories, verifier output, credentials, or local paths."
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
        {
            "command": (
                "loopx benchmark run <family> --goal-id <goal-id> --format json"
            ),
            "purpose": (
                "Build a compact benchmark_run_v0 or ingest supported official "
                "result metadata through an adapter."
            ),
            "write_boundary": (
                "dry-run by default; explicit append paths consume compact "
                "results and never publish raw evidence"
            ),
        },
        {
            "command": (
                "loopx benchmark run-ledger-check --goal-id <goal-id> --format json"
            ),
            "purpose": "Reconcile compact run history with the public benchmark ledger.",
            "write_boundary": "read-only compact history and ledger",
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
            "module": "loopx.benchmark_core.run_permissions",
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
        "Benchmark-family wiring remains in benchmark_adapters; the toolkit owns provider-neutral experiment and evidence policy.",
    ],
    "next_real_step": (
        "Qualify one private local run, ingest its independent compact result, "
        "and block the paired claim when either trajectory evidence or runner "
        "isolation attestation is incomplete."
    ),
}

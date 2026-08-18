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
        "provider-neutral permission, integrity, and post-run analysis boundaries "
        "for benchmark experiments"
    ),
    "user_value": (
        "Keep solving agents answer-denied while giving post-run analysts enough "
        "evidence and structure to explain benchmark outcomes."
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
            "command": "loopx capability show benchmark-toolkit --format json",
            "purpose": (
                "Read the post-run analyst hint and benchmark_case_insight_v0 "
                "artifact template."
            ),
            "write_boundary": (
                "read-only catalog; private analysis evidence remains outside "
                "the solving agent and public repository"
            ),
        },
    ],
    "post_run_case_analysis": {
        "benchmark_start_hint": (
            "When starting a benchmark, add one continuous_monitor todo that runs "
            "the post-run analyst brief on every material scored-case transition."
        ),
        "monitor_todo_template": {
            "task_class": "continuous_monitor",
            "action_kind": "benchmark_case_insight_monitor",
            "trigger": "material_scored_case_transition",
            "text": (
                "On each material scored-case transition, read the complete private "
                "evaluation evidence, write one benchmark_case_insight_v0, and report "
                "only new reusable insight."
            ),
        },
        "hint": (
            "After the solver has stopped and scoring is complete, read the task, "
            "real trajectory, final patch or workspace, hidden tests, grader or "
            "verifier, and full failure and score details; explain the decisive "
            "evidence, why the outcome happened, whether it was expected, and what "
            "LoopX should test or change next."
        ),
        "role_boundary": {
            "solver": (
                "must not access hidden tests, grader or verifier sources, expected "
                "answers, or official feedback during the solving phase"
            ),
            "post_run_analyst": (
                "may read the full private case evidence only after the solver is "
                "terminal and scoring is complete"
            ),
        },
        "artifact_template": {
            "schema_version": "benchmark_case_insight_v0",
            "case": {
                "benchmark_id": "<public-id>",
                "case_id": "<public-id>",
                "arm": "<baseline-or-treatment>",
            },
            "outcome": {
                "status": "<completed-or-runner-invalid>",
                "score": "<official-score-or-null>",
                "countable": "<true-or-false>",
            },
            "evidence_reviewed": [
                "task",
                "real_trajectory",
                "final_patch_or_workspace",
                "hidden_tests",
                "grader_or_verifier",
                "failure_and_score_details",
            ],
            "insight": {
                "approach_summary": "<what-the-solver-tried>",
                "decisive_evidence": ["<specific-observation>"],
                "why_this_outcome": "<causal-explanation>",
                "expectedness": "<expected-surprising-mixed-or-unknown>",
                "baseline_treatment_difference": "<difference-or-not-yet-compared>",
                "loopx_implication": "<reusable-product-or-experiment-insight>",
                "next_probe": "<smallest-discriminating-next-step>",
            },
            "confidence": "<high-medium-or-low>",
            "reuse_boundary": (
                "<diagnostic-only-heldout-generalization-or-declared-feedback>"
            ),
        },
    },
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
            "schema_version": "benchmark_exact_container_binding_v0",
            "module": "loopx.capabilities.benchmark_toolkit.container_binding",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "run_permission_policy_v0",
            "module": "loopx.capabilities.benchmark_toolkit.run_permissions",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_case_insight_v0",
            "module": "loopx.capabilities.benchmark_toolkit.catalog_entry",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
    ],
    "smokes": ["python -m pytest tests/capabilities/test_benchmark_toolkit.py -q"],
    "docs": ["loopx/capabilities/benchmark_toolkit/README.md"],
    "boundaries": [
        "The toolkit never grants runner, Docker, model, upload, submission, or publication authority; each effect remains separately gated.",
        "Raw trajectories are private local inputs to integrity qualification and are never copied into receipts, ledgers, docs, or PR artifacts.",
        "A clean trajectory scan is not isolation proof: runner-owned permission and verifier-order attestations are mandatory and fail closed when absent.",
        "Concurrent Docker runs must bind runtime evidence to one exact job-owned container; image-only discovery is not sufficient.",
        "Integrity qualification establishes countability eligibility only; an independent official result and matched experiment contract are still required.",
        "Post-run analyst access never widens the solving agent's evidence boundary or grants feedback reuse in another scored run.",
        "Benchmark-family runners remain outside the active capability; the toolkit owns only provider-neutral permission, artifact, integrity, and analyst-brief policy.",
    ],
    "next_real_step": (
        "After each scored case, keep solver integrity separate and write one "
        "private benchmark_case_insight_v0 from the complete evaluation evidence."
    ),
}

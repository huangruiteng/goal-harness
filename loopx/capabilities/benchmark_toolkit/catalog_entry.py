from __future__ import annotations

from typing import Any

from .four_arm_contract import (
    BENCHMARK_FOUR_ARM_ATTESTATIONS,
    BENCHMARK_FOUR_ARM_RUNNER_OBLIGATIONS,
)

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
    "workflow_skill": {
        "name": "loopx-benchmark",
        "delivery": "packaged_host_skill",
        "activation": "task_triggered",
        "goal_switch_required": False,
        "project_copy_required": False,
        "install_command": "loopx workflow-skills --install",
        "readback_command": "loopx doctor",
        "authority_boundary": (
            "Skill discovery does not grant runner, shell, network, credential, "
            "private-evidence, or Goal mutation authority; todo requirements, "
            "provider bindings, and host permissions remain authoritative."
        ),
    },
    "commands": [
        {
            "command": (
                "loopx benchmark four-arm-contract "
                "--spec-json <four-arm-spec.json> "
                "--require-qualified --format json"
            ),
            "purpose": (
                "Freeze a Goal/LoopX by plain/domain-hint factorial design and "
                "prove task-goal prompt parity within each matched pair."
            ),
            "write_boundary": (
                "read-only local spec; default receipt contains prompt hashes but "
                "not prompt text, qualifies design only, and grants no runner or "
                "startup authority"
            ),
        },
        {
            "command": (
                "loopx benchmark source-revision-fence "
                "--source-checkout <clean-source> "
                "--expected-revision <pin> "
                "--observed-reference-revision <observed-head> "
                "--require-admitted --format json"
            ),
            "purpose": (
                "Fail closed before a new run when the installed source no "
                "longer matches the caller-observed reference head."
            ),
            "write_boundary": (
                "local Git readback only; caller owns reference observation, "
                "fetch, installation, and launch"
            ),
        },
        {
            "command": (
                "loopx benchmark experiment-board-show --goal-id <goal-id> "
                "[--four-arm-contract-json <compact-contract.json>] --format json"
            ),
            "purpose": (
                "Read baseline, treatment, explore, countability, effort, and "
                "insight status before selecting or launching another arm; an "
                "explicit four-arm contract also projects conditional effects."
            ),
            "write_boundary": "read-only project-local public-safe domain state",
        },
        {
            "command": (
                "loopx benchmark runtime-observation --admission-active "
                "--job-receipt-state resolved --runner-owner-state alive "
                "--require-healthy --format json"
            ),
            "purpose": (
                "Classify exact-job runtime evidence without treating an active "
                "admission-ledger row as proof of process liveness."
            ),
            "write_boundary": (
                "read-only compact provider facts; caller owns discovery, startup "
                "grace, terminal writes, reconciliation, and slot release"
            ),
        },
        {
            "command": (
                "loopx benchmark runtime-continuity "
                "--launch-runtime-digest <sha256> "
                "--closeout-runtime-digest <sha256> "
                "--launch-generation-digest <sha256> "
                "--closeout-generation-digest <sha256> "
                "--event-window-state <state> --require-qualified --format json"
            ),
            "purpose": (
                "Fail closed unless terminal closeout retains the launch runtime "
                "artifact, attempt generation, and qualified event window."
            ),
            "write_boundary": (
                "read-only compact provider facts; emits no digest, run identity, "
                "event payload, or path, and performs no closeout write"
            ),
        },
        {
            "command": (
                "loopx benchmark experiment-board-upsert --goal-id <goal-id> "
                "--row-json <compact-row.json> --execute --format json"
            ),
            "purpose": (
                "Idempotently record one planned, running, or terminal compact run "
                "row, including optional provider-neutral orchestrator runtime "
                "revision provenance; omit --execute for a no-write preview."
            ),
            "write_boundary": (
                "explicit project-local domain-state write; rejects raw paths, "
                "logs, trajectories, hidden evaluation, credentials, and unknown fields"
            ),
        },
        {
            "command": (
                "loopx benchmark experiment-board-reconcile --goal-id <goal-id> "
                "--source-ledger <provider-board.jsonl> --execute --format json"
            ),
            "purpose": (
                "Monotonically fold one or more provider-owned public-safe board "
                "shards into the canonical project experiment board; omit --execute "
                "for a no-write preview."
            ),
            "write_boundary": (
                "explicit project-local canonical board write; source paths are "
                "never recorded and conflicting terminal states fail closed"
            ),
        },
        {
            "command": (
                "loopx benchmark concurrency-configure --goal-id <goal-id> "
                "--max-active-cases <n> --target-active-cases <n> "
                "--max-baseline-cases <n> --max-test-cases <n> "
                "--reserved-test-cases <n> "
                "[--require-resource-headroom-receipt] --execute --format json"
            ),
            "purpose": (
                "Configure one combined capacity envelope across baseline, control, "
                "treatment, and explore runs."
            ),
            "write_boundary": (
                "explicit project-local admission state; grants no runner or model "
                "launch authority"
            ),
        },
        {
            "command": (
                "loopx benchmark concurrency-admit --goal-id <goal-id> "
                "--run-id <run-id> --case-id <case-id> --arm-role <role> "
                "[--resource-headroom-json <receipt.json>] "
                "--execute --format json"
            ),
            "purpose": (
                "Atomically reserve a baseline or test-group slot immediately "
                "before an independently authorized runner launch."
            ),
            "write_boundary": (
                "compact project-local run identities only; resource receipts and "
                "raw metrics are not persisted, and launch, liveness, and termination "
                "remain runner-owned"
            ),
        },
        {
            "command": (
                "loopx benchmark integrity-qualification "
                "--trajectory-json <private.json> "
                "--runtime-attestation-json <attestation.json> "
                "[--restricted-access-adjudication-json <compact.json>] "
                "--require-qualified --format json"
            ),
            "purpose": (
                "Reduce private ATIF tool evidence and runner-owned isolation "
                "facts to a compact integrity qualification receipt; scanner "
                "suspicion remains eligible unless post-run causal review confirms "
                "restricted disclosure and use."
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
                "loopx benchmark verify-verifier-reward <reward.json> "
                "--require-valid --format json"
            ),
            "purpose": (
                "Validate a verifier reward.json against the numeric-only "
                "verifier reward contract (pier VerifierResult compatible)."
            ),
            "write_boundary": (
                "read-only local reward file; emits stable counts, labels, and "
                "reason codes only, never raw reward values"
            ),
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
    "agent_usage": {
        "benchmark_start_hint": (
            "At benchmark start, read the experiment board and concurrency envelope "
            "before selecting or launching a case; update the same stable board row "
            "and capacity reservation at every material run transition. "
            "Providers that keep separate board shards reconcile them "
            "into the canonical board before agent readback."
        ),
        "required_sequence": [
            "read_experiment_board_before_launch_or_case_selection",
            "qualify_four_arm_contract_when_domain_guidance_is_a_factor",
            "configure_or_read_concurrency_envelope_before_launch",
            "reconcile_admission_ledger_with_real_runner_liveness",
            "backfill_when_concurrency_status_reports_underfilled",
            "qualify_source_revision_before_each_new_run_admission",
            "qualify_resource_headroom_when_the_envelope_requires_a_receipt",
            "atomically_admit_case_slot_before_runner_launch",
            "upsert_preregistered_or_running_row_when_a_run_starts",
            "classify_exact_runtime_observation_during_active_monitor_cycles",
            "require_runtime_continuity_before_terminal_closeout_write",
            "adjudicate_restricted_access_suspicion_after_solver_and_score_terminal",
            "upsert_terminal_score_countability_effort_and_insight_status",
            "release_case_slot_after_terminal_or_runner_invalid_transition",
            "read_matched_comparisons_before_selecting_the_next_arm",
        ],
        "board_commands": {
            "read": (
                "loopx benchmark experiment-board-show --goal-id <goal-id> "
                "[--four-arm-contract-json <compact-contract.json>] --format json"
            ),
            "preview": (
                "loopx benchmark experiment-board-upsert --goal-id <goal-id> "
                "--row-json <compact-row.json> --format json"
            ),
            "write": (
                "loopx benchmark experiment-board-upsert --goal-id <goal-id> "
                "--row-json <compact-row.json> --execute --format json"
            ),
            "reconcile": (
                "loopx benchmark experiment-board-reconcile --goal-id <goal-id> "
                "--source-ledger <provider-board.jsonl> --execute --format json"
            ),
        },
        "concurrency_commands": {
            "status": (
                "loopx benchmark concurrency-status --goal-id <goal-id> --format json"
            ),
            "configure": (
                "loopx benchmark concurrency-configure --goal-id <goal-id> "
                "--max-active-cases <n> --target-active-cases <n> "
                "--max-baseline-cases <n> --max-test-cases <n> "
                "--reserved-test-cases <n> "
                "[--require-resource-headroom-receipt] --execute --format json"
            ),
            "admit": (
                "loopx benchmark concurrency-admit --goal-id <goal-id> "
                "--run-id <run-id> --case-id <case-id> --arm-role <role> "
                "[--resource-headroom-json <receipt.json>] "
                "--execute --format json"
            ),
            "release": (
                "loopx benchmark concurrency-release --goal-id <goal-id> "
                "--run-id <run-id> --execute --format json"
            ),
        },
        "concurrency_boundary": (
            "The envelope owns capacity admission only. A benchmark runner remains "
            "responsible for resource observation, launch, liveness, termination, "
            "and score transitions. When configured, admission requires a fresh "
            "public-safe resource-headroom receipt but never persists raw metrics."
        ),
        "selection_rule": (
            "Keep diagnostic-only explore rows separate and make paired claims "
            "only from matched_pair_countable comparisons."
        ),
    },
    "four_arm_study": {
        "benchmark_start_hint": (
            "When a benchmark-specific solver hint may affect outcomes, preregister "
            "goal_plain, loopx_plain, goal_<hint-id>, and loopx_<hint-id>; keep "
            "guided startup out of the task prompt and require equal prompt hashes "
            "within each Goal/LoopX pair."
        ),
        "factors": {
            "loopx": [False, True],
            "domain_hint": [False, True],
        },
        "attestations": list(BENCHMARK_FOUR_ARM_ATTESTATIONS),
        "runner_obligations": list(BENCHMARK_FOUR_ARM_RUNNER_OBLIGATIONS),
        "historical_boundary": (
            "An arm that mixed startup and domain guidance remains diagnostic-only "
            "and cannot be relabeled into the factorial study."
        ),
    },
    "concurrency_occupancy": {
        "benchmark_start_hint": (
            "When starting a benchmark, add one continuous_monitor todo that "
            "reconciles the admission ledger with exact runner liveness and "
            "backfills any safe target-occupancy gap."
        ),
        "monitor_todo_template": {
            "task_class": "continuous_monitor",
            "action_kind": "benchmark_concurrency_occupancy_monitor",
            "trigger": "launch_terminal_invalid_or_periodic_liveness_transition",
            "text": (
                "Classify exact-job receipt and runner-owner facts through the typed "
                "runtime observation on each launch, terminal or runner-invalid "
                "transition and a bounded cadence. Apply its terminal or runner-invalid "
                "transition before releasing that reservation; then read "
                "concurrency-status and, when launch authority already exists, admit "
                "and start up to missing_cases without exceeding caps."
            ),
        },
        "authority_boundary": (
            "The monitor may launch replacements only under separately granted "
            "runner authority; the envelope grants no model, verifier, upload, or "
            "submission authority."
        ),
    },
    "post_run_case_analysis": {
        "benchmark_start_hint": (
            "When starting a benchmark, add one continuous_monitor todo that "
            "refreshes aggregate score coverage and runs the post-run analyst brief "
            "on every material scored-case transition, with bounded periodic reviews "
            "while the campaign is active."
        ),
        "monitor_todo_template": {
            "task_class": "continuous_monitor",
            "action_kind": "benchmark_case_insight_monitor",
            "trigger": "material_scored_case_transition",
            "active_campaign_review": "bounded_periodic",
            "delivery_contract": {
                "catalog_role": "guidance_template",
                "creation_owner": "benchmark_startup_provider",
                "scheduler_owner": "registered_monitor_runtime",
            },
            "text": (
                "On each material scored-case transition and bounded active-campaign "
                "review, validate exact-job runtime authority and advance at least one "
                "bounded solver-trajectory slice even when no case became terminal; "
                "refresh the public-safe aggregate score and coverage summary, report "
                "material changes to the user, and after solver termination read the "
                "complete private evaluation evidence and write one "
                "benchmark_case_insight_v0."
            ),
        },
        "aggregate_reporting": {
            "score_source": "experiment_board_public_safe_projection",
            "insight_boundary": (
                "report only public-safe conclusions from post-run insight; never "
                "copy raw private evidence into the user update"
            ),
            "report_on": [
                "new_countable_terminal",
                "countability_or_pairing_change",
                "aggregate_score_or_direction_change",
                "new_reusable_case_insight",
                "systematic_runner_or_treatment_fidelity_issue",
            ],
            "report_fields": [
                "countable_baseline_cases",
                "countable_treatment_cases",
                "matched_pair_count",
                "aggregate_primary_metric_by_arm",
                "binary_outcome_by_arm_when_available",
                "improved_flat_regressed_pair_counts",
                "new_case_insights_and_next_probe",
            ],
            "unchanged_policy": (
                "Do not send a repetitive user update when no score, coverage, "
                "direction, insight, or material runner state changed."
            ),
        },
        "active_progress_readback": {
            "workspace_basis": [
                "recorded_start_revision_to_current_head",
                "current_worktree_status",
            ],
            "runtime_basis": [
                "active_admission_ledger",
                "exact_job_runtime_receipt",
                "exact_runner_owner_liveness_after_startup_grace",
                "terminal_result_presence",
                "goal_state_and_event_freshness",
                "typed_runner_error_category",
            ],
            "runtime_contract": (
                "Admission-ledger occupancy is not liveness. A healthy active run "
                "requires a resolved exact-job receipt and a live exact runner owner; "
                "terminal or lost-owner observations require provider reconciliation "
                "before slot release. These are provider obligations; the reducer "
                "classifies facts but performs no monitor, write, or release effect."
            ),
            "trajectory_basis": (
                "solver_trajectory_phase_without_hidden_evaluator_feedback"
            ),
            "classification_owner": "benchmark_monitor_provider",
            "stalled_when": {
                "all": [
                    "no_committed_progress",
                    "no_uncommitted_progress",
                ],
                "any": [
                    "trajectory_stale",
                    "typed_fatal_runner_error",
                ],
            },
            "non_signals": [
                "clean_worktree_alone",
                "raw_log_error_count_alone",
            ],
        },
        "hint": (
            "After the solver has stopped and scoring is complete, read the task, "
            "real trajectory, final patch or workspace, hidden tests, grader or "
            "verifier, and full failure and score details; explain the decisive "
            "evidence, why the outcome happened, whether it was expected, and what "
            "LoopX should test or change next."
        ),
        "restricted_access_adjudication": {
            "hint": (
                "When the integrity scan marks restricted access as suspected, "
                "inspect the real solver trajectory, tool results, and final "
                "workspace after terminal scoring. Keep the run countable unless "
                "restricted material was actually disclosed and causally entered "
                "a solving or validation decision."
            ),
            "artifact_template": {
                "schema_version": "benchmark_restricted_access_adjudication_v0",
                "decision": "<qualified_with_warning-or-confirmed_cheating>",
                "reviewer_role": "post_run_analyst",
                "reviewed_surfaces": [
                    "solver_trajectory",
                    "tool_results",
                    "final_workspace",
                ],
                "restricted_material_disclosed": "<true-or-false>",
                "causal_use_observed": "<true-or-false>",
                "evidence_id": "<public-safe-pointer>",
            },
            "decision_rule": (
                "Only disclosed=true plus causal_use=true may be "
                "confirmed_cheating; all other reviewed suspicion remains "
                "qualified_with_warning."
            ),
        },
        "role_boundary": {
            "solver": (
                "must not access hidden tests, grader or verifier sources, expected "
                "answers, or official feedback during the solving phase"
            ),
            "active_campaign_monitor": (
                "may inspect the solver-owned trajectory and exact-job runtime while "
                "the solver is active, but must not read hidden evaluator evidence or "
                "send findings back into the solving arm"
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
            "schema_version": "benchmark_four_arm_contract_v0",
            "module": "loopx.capabilities.benchmark_toolkit.four_arm_contract",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_concurrency_envelope_v0",
            "module": "loopx.capabilities.benchmark_toolkit.concurrency_envelope",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_source_revision_fence_v0",
            "module": "loopx.capabilities.benchmark_toolkit.source_revision_fence",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_experiment_board_row_v0",
            "module": "loopx.capabilities.benchmark_toolkit.experiment_board",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_experiment_board_v0",
            "module": "loopx.capabilities.benchmark_toolkit.experiment_board",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_integrity_qualification_v0",
            "module": "loopx.capabilities.benchmark_toolkit.integrity",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_restricted_access_adjudication_v0",
            "module": "loopx.capabilities.benchmark_toolkit.integrity",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_runtime_integrity_attestation_v0",
            "module": "loopx.capabilities.benchmark_toolkit.integrity",
            "doc": "loopx/capabilities/benchmark_toolkit/README.md",
        },
        {
            "schema_version": "benchmark_runtime_observation_v0",
            "module": "loopx.capabilities.benchmark_toolkit.runtime_observation",
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
    "smokes": [
        (
            "python -m pytest tests/capabilities/test_benchmark_toolkit.py "
            "tests/capabilities/test_benchmark_concurrency_envelope.py "
            "tests/capabilities/test_benchmark_experiment_board.py "
            "tests/capabilities/test_benchmark_source_revision_fence.py -q"
        )
    ],
    "docs": ["loopx/capabilities/benchmark_toolkit/README.md"],
    "boundaries": [
        "The four-arm contract controls prompt parity and factor identity only; providers retain launch, guided-startup, task, model, verifier, and score authority.",
        "The toolkit never grants runner, Docker, model, upload, submission, or publication authority; each effect remains separately gated.",
        "Source revision qualification is read-only and caller-observed: it does not fetch, install, update a checkout, or rewrite an already admitted run.",
        "Raw trajectories are private local inputs to integrity qualification and are never copied into receipts, ledgers, docs, or PR artifacts.",
        "A clean trajectory scan is not isolation proof: runner-owned permission and verifier-order attestations are mandatory and fail closed when absent.",
        "Automated restricted-access matches are countable suspicion only; confirmed cheating requires post-run agent evidence of both disclosure and causal use.",
        "Concurrent Docker runs must bind runtime evidence to one exact job-owned container; image-only discovery is not sufficient.",
        "Admission-ledger occupancy never proves runner liveness; active health requires a resolved exact-job receipt and a live exact runner owner after startup grace.",
        "Integrity qualification establishes countability eligibility only; an independent official result and matched experiment contract are still required.",
        "Post-run analyst access never widens the solving agent's evidence boundary or grants feedback reuse in another scored run.",
        "Concurrency reservations are not runtime liveness: runners must reconcile exact processes before release or backfill.",
        "The experiment board is a compact projection, not a score authority: benchmark-family runners and scoring adapters remain outside the active capability.",
    ],
    "next_real_step": (
        "Use the board and concurrency envelope before launch, classify exact runtime "
        "during active monitor cycles, and after each scored case advance one bounded "
        "trajectory review while keeping solver integrity separate from private analysis."
    ),
}

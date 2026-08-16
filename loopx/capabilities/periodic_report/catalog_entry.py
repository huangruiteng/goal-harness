from __future__ import annotations

from typing import Any


PERIODIC_REPORT_CATALOG_ENTRY: dict[str, Any] = {
    "id": "periodic-report",
    "origin": "builtin",
    "visibility": "public",
    "provider_id": "loopx-core",
    "documentation": {
        "source_root": "loopx/capabilities/periodic_report",
        "site_root": "capabilities/periodic-report",
        "canonical": "README.md",
    },
    "title": "Provider-neutral periodic and progress report runs",
    "status": "active-preview",
    "default_enabled": False,
    "real_world_anchor": "scheduled and milestone project reports with verified archive and delivery",
    "user_value": (
        "Generate a concise weekly project report from the active session "
        "with one built-in portable profile, while retaining deterministic "
        "trigger, receipt, partial-state, and retry contracts for custom runs."
    ),
    "entry_command": "loopx periodic-report inspect-profile --preset weekly --format json",
    "commands": [
        {
            "command": "loopx periodic-report inspect-profile --preset weekly --format json",
            "purpose": "Resolve the built-in domain-neutral weekly profile for an explicitly requested in-session report.",
            "write_boundary": "local preset inspection only; creates no schedule, persists no activation, declares no sink, and performs no provider lookup or write",
        },
        {
            "command": "loopx periodic-report inspect-profile --profile-json <profile.json> --format json",
            "purpose": "Validate custom project trigger, source, renderer, schedule, and extension sink bindings.",
            "write_boundary": "local profile inspection only; performs no provider lookup, schedule mutation, or write",
        },
        {
            "command": "loopx periodic-report evaluate-trigger --request-json <request.json> --format json",
            "purpose": "Select, coalesce, cool down, and deduplicate cadence or material progress triggers without provider effects.",
            "write_boundary": "local trigger decision only; no source read, schedule mutation, rendering, archive write, message delivery, or provider write",
        },
        {
            "command": "loopx periodic-report compose-run --request-json <request.json> --format json",
            "purpose": "Normalize one typed report attempt and derive stable run/sink idempotency, state, and retry evidence.",
            "write_boundary": "local contract output only; no source read, rendering, archive write, message delivery, or provider write",
        },
        {
            "command": "loopx periodic-report archive-openviking --request-json <request.json> --available-capability openviking_context_write --execute --format json",
            "purpose": "Invoke the optional OpenViking archive extension after profile, runtime-capability, manifest permission, revision, and doctor checks.",
            "write_boundary": "writes report.md and then manifest.json only when --execute is explicit; exact Resource readback is required for sent",
        },
    ],
    "implemented_protocols": [
        {
            "schema_version": "periodic_report_profile_v0",
            "module": "loopx.capabilities.periodic_report.profile",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_activation_v0",
            "module": "loopx.capabilities.periodic_report.profile",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_project_progress_projection_v0",
            "module": "loopx.capabilities.periodic_report.project_progress",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_trigger_decision_v0",
            "module": "loopx.capabilities.periodic_report.triggers",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_v0",
            "module": "loopx.capabilities.periodic_report.core",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_editorial_orchestration_v0",
            "module": "loopx.capabilities.periodic_report.adapters",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_generation_bundle_v0",
            "module": "loopx.capabilities.periodic_report.bindings",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_generation_receipt_v0",
            "module": "loopx.capabilities.periodic_report.bindings",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_sink_binding_v0",
            "module": "loopx.capabilities.periodic_report.bindings",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_extension_readiness_v0",
            "module": "loopx.capabilities.periodic_report.bindings",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
        {
            "schema_version": "periodic_report_delivery_receipt_v0",
            "module": "loopx.capabilities.periodic_report.bindings",
            "doc": "docs/reference/protocols/periodic-report-v0.md",
        },
    ],
    "smokes": [
        "python3 examples/periodic-report-smoke.py",
        "python3 examples/periodic-report-adapters-smoke.py",
        "python3 examples/periodic-report-html-smoke.py",
        "python3 examples/periodic-report-bindings-smoke.py",
        "python3 examples/openviking-periodic-report-extension-smoke.py",
        "python3 examples/periodic-report-profile-smoke.py",
    ],
    "docs": [
        "loopx/capabilities/periodic_report/README.md",
        "docs/reference/protocols/periodic-report-v0.md",
    ],
    "boundaries": [
        "An explicit request in an active project session may select the built-in weekly-progress profile for one provider-free local generation; it persists no project activation and creates no schedule or sink.",
        "Custom, unattended, or externally delivered reports remain disabled until a project profile and host/runtime authority explicitly enable those separate paths.",
        "The core owns material trigger classification, coalescing, cooldown/deduplication, period/profile binding, deterministic identity, receipts, run state, and retry projection.",
        "Profiles own schedule calculation, enabled trigger kinds, minimum interval, timezone, sections, audience, and project policy.",
        "Adapters own domain source collection; renderers and sinks own all provider effects and verified readback.",
        "The document builder compiles hero summaries only from typed primary outcomes, risks, and next actions; renderers reject authored or stale summaries.",
        "Markdown and HTML render from one normalized document; runtime and delivery-receipt items must be supporting, HTML collapses them, and Markdown preserves them in a labeled appendix.",
        "Raw content, messages, logs, transcripts, credentials, secrets, and private paths are rejected.",
        "The optional openviking-periodic-report extension implements only the archive sink; it rejects activation unless the periodic-report profile is enabled, its sink binding matches, and openviking_context_write is observed.",
    ],
    "next_real_step": (
        "Exercise the built-in weekly profile in a normal project session, then "
        "prove one separately configured scheduled delivery without widening its "
        "authority into the portable path."
    ),
}

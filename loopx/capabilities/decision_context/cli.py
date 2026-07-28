from __future__ import annotations

import argparse
from collections.abc import Callable, Collection
from datetime import datetime, timezone
from pathlib import Path

from .assembler import DecisionEvidenceRecords
from .architecture import build_decision_context_architecture_packet
from .profile import resolve_decision_context_activation
from .runtime import assemble_profile_decision_evidence
from .sources import build_decision_source_manifest

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def _collection_size(value: object) -> int:
    if isinstance(value, Collection) and not isinstance(value, (str, bytes)):
        return len(value)
    return 0


def _render(payload: dict[str, object]) -> str:
    capability = payload.get("capability")
    capability_id = (
        capability.get("capability_id")
        if isinstance(capability, dict)
        else "decision_context"
    )
    return "\n".join(
        [
            "# Decision Context",
            "",
            f"- status: `{payload.get('status')}`",
            f"- capability_id: `{capability_id}`",
            f"- packet_schemas: `{_collection_size(payload.get('packet_schemas'))}`",
            f"- source_schemas: `{_collection_size(payload.get('source_schemas'))}`",
            f"- source_count: `{payload.get('source_count', 0)}`",
            "",
        ]
    )


def register_decision_context_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "decision-context",
        help="Inspect the provider-neutral decision evidence and outcome contract.",
    )
    commands = parser.add_subparsers(dest="decision_context_command", required=True)
    architecture = commands.add_parser(
        "architecture",
        help="Render the default-off Stage-0 Decision Context contract.",
    )
    add_subcommand_format(architecture)
    status = commands.add_parser(
        "inspect-profile",
        help="Inspect a default-off goal profile without provider access.",
    )
    add_subcommand_format(status)
    status.add_argument("--goal-id", required=True)
    status.add_argument("--agent-id", required=True)
    status.add_argument(
        "--profile",
        help="Private local profile. Omit it to prove the default-off route.",
    )

    manifest = commands.add_parser(
        "source-manifest",
        help="Project an enabled private source profile into a public-safe manifest.",
    )
    add_subcommand_format(manifest)
    manifest.add_argument("--goal-id", required=True)
    manifest.add_argument("--agent-id", required=True)
    manifest.add_argument("--profile", required=True)
    manifest.add_argument(
        "--observed-at",
        help="Optional timezone-aware ISO-8601 time for a reproducible manifest.",
    )
    prepare = commands.add_parser(
        "prepare-evidence",
        help=(
            "Run bounded source scans and exact reads without applying private "
            "cursor proposals."
        ),
    )
    add_subcommand_format(prepare)
    prepare.add_argument("--goal-id", required=True)
    prepare.add_argument("--agent-id", required=True)
    prepare.add_argument("--profile", required=True)
    prepare.add_argument("--decision-id", required=True)
    prepare.add_argument(
        "--cursor-state",
        help="Optional private JSON object mapping source ids to opaque cursors.",
    )
    prepare.add_argument(
        "--source-id",
        action="append",
        help=(
            "Explicit enabled source to scan. Repeat to include on-demand "
            "sources; omit to scan automatic sources only."
        ),
    )
    prepare.add_argument(
        "--observed-at",
        help="Optional timezone-aware ISO-8601 assembly time.",
    )
    prepare.add_argument(
        "--before",
        help="Optional timezone-aware upper bound for source changes.",
    )
    prepare.add_argument(
        "--timeout-seconds",
        type=float,
        help="Optional bounded provider timeout override.",
    )


def handle_decision_context_command(
    args: argparse.Namespace,
    *,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "decision-context":
        return None
    if args.decision_context_command == "architecture":
        payload = build_decision_context_architecture_packet()
    elif args.decision_context_command == "prepare-evidence":
        now = datetime.now(timezone.utc).isoformat()
        observed_at = str(getattr(args, "observed_at", None) or "").strip() or now
        before = str(getattr(args, "before", None) or "").strip() or observed_at
        activation, assembly = assemble_profile_decision_evidence(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            profile_path=Path(args.profile),
            decision_id=args.decision_id,
            observed_at=observed_at,
            before=before,
            cursor_path=(
                Path(args.cursor_state)
                if str(getattr(args, "cursor_state", None) or "").strip()
                else None
            ),
            source_ids=(
                tuple(args.source_id)
                if getattr(args, "source_id", None) is not None
                else None
            ),
            rebase=lambda _collection: DecisionEvidenceRecords(),
            timeout_seconds=getattr(args, "timeout_seconds", None),
        )
        payload = activation | {
            "assembly": assembly.public_packet() if assembly is not None else None,
            "semantic_rebase_performed": False,
            "validated_writeback_required": assembly is not None,
            "cursor_commit_allowed": False,
            "cursor_state_mutated": False,
        }
    elif args.decision_context_command in {"inspect-profile", "source-manifest"}:
        profile_value = str(getattr(args, "profile", None) or "").strip()
        status, profile = resolve_decision_context_activation(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            profile_path=Path(profile_value) if profile_value else None,
        )
        if args.decision_context_command == "inspect-profile":
            payload = status
        else:
            observed_at = str(getattr(args, "observed_at", None) or "").strip()
            payload = status | {
                "source_manifest": (
                    build_decision_source_manifest(
                        goal_id=args.goal_id,
                        observed_at=(
                            observed_at or datetime.now(timezone.utc).isoformat()
                        ),
                        sources=profile.sources,
                    )
                    if status["available"] and profile is not None
                    else None
                )
            }
    else:
        raise ValueError("decision-context requires a supported subcommand")
    print_payload(payload, output_format(args), _render)
    return 0

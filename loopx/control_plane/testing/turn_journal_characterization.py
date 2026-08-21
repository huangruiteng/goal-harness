from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


TURN_JOURNAL_CHARACTERIZATION_CORPUS_VERSION = (
    "loopx_turn_journal_characterization_corpus_v0"
)
TURN_JOURNAL_CHARACTERIZATION_PROBE_VERSION = (
    "loopx_turn_journal_characterization_probe_v0"
)
TURN_JOURNAL_CHARACTERIZATION_REQUEST_VERSION = (
    "loopx_turn_journal_characterization_request_v0"
)
TURN_JOURNAL_CHARACTERIZATION_DIFFERENTIAL_VERSION = (
    "loopx_turn_journal_characterization_differential_v0"
)

_PROJECTION_FIELDS = (
    "decision",
    "journal_status",
    "replay_legal",
    "goal_matches",
    "owner_matches",
    "turn_key_matches",
    "phases_form_ordered_prefix",
    "completed_phases",
    "tombstone_retained",
    "violations",
    "effects",
)
_INVARIANT_FIELDS = (
    "decision",
    "replay_legal",
    "goal_matches",
    "owner_matches",
    "turn_key_matches",
    "phases_form_ordered_prefix",
    "tombstone_retained",
)
_BANNED_KEYS = frozenset(
    {
        "credential",
        "credentials",
        "password",
        "raw_log",
        "raw_logs",
        "secret",
        "token",
        "trajectory",
        "trajectories",
        "verifier_output",
    }
)

def _walk(value: Any) -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            rows.append((str(key), child))
            rows.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_walk(child))
    return rows


def validate_turn_journal_characterization_corpus(
    corpus: Mapping[str, Any],
) -> None:
    if corpus.get("schema_version") != TURN_JOURNAL_CHARACTERIZATION_CORPUS_VERSION:
        raise ValueError("Turn-journal corpus schema_version mismatch")
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Turn-journal corpus requires at least one case")

    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            raise ValueError("Turn-journal corpus cases must be objects")
        case_id = str(case.get("case_id") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError("Turn-journal case_id must be non-empty and unique")
        seen.add(case_id)
        if not str(case.get("invariant_id") or "").strip():
            raise ValueError(f"Turn-journal case {case_id} requires invariant_id")
        if not str(case.get("rationale") or "").strip():
            raise ValueError(f"Turn-journal case {case_id} requires rationale")

        request = case.get("request")
        invariant = case.get("invariant")
        if not isinstance(request, Mapping) or not isinstance(
            request.get("journal"), Mapping
        ):
            raise ValueError(f"Turn-journal case {case_id} requires request.journal")
        for field in ("goal_id", "agent_id", "turn_key"):
            value = request.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"Turn-journal case {case_id} requires request.{field}"
                )
        if not isinstance(invariant, Mapping):
            raise ValueError(f"Turn-journal case {case_id} requires invariant")
        unknown = set(invariant) - set(_INVARIANT_FIELDS)
        if unknown:
            raise ValueError(
                f"Turn-journal case {case_id} has unsupported invariants: "
                + ", ".join(sorted(unknown))
            )
        if not invariant:
            raise ValueError(f"Turn-journal case {case_id} has no invariants")

    for key, value in _walk(corpus):
        if key.lower() in _BANNED_KEYS:
            raise ValueError(f"Turn-journal corpus contains banned key: {key}")
        if isinstance(value, str) and (value.startswith("/") or "file://" in value):
            raise ValueError(f"Turn-journal corpus contains a local path in {key}")


def load_turn_journal_characterization_corpus(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Turn-journal corpus root must be an object")
    validate_turn_journal_characterization_corpus(payload)
    return payload


def run_turn_journal_probe_command(
    corpus: Mapping[str, Any],
    *,
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str] | None = None,
    implementation_id: str,
) -> dict[str, Any]:
    """Run one semantic owner as an isolated whole-corpus JSON process."""

    validate_turn_journal_characterization_corpus(corpus)
    if not command:
        raise ValueError("Turn-journal probe command must not be empty")
    request = {
        "schema_version": TURN_JOURNAL_CHARACTERIZATION_REQUEST_VERSION,
        "implementation_id": implementation_id,
        "corpus": corpus,
    }
    env = dict(os.environ)
    if environment is not None:
        env.update(environment)
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        input=json.dumps(request, sort_keys=True),
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Turn-journal probe failed with exit {completed.returncode}: "
            + completed.stderr.strip()
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Turn-journal probe returned malformed JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Turn-journal probe root must be an object")
    if payload.get("schema_version") != TURN_JOURNAL_CHARACTERIZATION_PROBE_VERSION:
        raise RuntimeError("Turn-journal probe returned an unsupported schema")
    return payload


def _index_probe_rows(
    corpus: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    if receipt.get("schema_version") != TURN_JOURNAL_CHARACTERIZATION_PROBE_VERSION:
        raise ValueError("Turn-journal probe receipt schema_version mismatch")
    if receipt.get("corpus_schema_version") != corpus.get("schema_version"):
        raise ValueError("Turn-journal probe receipt corpus_schema_version mismatch")
    if not str(receipt.get("implementation_id") or "").strip():
        raise ValueError("Turn-journal probe receipt requires implementation_id")
    rows = receipt.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Turn-journal probe receipt requires rows")
    expected_keys = {"case_id", *_PROJECTION_FIELDS}
    indexed: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Turn-journal probe rows must be objects")
        case_id = str(row.get("case_id") or "").strip()
        if not case_id or case_id in indexed:
            raise ValueError("Turn-journal probe case_id must be non-empty and unique")
        if set(row) != expected_keys:
            raise ValueError(f"Turn-journal probe {case_id} projection shape mismatch")
        if row.get("effects") != []:
            raise ValueError(f"Turn-journal probe {case_id} must remain effect-free")
        indexed[case_id] = row
    corpus_ids = {str(case["case_id"]) for case in corpus["cases"]}
    if set(indexed) != corpus_ids:
        raise ValueError("Turn-journal probe rows must match the corpus case set")
    return indexed


def evaluate_turn_journal_invariants(
    corpus: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, list[str]]:
    validate_turn_journal_characterization_corpus(corpus)
    by_id = _index_probe_rows(corpus, receipt)
    failures: dict[str, list[str]] = {}
    for case in corpus["cases"]:
        assert isinstance(case, Mapping)
        case_id = str(case["case_id"])
        row = by_id.get(case_id)
        if row is None:
            failures[case_id] = ["probe row missing"]
            continue
        invariant = case["invariant"]
        assert isinstance(invariant, Mapping)
        mismatches = [
            f"{field}: expected {expected!r}, got {row.get(field)!r}"
            for field, expected in invariant.items()
            if row.get(field) != expected
        ]
        if mismatches:
            failures[case_id] = mismatches
    return failures


def compare_turn_journal_characterization_receipts(
    corpus: Mapping[str, Any],
    base_receipt: Mapping[str, Any],
    candidate_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    base_failures = evaluate_turn_journal_invariants(corpus, base_receipt)
    candidate_failures = evaluate_turn_journal_invariants(corpus, candidate_receipt)
    base_rows = _index_probe_rows(corpus, base_receipt)
    candidate_rows = _index_probe_rows(corpus, candidate_receipt)

    comparisons: list[dict[str, Any]] = []
    for case in corpus["cases"]:
        assert isinstance(case, Mapping)
        case_id = str(case["case_id"])
        base = base_rows.get(case_id)
        candidate = candidate_rows.get(case_id)
        exact_match = base == candidate and base is not None
        failures = candidate_failures.get(case_id, [])
        if failures or base is None or candidate is None:
            status = "failed"
        elif exact_match:
            status = "passed"
        else:
            status = "review_required"
        comparisons.append(
            {
                "case_id": case_id,
                "status": status,
                "exact_match": exact_match,
                "base_invariant_failures": base_failures.get(case_id, []),
                "candidate_invariant_failures": failures,
            }
        )

    failed = [row for row in comparisons if row["status"] == "failed"]
    review = [row for row in comparisons if row["status"] == "review_required"]
    return {
        "schema_version": TURN_JOURNAL_CHARACTERIZATION_DIFFERENTIAL_VERSION,
        "ok": not failed and not base_failures,
        "exact_parity": not failed and not review and not base_failures,
        "base_invariant_failures": base_failures,
        "candidate_invariant_failures": candidate_failures,
        "failed_case_count": len(failed),
        "review_required_case_count": len(review),
        "cases": comparisons,
    }

"""CLI tests for governed goal amendment proposal submission and readback.

Verifies ``loopx goal-amendment-proposal`` and its ``loopx
amendment-proposal`` alias end to end: a proposal submitted through the CLI
lands in ``runtime/goals/<goal>/amendment-proposals/journal.jsonl`` and the
``--list`` readback returns the same retained row (the Stage 2 production
consumer loop), plus markdown output, idempotent resubmission, and the
fail-closed negative paths. The causal replan obligation is never a CLI
input: every positive path derives it from the fixture quota run ledger
(the same read-time projection production uses), and every negative path
proves a forged or missing history cannot produce authority.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.cli import main as cli_main
from tests.control_plane.test_goal_amendment_proposal import (
    GOAL_ID,
    OTHER_GOAL_ID,
    _ack_run,
    _append_runs,
    _default_events,
    _derived_obligation,
    _proposal,
    _stall_runs,
    _write_fixture,
)


def _run_amendment_cli(
    capsys: pytest.CaptureFixture[str],
    registry: Path,
    *argv: str,
    runtime_root: Path | None = None,
) -> tuple[int, dict[str, Any], str]:
    top_argv = ["--registry", str(registry)]
    if runtime_root is not None:
        top_argv.extend(["--runtime-root", str(runtime_root)])
    exit_code = cli_main([*top_argv, *argv])
    captured = capsys.readouterr()
    payload: dict[str, Any] = {}
    if "--format" in argv and "json" in argv:
        payload = json.loads(captured.out)
    return exit_code, payload, captured.out


def _write_submit_inputs(
    tmp_path: Path,
    proposal: dict[str, object],
) -> Path:
    proposal_json = tmp_path / "proposal.json"
    proposal_json.write_text(json.dumps(proposal), encoding="utf-8")
    return proposal_json


def _submit_argv(
    paths: dict[str, Path],
    proposal_json: Path,
    *extra: str,
) -> tuple[str, ...]:
    return (
        "--proposal-json",
        str(proposal_json),
        "--project",
        str(paths["project"]),
        *extra,
    )


def test_cli_submits_proposal_and_lists_journal_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths)
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["admission"] == "admitted"
    assert payload["canonical_effect"] == "none"
    assert payload["proposal_id"] == "gap_stage2_001"
    assert payload["journal_append_sequence"] == 1
    # The retained causal id is the one derived from the run ledger — no
    # authority payload was passed through the CLI at all.
    assert (
        payload["replan_obligation_id"] == _derived_obligation(paths)["obligation_id"]
    )

    journal = (
        paths["runtime"] / "goals" / GOAL_ID / "amendment-proposals" / "journal.jsonl"
    )
    assert journal.is_file()
    lines = journal.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    retained = json.loads(lines[0])
    assert retained["proposal_id"] == "gap_stage2_001"

    # End-to-end readback: the journal row the CLI wrote is what --list
    # returns, through the same runtime root the registry carries.
    list_code, list_payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        GOAL_ID,
        "--format",
        "json",
    )

    assert list_code == 0
    assert list_payload["ok"] is True
    assert list_payload["goal_id"] == GOAL_ID
    assert list_payload["count"] == 1
    assert list_payload["rows"][0]["proposal_id"] == "gap_stage2_001"
    assert list_payload["rows"][0]["journal_append_sequence"] == 1


def test_cli_submits_proposal_markdown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths)
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, _, stdout = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "markdown",
    )

    assert exit_code == 0
    assert "# LoopX Goal Amendment Proposal" in stdout
    assert "- ok: `True`" in stdout
    assert f"- goal_id: `{GOAL_ID}`" in stdout
    assert "- admission: `admitted`" in stdout
    assert "- canonical_effect: `none`" in stdout

    list_code, _, list_stdout = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        GOAL_ID,
        "--format",
        "markdown",
    )

    assert list_code == 0
    assert "- count: 1" in list_stdout
    assert "`gap_stage2_001` admission=`admitted` sequence=1" in list_stdout


def test_cli_alias_amendment_proposal_matches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths)
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["admission"] == "admitted"


def test_cli_resubmission_is_idempotent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths)
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    first_code, first_payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )
    second_code, second_payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert first_code == second_code == 0
    assert (
        second_payload["journal_append_sequence"]
        == first_payload["journal_append_sequence"]
        == 1
    )
    _, list_payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        GOAL_ID,
        "--format",
        "json",
    )
    assert list_payload["count"] == 1


def test_cli_nonexistent_obligation_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths, {"replan_obligation_id": "replan-deadbeefdeadbeef"})
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "does not match an open replan obligation" in payload["error"]
    journal = (
        paths["runtime"] / "goals" / GOAL_ID / "amendment-proposals" / "journal.jsonl"
    )
    assert not journal.exists()


def test_cli_unregistered_proposer_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths, {"proposer_agent_id": "agent-z"})
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "not registered" in payload["error"]


def test_cli_list_without_goal_id_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "--list requires --goal-id" in payload["error"]


def test_cli_malformed_proposal_json_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal_json = tmp_path / "broken.json"
    proposal_json.write_text('{"schema_version": tru', encoding="utf-8")

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--proposal-json",
        str(proposal_json),
        "--project",
        str(paths["project"]),
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "error" in payload


def test_cli_submit_without_run_history_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # No run ledger at all: the obligation inventory is empty and the
    # causal chain cannot be verified from string shape alone. There is no
    # CLI flag that could supply an authority payload instead.
    paths = _write_fixture(tmp_path, events=_default_events(), runs=[])
    proposal = _proposal(paths, {"replan_obligation_id": "replan-0123456789abcdef"})
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "does not match an open replan obligation" in payload["error"]


def test_cli_list_path_traversal_sibling_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())
    # Place a sibling journal under runtime/goals/victim/amendment-proposals/journal.jsonl
    sibling_journal = (
        paths["runtime"] / "goals" / "victim" / "amendment-proposals" / "journal.jsonl"
    )
    sibling_journal.parent.mkdir(parents=True, exist_ok=True)
    sibling_journal.write_text(
        json.dumps({"proposal_id": "gap_victim_001", "journal_append_sequence": 1})
        + "\n",
        encoding="utf-8",
    )

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        "../victim",
        "--format",
        "json",
        runtime_root=paths["runtime"],
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "single path segment" in payload["error"]
    assert "gap_victim_001" not in str(payload)


def test_cli_list_path_traversal_dotdot_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        "..",
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "single path segment" in payload["error"]


def test_cli_list_absolute_path_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        "/victim",
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "single path segment" in payload["error"]


def test_cli_list_path_separator_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        "victim/extra",
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "single path segment" in payload["error"]


def test_cli_list_unknown_goal_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(tmp_path, events=_default_events())

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        "--list",
        "--goal-id",
        "goal_unknown",
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "goal is not registered" in payload["error"]


def test_cli_submit_forged_run_rows_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Appending plain rows into the quota ledger cannot mint authority:
    # rows without a typed progress observation (or with an unattributable
    # one) derive no obligation, so the causal chain fails closed.
    forged_rows = [
        {
            "generated_at": "2026-09-01T00:00:00+00:00",
            "goal_id": GOAL_ID,
            "agent_id": "agent-a",
            "classification": "bounded_replan_progress",
            "turn_instance_id": "turn_stage2_forged_0",
        },
        {
            "generated_at": "2026-09-01T00:01:00+00:00",
            "goal_id": GOAL_ID,
            "agent_id": "agent-a",
            "classification": "quota_monitor_poll",
            "turn_instance_id": "turn_stage2_forged_1",
            "progress_observation": {"result_class": "blocked"},
        },
    ]
    paths = _write_fixture(tmp_path, events=_default_events(), runs=forged_rows)
    proposal = _proposal(paths, {"replan_obligation_id": "replan-0123456789abcdef"})
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "does not match an open replan obligation" in payload["error"]
    journal = (
        paths["runtime"] / "goals" / GOAL_ID / "amendment-proposals" / "journal.jsonl"
    )
    assert not journal.exists()


def test_cli_legacy_receipt_journal_is_inert(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The retired receipts.jsonl path is read by nothing: appending a
    # self-minted "open" receipt row there neither admits a proposal nor
    # changes the derived causal id.
    paths = _write_fixture(tmp_path, events=_default_events())
    legacy = (
        paths["runtime"] / "goals" / GOAL_ID / "replan-obligations" / "receipts.jsonl"
    )
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "replan_obligation_authority_envelope_v0",
                "goal_id": GOAL_ID,
                "status": "open",
                "receipt": {"receipt_id": "rcpt_forged", "status": "open"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    proposal = _proposal(paths)
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["admission"] == "admitted"
    assert (
        payload["replan_obligation_id"] == _derived_obligation(paths)["obligation_id"]
    )
    assert payload["replan_obligation_id"] != "rcpt_forged"


def test_cli_submit_after_settlement_ack_run_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The real close path: refresh-state appends an autonomous_replan_ack
    # run into the quota ledger, derivation stops there, and a proposal
    # naming the previously open obligation fails closed.
    paths = _write_fixture(tmp_path, events=_default_events())
    proposal = _proposal(paths)
    obligation_id = _derived_obligation(paths)["obligation_id"]

    _append_runs(paths, [_ack_run(obligation_id)])
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )
    assert exit_code == 1
    assert payload["ok"] is False
    assert "does not match an open replan obligation" in payload["error"]
    journal = (
        paths["runtime"] / "goals" / GOAL_ID / "amendment-proposals" / "journal.jsonl"
    )
    assert not journal.exists()


def test_cli_submit_wrong_goal_obligation_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = _write_fixture(
        tmp_path,
        events=_default_events(),
        with_other_goal=True,
        other_goal_runs=_stall_runs(
            goal_id=OTHER_GOAL_ID, hypothesis="hypothesis-stage2-peer"
        ),
    )
    peer_obligation_id = _derived_obligation(
        paths, agent_id=None, goal_id=OTHER_GOAL_ID
    )["obligation_id"]
    proposal = _proposal(paths, {"replan_obligation_id": peer_obligation_id})
    proposal_json = _write_submit_inputs(tmp_path, proposal)

    exit_code, payload, _ = _run_amendment_cli(
        capsys,
        paths["registry"],
        "goal-amendment-proposal",
        *_submit_argv(paths, proposal_json),
        "--format",
        "json",
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert "does not match an open replan obligation" in payload["error"]

"""Pytest projection of the shared-goal-authority E2E stage ladder.

Each ladder row becomes one parametrized test. Rows whose environment gate is
closed skip with ``unverified: <reason>`` so a green pytest run never implies
that a live provider was exercised; the ladder's own exit policy is pinned
separately so the standalone runner cannot report green while unverified.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from loopx.control_plane.testing import authority_e2e_ladder as ladder


LIVE_ENVIRONMENT_VARIABLES = (
    ladder.POSTGRES_URL_VARIABLE,
    ladder.NOKV_LIVE_FLAG,
    *ladder.NOKV_STACK_VARIABLES,
)
GATED_ROW_IDS = ("s0.nokv_live_matrix", "s2b.postgresql_conformance_live")
REQUIRED_PENDING_ROW_IDS = (
    "s2a.nokv_live_qualification",
    "s2c2.outbox_prepared_then_committed_entries",
    "s2c2.drain_idempotent",
    "s2c2.sigkill_between_primary_write_and_drain",
    "s2c2.sigkill_mid_drain",
    "s2c2.rollback_with_pending_entries",
    "s2c2.dual_runtime_root_consistency",
    "s2c2.parity_equal",
    "s2c2.parity_divergent_detects_foreign_edit",
    "s2c2.migration_seeds_and_drains",
    "s2c2.growth_measurement_gate",
)


def _row_parameters() -> Iterator[object]:
    for row in ladder.LADDER_ROWS:
        marks = (
            [pytest.mark.skipif(os.name == "nt", reason="requires POSIX cross-process flock and SIGKILL")]
            if row.posix_only
            else []
        )
        yield pytest.param(row, id=row.id, marks=marks)


@pytest.mark.parametrize("row", list(_row_parameters()))
def test_ladder_row_passes_or_is_declared_unverified(
    row: ladder.LadderRow,
    tmp_path: Path,
) -> None:
    result = ladder.run_row(row, root=tmp_path, environ=os.environ)
    if result.status == "unverified":
        pytest.skip(f"unverified: {result.reason_code}")
    report = ladder.build_report(
        [result],
        pending=(),
        allow_unverified=False,
        environ=os.environ,
        forbidden=ladder.default_forbidden_tokens([tmp_path], os.environ),
    )
    reported = report["rows"][0]
    assert reported["status"] == "pass", (reported["reason_code"], reported["evidence"])
    assert report["summary"] == {"pass": 1, "fail": 0, "unverified": 0, "pending": 0}
    assert report["exit_policy"]["exit_code"] == 0


def test_registry_vocabulary_and_pending_rows_are_declared_not_claimed() -> None:
    row_ids = [row.id for row in ladder.LADDER_ROWS]
    pending_ids = [row.id for row in ladder.PENDING_ROWS]
    assert len(set(row_ids)) == len(row_ids)
    assert set(row_ids).isdisjoint(pending_ids)
    assert set(REQUIRED_PENDING_ROW_IDS) <= set(pending_ids)
    assert {row.stage for row in ladder.LADDER_ROWS} == {"0", "1", "2b", "2c1"}
    assert {row.stage for row in ladder.PENDING_ROWS} == {"2a", "2c2"}
    assert all(row.gate in ladder.GATES for row in ladder.LADDER_ROWS)
    assert all(row.product_path in ladder.PRODUCT_PATHS for row in ladder.LADDER_ROWS)
    with pytest.raises(ValueError):
        ladder.LadderRow(
            id="bad.stage",
            stage="9",
            title="invalid",
            product_path="real_cli",
            gate="deterministic",
            posix_only=False,
            run=lambda _context: ladder.passed(),
        )


def test_main_never_reports_green_while_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in LIVE_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    report_path = tmp_path / "report.json"
    argv = ["--report-json", str(report_path)]
    for row_id in GATED_ROW_IDS:
        argv.extend(["--row", row_id])

    assert ladder.main(argv) == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema_version"] == ladder.REPORT_SCHEMA
    assert report["summary"] == {"pass": 0, "fail": 0, "unverified": 2, "pending": 0}
    assert {row["status"] for row in report["rows"]} == {"unverified"}
    assert {row["reason_code"] for row in report["rows"]} == {
        "nokv_live_env_missing",
        "postgres_url_missing",
    }
    assert report["exit_policy"] == {
        "allow_unverified": False,
        "exit_code": 1,
        "rule": ladder.EXIT_POLICY_RULE,
    }
    assert report["bindings"]["postgres_url_sha256_prefix"] is None
    assert report["bindings"]["nokv_client_config_sha256"] is None
    assert report["bindings"]["loopx_commit"] is None or len(report["bindings"]["loopx_commit"]) == 40
    captured = capsys.readouterr()
    assert "unverified rows:" in captured.err

    assert ladder.main([*argv, "--allow-unverified"]) == 0
    relaxed = json.loads(report_path.read_text(encoding="utf-8"))
    assert relaxed["summary"]["unverified"] == 2
    assert relaxed["exit_policy"]["allow_unverified"] is True
    assert relaxed["exit_policy"]["exit_code"] == 0
    capsys.readouterr()


def test_privacy_scan_turns_leaks_into_failures(tmp_path: Path) -> None:
    row = ladder.row_by_id("s0.file_matrix_twelve_rows")
    leaking = ladder.RowResult(
        row=row,
        status="pass",
        reason_code=None,
        evidence={"pointer": str(tmp_path / "leaked-root")},
        duration_ms=1,
    )
    clean = ladder.RowResult(
        row=ladder.row_by_id("s1.cli_document_decodes_through_ts_store"),
        status="pass",
        reason_code=None,
        evidence={"cursor": "3"},
        duration_ms=1,
    )

    report = ladder.build_report(
        [leaking, clean],
        pending=ladder.PENDING_ROWS,
        allow_unverified=True,
        environ=os.environ,
        forbidden=ladder.default_forbidden_tokens([tmp_path], os.environ),
    )

    statuses = {row["id"]: row for row in report["rows"]}
    assert statuses[leaking.row.id]["status"] == "fail"
    assert statuses[leaking.row.id]["reason_code"] == "privacy_violation"
    assert str(tmp_path) not in json.dumps(report)
    assert statuses[clean.row.id]["status"] == "pass"
    assert report["summary"] == {
        "pass": 1,
        "fail": 1,
        "unverified": 0,
        "pending": len(ladder.PENDING_ROWS),
    }
    assert report["exit_policy"]["exit_code"] == 1
    assert {row["status"] for row in report["pending"]} == {"pending"}


def test_list_prints_rows_and_pending_declarations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert ladder.main(["--list"]) == 0
    listing = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in listing["rows"]] == [row.id for row in ladder.LADDER_ROWS]
    assert [row["id"] for row in listing["pending"]] == [row.id for row in ladder.PENDING_ROWS]
    assert all(row["status"] == "pending" for row in listing["pending"])

    assert ladder.main(["--list", "--stage", "2c2"]) == 0
    stage_listing = json.loads(capsys.readouterr().out)
    assert stage_listing["rows"] == []
    assert {row["stage"] for row in stage_listing["pending"]} == {"2c2"}

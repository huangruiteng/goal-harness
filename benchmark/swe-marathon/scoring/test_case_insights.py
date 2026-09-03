#!/usr/bin/env python3
"""case_insights.py 的回归测试：产出的记录必须满足 LoopX 官方
`benchmark_case_insight_projection_v0` 契约（upstream #3878 / RFC #3812）。

契约取值集合与 upstream study_projection.py 一致（该模块依赖 loopx 深层包，无法单文件
加载，故在此按同一规则逐项断言）。可直接 `python3 test_case_insights.py`。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import case_insights
from case_insights import SCHEMA as _SCHEMA, TERMINAL as _TERMINAL

_EXPECT = {"expected", "unexpected", "mixed", "unknown"}
_CONF = {"low", "medium", "high"}
_ALLOWED = {
    "schema_version", "benchmark_id", "study_id", "case_id", "run_id", "outcome_status",
    "failure_class", "causal_summary", "expectedness", "implication", "next_probe",
    "confidence", "evidence_refs", "privacy_classification", "producer_redaction_attested",
}
_TOKENS = ("benchmark_id", "study_id", "case_id", "run_id", "failure_class")
_TEXTS = ("causal_summary", "implication", "next_probe")


def _assert_contract(p: dict) -> None:
    """逐项断言一条记录满足契约（每条 assert 单独一句，便于定位）。"""
    assert set(p) <= _ALLOWED
    assert p["schema_version"] == _SCHEMA
    assert p["privacy_classification"] == "public_safe"
    assert p["producer_redaction_attested"] is True
    assert p["expectedness"] in _EXPECT
    assert p["confidence"] in _CONF
    assert p["outcome_status"] in _TERMINAL
    assert isinstance(p["evidence_refs"], list)
    assert len(p["evidence_refs"]) <= 16
    for ref in p["evidence_refs"]:
        assert isinstance(ref, str) and ref.strip()
        assert "\n" not in ref                      # 句柄不得内联 raw
    for field in _TOKENS:
        assert isinstance(p[field], str) and p[field].strip()
    for field in _TEXTS:
        assert isinstance(p[field], str)
        assert len(p[field]) <= 600


def _sample_data() -> dict:
    def cell(task, arm, **kw):
        base = {"task": task, "arm": arm, "reward": 0.0, "partial": 0.0,
                "build_failed": False, "status": None, "cont": 0, "unblock": 0,
                "run_dir": f"{task}/{arm}/20260102-030405/{arm}"}
        base.update(kw)
        return base
    return {"cells": {
        "kubernetes-rust-rewrite": {
            "codex-cli": cell("kubernetes-rust-rewrite", "codex-cli",
                              build_failed=True, status="blocked", unblock=8, cont=10),
            "heartbeat": cell("kubernetes-rust-rewrite", "heartbeat",
                              reward=1.0, partial=1.0, status="complete", cont=9),
        },
        "zstd-decoder": {
            "codex-cli": cell("zstd-decoder", "codex-cli",
                              partial=0.60, status="blocked", unblock=8, cont=10),
        },
        "excel-clone": {  # 无明确洞见 → 不应生成记录
            "plain": cell("excel-clone", "plain", partial=0.49),
        },
    }}


def test_records_conform_to_contract():
    recs = case_insights.build(_sample_data())
    assert recs
    for r in recs:
        _assert_contract(r)


def test_build_failure_and_idle_churn_detected():
    fclasses = {(r["case_id"], r["failure_class"]) for r in case_insights.build(_sample_data())}
    assert ("kubernetes-rust-rewrite", "build_failed_gate_zeroed") in fclasses
    assert ("zstd-decoder", "unattended_continuation_idle_churn") in fclasses


def test_no_insight_case_is_skipped():
    recs = case_insights.build(_sample_data())
    assert not any(r["case_id"] == "excel-clone" for r in recs)


def test_build_failure_maps_to_runner_invalid():
    recs = case_insights.build(_sample_data())
    bf = next(r for r in recs if r["failure_class"] == "build_failed_gate_zeroed")
    assert bf["outcome_status"] == "runner_invalid"


def test_evidence_refs_carry_no_timestamp():
    for r in case_insights.build(_sample_data()):
        for ref in r["evidence_refs"]:
            assert "20260102-030405" not in ref     # stamp 不进公开句柄


def test_cli_writes_valid_file():
    import sys
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "data.json", Path(d) / "ci.json"
        src.write_text(json.dumps(_sample_data()))
        argv = sys.argv
        sys.argv = ["case_insights.py", str(src), str(out)]
        try:
            case_insights.main()
        finally:
            sys.argv = argv
        payload = json.loads(out.read_text())
        assert payload["schema_version"] == _SCHEMA
        assert payload["count"] == len(payload["records"])
        for r in payload["records"]:
            _assert_contract(r)


def _run() -> int:
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except AssertionError as exc:
                fails += 1
                print(f"  FAIL {name}: {exc}")
    print("OK" if not fails else f"{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_run())

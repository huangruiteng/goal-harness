from __future__ import annotations

import os
from pathlib import Path

from loopx.capabilities.public_safe_outbound.scanner import scan_paths, scan_texts


def test_detects_credentials() -> None:
    # build the sample at runtime so the source stays clean of the literal pattern
    fake_key = "ark" + "-11111111-2222-3333-4444-555555555555-00000"
    assignment = "api" + "_key = '" + fake_key + "'"
    res = scan_texts({"a": assignment})
    assert res.ok is False
    assert any(h.rule_id in {"ark_api_key", "api_key_assignment"} for h in res.hits)


def test_detects_internal_domain(tmp_path: Path) -> None:
    markers = tmp_path / "markers.json"
    markers.write_text('{"internal_domains": ["corp.example"]}', encoding="utf-8")
    os.environ["PUBLIC_SAFE_CONFIG"] = str(markers)
    try:
        res = scan_texts({"b": "ref: https://code.corp.example/internal/repo"})
    finally:
        os.environ.pop("PUBLIC_SAFE_CONFIG", None)
    assert res.ok is False
    assert any(h.rule_id == "internal_domain" for h in res.hits)


def test_detects_private_path() -> None:
    private = "/" + "home/example-user/code-reading/some_workspace"
    res = scan_texts({"c": "run from " + private})
    assert res.ok is False
    assert any(h.rule_id == "private_abs_path" for h in res.hits)


def test_clean_text_passes(tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_text(
        "Public-safe note: compare baseline vs treatment on the same model/task/verifier.",
        encoding="utf-8",
    )
    res = scan_paths([tmp_path / "ok.md"])
    assert res.ok is True

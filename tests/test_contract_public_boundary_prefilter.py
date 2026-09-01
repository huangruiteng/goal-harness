from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from loopx import contract


@pytest.mark.parametrize(
    ("rule_name", "line"),
    [
        ("private_doc_url", "https://tenant.lark" + "office.com/wiki/example"),
        ("private_doc_url", "https://docs" + ".internal/example"),
        ("credential", "Bear" + "er literal"),
        ("credential", "AK" + "IA1234567890ABCDEF"),
        ("credential", "tok" + "en=literal"),
        ("credential", "pass" + "word=literal"),
        ("credential", "Author" + "ization: literal"),
        ("local_private_path", "/" + "Users/alice/Documents/example.md"),
        ("local_private_path", "/" + "Users/alice/code-reading/example.md"),
        ("local_private_path", "/ext" + "_data/example.md"),
        ("internal_task_id", "ticket t-" + "20260828123456-example"),
        ("private_ip", "host 10" + ".1.2.3"),
        ("private_ip", "host 172" + ".31.2.3"),
        ("private_ip", "host 192" + ".168.2.3"),
    ],
)
def test_every_authoritative_leak_pattern_has_a_matching_prefilter(
    rule_name: str,
    line: str,
) -> None:
    rule = contract.LEAK_RULES[rule_name]

    assert rule.pattern.search(line)
    assert rule.is_candidate(line.casefold())


def test_prefilter_only_runs_regex_for_candidate_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingPattern:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def search(self, line: str) -> None:
            self.lines.append(line)

    pattern = RecordingPattern()
    monkeypatch.setattr(
        contract,
        "LEAK_RULES",
        {
            "private_ip": contract.LeakRule(
                pattern=pattern,  # type: ignore[arg-type]
                required_literals=("candidate",),
            )
        },
    )
    (tmp_path / "sample.md").write_text(
        "ordinary public line\ncandidate without a regex hit\nanother ordinary line\n",
        encoding="utf-8",
    )

    payload = contract.scan_public_boundary([tmp_path])

    assert payload["ok"] is True
    assert pattern.lines == ["candidate without a regex hit"]


def test_prefilter_preserves_all_boundary_hit_categories(tmp_path: Path) -> None:
    lines = [
        "https://tenant.lark" + "office.com/wiki/example",
        "tok" + "en=literal",
        "/" + "Users/alice/Documents/example.md",
        "ticket t-" + "20260828123456-example",
        "host 10" + ".1.2.3",
    ]
    (tmp_path / "sample.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    payload: dict[str, Any] = contract.scan_public_boundary([tmp_path])

    assert payload["hits"] == [
        "sample.md:1: private_doc_url",
        "sample.md:2: credential",
        "sample.md:3: local_private_path",
        "sample.md:4: internal_task_id",
        "sample.md:5: private_ip",
    ]

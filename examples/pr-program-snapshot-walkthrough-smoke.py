#!/usr/bin/env python3
"""Synthetic walkthrough for provider-neutral PR program snapshot tracking.

GH-C81: Prove stable program identity, observed head snapshots, compact diff
classification, review/CI transition lineage, and fail-closed unknown state.
Keep provider payloads, review bodies, credentials, local paths, and merge
authority outside the snapshot.

This walkthrough exercises the pure diff rules from the PR program skill
without touching GitHub, fetching, or writing any branch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT_PATH = REPO_ROOT / "skills" / "loopx-pr-program" / "scripts" / "diff_snapshot.py"


def _load_diff_module():
    spec = importlib.util.spec_from_file_location("loopx_pr_program_diff", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(
    program_id: str,
    *,
    complete: bool,
    repositories: list[str],
    generated_at: str,
    refs: list[dict[str, object]],
    requirements: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "loopx_pr_program_snapshot_v0",
        "program_id": program_id,
        "generated_at": generated_at,
        "result_completeness": {
            "complete": complete,
            "scope": {
                "repositories": repositories,
                "states": ["open"],
                "authors": [],
                "time_window": {"since": None, "until": None},
            },
        },
        "requirements": requirements or [],
        "change_requests": refs,
    }


def _ref(
    ref: str,
    *,
    title: str = "feat: example",
    checks: str = "passed",
    review: str = "pending",
    work_item: str = "action_required",
    priority: str = "P0",
    requirement_ids: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, object]:
    return {
        "ref": ref,
        "title": title,
        "state": "open",
        "draft": False,
        "target_branch": "main",
        "head_sha": ref.replace("#", "s") * 10,
        "updated_at": "2026-08-10T00:00:00Z",
        "checks": checks,
        "review": review,
        "work_item": work_item,
        "theme": "runtime controls",
        "priority": priority,
        "requirement_ids": requirement_ids or [],
        "depends_on": depends_on or [],
        "supersedes": [],
        "description_digest": f"sha256:{ref}",
        "review_digest": f"sha256:review-{ref}",
    }


def main() -> None:
    module = _load_diff_module()

    # ── 1. Complete snapshot: detects material change and removal ────────
    previous = _snapshot(
        "public-runtime-program",
        complete=True,
        repositories=["example/runtime"],
        generated_at="2026-08-10T09:00:00Z",
        refs=[
            _ref("example/runtime#42", title="feat(runtime): expose control"),
            _ref("example/runtime#41", title="refactor(runtime): clean up"),
        ],
    )
    current = _snapshot(
        "public-runtime-program",
        complete=True,
        repositories=["example/runtime"],
        generated_at="2026-08-10T10:00:00Z",
        refs=[
            _ref("example/runtime#42", title="feat(runtime): expose control", checks="failed"),
        ],
    )

    delta = module.build_delta(previous, current)
    assert delta["material_change"] is True, delta
    assert delta["baseline_advance_allowed"] is True, delta
    assert delta["result_hash"] == delta["observed_result_hash"], delta
    assert delta["removed"] == ["example/runtime#41"], delta
    assert delta["changed"][0]["ref"] == "example/runtime#42", delta
    assert delta["changed"][0]["changed_fields"] == ["checks"], delta
    print("  1. Complete snapshot detects material change and removal: ok")

    # ── 2. Incomplete snapshot: does not treat absent rows as removed ───
    incomplete = _snapshot(
        "public-runtime-program",
        complete=False,
        repositories=["example/runtime"],
        generated_at="2026-08-10T10:00:00Z",
        refs=[_ref("example/runtime#42", title="feat(runtime): expose control")],
    )

    delta2 = module.build_delta(previous, incomplete)
    assert delta2["baseline_advance_allowed"] is False, delta2
    assert delta2["result_hash"] is None, delta2
    assert delta2["removed"] == [], delta2
    assert delta2["omitted_previous"] == ["example/runtime#41"], delta2
    print("  2. Incomplete snapshot preserves absent rows: ok")

    # ── 3. Scope mismatch fails closed ──────────────────────────────────
    different_scope = _snapshot(
        "public-runtime-program",
        complete=True,
        repositories=["example/other"],
        generated_at="2026-08-10T10:00:00Z",
        refs=[_ref("example/runtime#42")],
    )

    delta3 = module.build_delta(previous, different_scope)
    assert delta3["scope_matches_previous"] is False, delta3
    assert delta3["baseline_advance_allowed"] is False, delta3
    assert delta3["baseline_block_reason"] == "scope_mismatch", delta3
    print("  3. Scope mismatch fails closed: ok")

    # ── 4. Stable identity: same scope, same refs, same content = no change
    identical = _snapshot(
        "public-runtime-program",
        complete=True,
        repositories=["example/runtime"],
        generated_at="2026-08-10T10:00:00Z",
        refs=[
            _ref("example/runtime#42", title="feat(runtime): expose control"),
            _ref("example/runtime#41", title="refactor(runtime): clean up"),
        ],
    )

    delta4 = module.build_delta(previous, identical)
    assert delta4["material_change"] is False, delta4
    assert delta4["removed"] == [], delta4
    assert delta4["changed"] == [], delta4
    print("  4. Identical snapshots produce no material change: ok")

    # ── 5. New PR detected as added ─────────────────────────────────────
    expanded = _snapshot(
        "public-runtime-program",
        complete=True,
        repositories=["example/runtime"],
        generated_at="2026-08-10T11:00:00Z",
        refs=[
            _ref("example/runtime#42", title="feat(runtime): expose control"),
            _ref("example/runtime#41", title="refactor(runtime): clean up"),
            _ref("example/runtime#43", title="fix(runtime): handle edge case"),
        ],
    )

    delta5 = module.build_delta(previous, expanded)
    assert delta5["material_change"] is True, delta5
    assert delta5["added"] == ["example/runtime#43"], delta5
    print("  5. New PR detected as added: ok")

    # ── 6. Transition lineage: checks → review changes are detected ─────
    review_changed = _snapshot(
        "public-runtime-program",
        complete=True,
        repositories=["example/runtime"],
        generated_at="2026-08-10T12:00:00Z",
        refs=[
            _ref("example/runtime#42", title="feat(runtime): expose control", checks="passed", review="approved", work_item="passed"),
            _ref("example/runtime#41", title="refactor(runtime): clean up"),
        ],
    )

    delta6 = module.build_delta(previous, review_changed)
    transition_refs = {c["ref"] for c in delta6["changed"]}
    assert "example/runtime#42" in transition_refs, delta6
    print("  6. Review transition lineage detected: ok")

    # ── 7. Fail-closed: unknown fields in snapshot don't break diff ─────
    unknown_field_snapshot = dict(previous)
    unknown_field_snapshot["change_requests"] = [
        dict(r, **{"unknown_provider_field": "should_be_ignored"})  # type: ignore[arg-type]
        for r in previous["change_requests"]  # type: ignore[union-attr]
    ]
    delta7 = module.build_delta(previous, unknown_field_snapshot)
    assert delta7["material_change"] is False, delta7
    print("  7. Unknown fields ignored (fail-closed): ok")

    # ── 8. Public-safety: no private fields leak into delta ─────────────
    def assert_public_safe(payload: object) -> None:
        import json
        text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
        forbidden = ["/Users/", "/private/", "/tmp/", "api_key", "password", "secret"]
        leaked = [n for n in forbidden if n.lower() in text.lower()]
        assert not leaked, f"Leaked: {leaked}"

    assert_public_safe(delta)
    assert_public_safe(delta3)
    print("  8. Public-safe boundary verified: ok")

    print("\npr-program-snapshot-walkthrough ok")


if __name__ == "__main__":
    main()

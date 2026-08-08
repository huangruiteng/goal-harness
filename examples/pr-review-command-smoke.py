#!/usr/bin/env python3
"""Smoke-test the public-safe `loopx pr-review` command."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import loopx.pr_review as pr_review_module
from loopx.pr_review import (
    _github_search_date,
    build_pr_review_packet,
    load_pr_fixture,
)

FIXTURE = REPO_ROOT / "examples" / "fixtures" / "pr-review.public.json"
PR_REVIEW_SKILL = REPO_ROOT / "skills" / "loopx-pr-review" / "SKILL.md"
PRIVATE_PATTERNS = [
    re.compile(r"/" + r"Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/" + r"private/"),
    re.compile(r"/tmp/"),
    re.compile(r"/var/"),
    re.compile(r"[A-Za-z]:\\\\Users\\\\"),
]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def assert_public_safe(payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for pattern in PRIVATE_PATTERNS:
        if pattern.search(text):
            raise AssertionError(f"pr-review payload leaked private pattern {pattern.pattern!r}")


def main() -> int:
    skill_source = PR_REVIEW_SKILL.read_text(encoding="utf-8")
    skill_text = " ".join(skill_source.split())
    for phrase in (
        "This skill is a thin host adapter",
        "loopx --format json pr-review --state all",
        "agent_response_contract.review_execution_contract",
        "pull_requests[].review_plan",
        "pull_requests[].review_template",
        "pull_requests[].evidence_commands",
        "Apply `completion_gate` literally",
        "Re-read the remote head immediately before verdict and publication",
        "formal `REQUEST_CHANGES`",
        "Read the published review back",
        "Route approval, merge, self-merge, and admin bypass to `loopx-pr-merge`",
        "Full PR Review And Bilingual Format",
        "findings-only or blocker-only body is incomplete",
        "Cover every changed surface and key symbols",
        "详细中文评审",
        "英文简短结论",
        "complete Chinese five-block review plus one concise English verdict",
        "Full PR Interpretation Depth",
        "Walk one positive path",
        "Walk one negative path",
        "omits whole files/modules is incomplete",
    ):
        assert phrase in skill_text, phrase
    assert len(skill_source.splitlines()) <= 180, len(skill_source.splitlines())
    for duplicated_contract_heading in (
        "Per-PR Evidence And Depth Gate",
        "Motivation Causal Chain",
        "Implementation Execution Chain",
        "Code Volume And Simplification Review",
    ):
        assert duplicated_contract_heading not in skill_source, duplicated_contract_heading

    assert _github_search_date("2026-06-28T00:00:00+08:00") == "2026-06-27"
    assert _github_search_date("2026-06-28T00:00:00Z") == "2026-06-28"
    calls: list[list[str]] = []

    def fake_run_gh_json(args: list[str], *, cwd: Path | None = None) -> object:
        calls.append(args)
        assert args[:2] == ["pr", "list"], calls
        assert "--search" in args and "updated:>=2026-06-27" in args, args
        state = args[args.index("--state") + 1]
        if state == "open":
            return [
                {
                    "number": 900,
                    "title": "Runtime review fixture",
                    "url": "https://github.com/owner/repo/pull/900",
                    "state": "OPEN",
                    "updatedAt": "2026-06-28T00:01:00Z",
                    "files": [{"path": "src/status.py", "additions": 4, "deletions": 1}],
                    "changedFiles": 1,
                    "additions": 4,
                    "deletions": 1,
                    "statusCheckRollup": [],
                }
            ]
        if state == "closed":
            return [
                {
                    "number": 901,
                    "title": "Merged review fixture",
                    "url": "https://github.com/owner/repo/pull/901",
                    "state": "MERGED",
                    "updatedAt": "2026-06-27T23:59:00Z",
                    "closedAt": "2026-06-28T00:03:00Z",
                    "mergedAt": "2026-06-28T00:03:00Z",
                    "files": [{"path": "docs/review.md", "additions": 2, "deletions": 0}],
                    "changedFiles": 1,
                    "additions": 2,
                    "deletions": 0,
                    "statusCheckRollup": [],
                }
            ]
        raise AssertionError(args)

    original_run_gh_json = pr_review_module._run_gh_json
    try:
        pr_review_module._run_gh_json = fake_run_gh_json
        fetched = pr_review_module.fetch_github_pull_requests(
            repo="owner/repo",
            limit=10,
            state_filter="all",
            since="2026-06-28T00:00:00+08:00",
        )
    finally:
        pr_review_module._run_gh_json = original_run_gh_json
    assert len(calls) == 2, calls
    assert [args[args.index("--state") + 1] for args in calls] == ["open", "closed"], calls
    assert fetched[0]["number"] == 900, fetched
    assert fetched[0]["files"][0]["path"] == "src/status.py", fetched
    assert fetched[1]["number"] == 901, fetched
    assert fetched[1]["state"] == "MERGED", fetched

    payload = json.loads(
        run_cli("--format", "json", "pr-review", "--fixture", str(FIXTURE), "--limit", "5").stdout
    )
    assert payload["schema_version"] == "loopx_pr_review_command_response_v0", payload
    request = payload["request"]
    assert request["command"] == "/loopx-pr-review", request
    assert (
        request["cli_command"]
        == "loopx pr-review [--repo owner/repo] [--state open|merged|all] [--since ISO]"
    ), request
    assert request["privacy_mode"] == "public_safe_github_metadata", request
    assert request["dry_run"] is True, request
    assert request["repository"] == "owner/repo", request
    assert request["state_filter"] == "all", request
    assert "result_completeness" in request["include"], request
    assert payload["result_completeness"]["complete"] is True, payload
    assert payload["summary"]["total_pr_count"] == 4, payload["summary"]
    assert payload["summary"]["open_pr_count"] == 3, payload["summary"]
    assert payload["summary"]["merged_pr_count"] == 1, payload["summary"]
    assert payload["summary"]["post_merge_review_count"] == 1, payload["summary"]
    assert payload["summary"]["review_attention_count"] == 3, payload["summary"]
    assert payload["summary"]["draft_count"] == 1, payload["summary"]
    groups = payload["review_groups"]
    assert groups["unmerged"]["group_id"] == "unmerged", groups
    assert groups["merged"]["group_id"] == "merged", groups
    assert groups["unmerged"]["count"] == 3, groups
    assert groups["merged"]["count"] == 1, groups
    assert groups["merged"]["complete"] is True, groups
    assert 770 not in groups["unmerged"]["pr_numbers"], groups
    assert groups["merged"]["pr_numbers"] == [770], groups
    assert groups["unmerged"]["review_sequence"][0]["number"] == 773, groups
    assert groups["merged"]["review_sequence"][0]["number"] == 770, groups
    sequence = payload["review_sequence"]
    assert sequence[0]["number"] == 773, sequence
    assert any(item["number"] == 775 for item in sequence), sequence
    assert any(item["number"] == 770 and item["state"] == "MERGED" for item in sequence), sequence
    assert sequence[0]["risk_hint_level"] == "low", sequence[0]
    assert sequence[0]["main_risk_level"] == "low", sequence[0]
    merged_sequence = next(item for item in sequence if item["number"] == 770)
    assert merged_sequence["risk_hint_level"] == "medium", merged_sequence
    assert merged_sequence["main_risk_level"] == "high", merged_sequence
    first = payload["pull_requests"][0]
    assert first["number"] == 773, first
    assert "newcomer command path" in first["motivation"], first
    template = first["review_template"]
    assert template["schema_version"] == "pr_review_five_block_template_v0", template
    assert "Empty scaffold only" in template["purpose"], template
    assert "review_execution_contract" in template["output_hint"], template
    labels = [section["label"] for section in template["sections"]]
    assert labels == ["动机", "改动思路", "具体改动", "对主干的风险", "我的整体评价"], template
    for section in template["sections"]:
        assert section["content"] == "", section
        assert section["word_hint"], section
        assert section["agent_instruction"], section
        assert "quota.py" not in section["agent_instruction"], section
    assert [section["word_hint"] for section in template["sections"]] == [
        "200-350字",
        "300-500字",
        "450-800字",
        "250-500字",
        "150-300字",
    ], template
    concrete_change = next(
        section for section in template["sections"] if section["label"] == "具体改动"
    )
    assert "### 关键代码讲解" in concrete_change["agent_instruction"], concrete_change
    assert "2-5 behavior-bearing exact-head symbols" in concrete_change["agent_instruction"], concrete_change
    assert "headRefOid" in first["evidence_commands"][0], first["evidence_commands"]
    assert "headRefOid" in first["evidence_commands"][-1], first["evidence_commands"]
    assert template["review_order"][0] == "docs/guides/newcomer-command-path.md", template
    assert first["checks"]["counts"]["success"] == 2, first["checks"]
    assert "public_docs" in first["areas"], first["areas"]
    risk_hint = first["metadata_risk_hint"]
    assert risk_hint["schema_version"] == "pr_metadata_risk_hint_v0", risk_hint
    assert risk_hint["level"] == "low", risk_hint
    assert "Metadata-only" in risk_hint["disclaimer"], risk_hint
    assert "quota.py" not in json.dumps(risk_hint), risk_hint
    main_risk = first["main_regression_analysis"]
    assert main_risk["schema_version"] == "main_regression_analysis_v0", main_risk
    assert main_risk["risk_level"] == "low", main_risk
    assert main_risk["post_merge_review"] is False, main_risk
    assert main_risk["potential_regressions"], main_risk
    assert main_risk["bug_risks"], main_risk

    default_payload = json.loads(
        run_cli("--format", "json", "pr-review", "--fixture", str(FIXTURE)).stdout
    )
    assert default_payload["request"]["limit"] == 100, default_payload["request"]
    assert "autonomous_review" not in default_payload, default_payload

    observed = json.loads(
        run_cli(
            "--format",
            "json",
            "pr-review",
            "--fixture",
            str(FIXTURE),
            "--state",
            "open",
            "--autonomous-observation",
        ).stdout
    )
    observation = observed["autonomous_review"]
    assert observed["request"]["autonomous_observation"] is True, observed["request"]
    assert "autonomous_review" in observed["request"]["include"], observed["request"]
    assert (
        observation["schema_version"] == "pull_request_review_queue_observation_v0"
    ), observation
    assert observation["observation_state"] == "material_transition", observation
    assert observation["candidate_count"] == 1, observation
    assert observation["candidate"]["number"] == 773, observation
    assert (
        observation["candidate"]["head_oid"]
        == "7730000000000000000000000000000000000000"
    ), observation
    assert observation["write_authority_granted"] is False, observation
    assert_public_safe(observed)

    with tempfile.TemporaryDirectory() as temp_dir:
        previous_path = Path(temp_dir) / "previous.json"
        previous_path.write_text(json.dumps(observed), encoding="utf-8")
        unchanged = json.loads(
            run_cli(
                "--format",
                "json",
                "pr-review",
                "--fixture",
                str(FIXTURE),
                "--state",
                "open",
                "--autonomous-observation",
                "--previous-observation-json",
                str(previous_path),
            ).stdout
        )
        progressed = json.loads(
            run_cli(
                "--format",
                "json",
                "pr-review",
                "--fixture",
                str(FIXTURE),
                "--state",
                "open",
                "--autonomous-observation",
                "--previous-observation-json",
                str(previous_path),
                "--handled-exact-head",
                "773@7730000000000000000000000000000000000000",
            ).stdout
        )
    assert unchanged["request"]["previous_observation_supplied"] is True, unchanged[
        "request"
    ]
    assert (
        unchanged["autonomous_review"]["observation_state"] == "observed_unchanged"
    ), unchanged
    assert unchanged["autonomous_review"]["candidate"]["number"] == 771, unchanged
    assert (
        unchanged["autonomous_review"]["projected_candidate_count"] == 2
    ), unchanged
    progressed_observation = progressed["autonomous_review"]
    assert (
        progressed_observation["observation_state"] == "observed_unchanged"
    ), progressed
    assert progressed_observation["candidate"]["number"] == 771, progressed
    assert (
        progressed_observation["projected_candidate_count"] == 1
    ), progressed
    assert progressed_observation["handled_exact_head_count"] == 1, progressed

    incomplete_observation = json.loads(
        run_cli(
            "--format",
            "json",
            "pr-review",
            "--fixture",
            str(FIXTURE),
            "--state",
            "open",
            "--limit",
            "1",
            "--autonomous-observation",
        ).stdout
    )["autonomous_review"]
    assert incomplete_observation["observation_state"] == "not_observed", (
        incomplete_observation
    )
    assert incomplete_observation["candidate"] is None, incomplete_observation

    repository, fixture_prs = load_pr_fixture(FIXTURE)
    merged_fixture = next(item for item in fixture_prs if item.get("state") == "MERGED")
    busy_window = []
    for offset in range(105):
        item = dict(merged_fixture)
        item["number"] = 1000 + offset
        item["url"] = f"https://github.com/owner/repo/pull/{1000 + offset}"
        busy_window.append(item)
    truncated = build_pr_review_packet(
        pull_requests=busy_window,
        repository=repository,
        limit=100,
        source="fixture",
        state_filter="merged",
    )
    completeness = truncated["result_completeness"]
    assert completeness["complete"] is False, completeness
    assert completeness["groups"]["merged"] == {
        "complete": False,
        "observed_count": 105,
        "included_count": 100,
        "truncated": True,
    }, completeness
    assert completeness["recommended_limit"] >= 106, completeness
    assert truncated["review_groups"]["merged"]["truncated"] is True, truncated

    saturated_source = build_pr_review_packet(
        pull_requests=busy_window[:100],
        repository=repository,
        limit=100,
        source="github_cli",
        state_filter="merged",
        source_scan={
            "schema_version": "pr_review_source_scan_v0",
            "complete": False,
            "pull_requests": busy_window[:100],
            "states": [
                {
                    "state": "merged",
                    "fetch_limit": 100,
                    "fetched_count": 100,
                    "included_after_window": 100,
                    "source_saturated": True,
                    "source_read_valid": True,
                }
            ],
        },
    )
    saturated_completeness = saturated_source["result_completeness"]
    assert saturated_completeness["complete"] is False, saturated_completeness
    assert saturated_completeness["source_scan_complete"] is False, saturated_completeness
    assert saturated_completeness["observed_count_is_lower_bound"] is True, saturated_completeness
    assert "pull_requests" not in saturated_completeness["source_scan"], saturated_completeness
    assert saturated_completeness["recommended_limit"] == 200, saturated_completeness
    assert main_risk["verification_focus"], main_risk
    assert "quota.py" not in json.dumps(main_risk), main_risk
    response_contract = payload["agent_response_contract"]
    assert response_contract["schema_version"] == "pr_review_agent_response_contract_v0", response_contract
    assert response_contract["table_only_response_allowed"] is False, response_contract
    assert response_contract["slash_prefix_dominates_intent"] is True, response_contract
    assert response_contract["stats_only_requires_explicit_opt_out"] is True, response_contract
    assert response_contract["queue_table_role"] == "preface_only", response_contract
    assert response_contract["required_packet_fields_to_preserve"] == [
        "agent_response_contract",
        "agent_response_contract.review_execution_contract",
        "result_completeness",
        "review_groups",
        "pull_requests[].review_plan",
        "pull_requests[].review_template",
        "pull_requests[].evidence_commands",
    ], response_contract
    assert response_contract["required_final_sections"] == [
        "动机",
        "改动思路",
        "具体改动",
        "对主干的风险",
        "我的整体评价",
    ], response_contract
    depth = response_contract["explanation_depth_contract"]
    assert depth["schema_version"] == "pr_review_explanation_depth_v0", depth
    assert depth["authority"] == "agent_response_contract.review_execution_contract", depth
    assert "may not know" in depth["reader_profile"], depth
    execution = response_contract["review_execution_contract"]
    assert execution["schema_version"] == "pull_request_review_execution_contract_v1", execution
    requirements = {
        item["evidence_id"]: item for item in execution["evidence_requirements"]
    }
    assert set(requirements) == {
        "problem_context",
        "architecture_flow",
        "changed_line_classification",
        "symbol_map",
        "walkthroughs",
        "validation_matrix",
        "failure_analysis",
        "code_volume",
    }, requirements
    assert requirements["symbol_map"]["item_count"] == {"minimum": 2, "maximum": 5}
    assert "caller_evidence" in requirements["symbol_map"]["item_fields"]
    assert requirements["changed_line_classification"]["categories"] == [
        "production",
        "tests_or_fixtures",
        "docs",
        "generated",
        "mechanical_moves",
    ]
    assert "negative_fields" in requirements["walkthroughs"]
    assert "regression_test" in requirements["failure_analysis"]["fields"]
    assert requirements["code_volume"]["verdict_values"] == [
        "necessary",
        "partly_avoidable",
        "not_yet_proven",
    ]
    assert execution["completion_gate"]["metadata_only_verdict_allowed"] is False
    assert execution["completion_gate"]["stale_head_verdict_allowed"] is False
    assert execution["finding_contract"]["findings_first"] is True
    first_plan = first["review_plan"]
    assert first_plan["schema_version"] == "pull_request_review_plan_v1", first_plan
    assert first_plan["applicability"]["docs_only"] is True, first_plan
    assert first_plan["applicability"]["symbol_map_required"] is False, first_plan
    assert "symbol_map" not in first_plan["required_evidence_ids"], first_plan
    assert first_plan["result_template"]["target_exact_head"] == (
        "773@7730000000000000000000000000000000000000"
    ), first_plan
    merged = next(item for item in payload["pull_requests"] if item["number"] == 770)
    merged_plan = merged["review_plan"]
    assert merged_plan["applicability"]["code_change"] is True, merged_plan
    assert merged_plan["applicability"]["symbol_map_required"] is True, merged_plan
    assert merged_plan["applicability"]["negative_walkthrough_required"] is True, merged_plan
    assert "symbol_map" in merged_plan["required_evidence_ids"], merged_plan
    merged_risk_hint = merged["metadata_risk_hint"]
    assert merged_risk_hint["level"] == "medium", merged_risk_hint
    merged_main_risk = merged["main_regression_analysis"]
    assert merged_main_risk["risk_level"] == "high", merged_main_risk
    assert merged_main_risk["post_merge_review"] is True, merged_main_risk
    assert any("Runtime or CLI behavior" in item for item in merged_main_risk["potential_regressions"]), merged_main_risk
    assert payload["boundary"]["absolute_paths_recorded"] is False, payload["boundary"]
    assert_public_safe(payload)

    group_limited = json.loads(
        run_cli("--format", "json", "pr-review", "--fixture", str(FIXTURE), "--limit", "1").stdout
    )
    assert group_limited["summary"]["total_pr_count"] == 2, group_limited["summary"]
    assert group_limited["summary"]["open_pr_count"] == 1, group_limited["summary"]
    assert group_limited["summary"]["merged_pr_count"] == 1, group_limited["summary"]
    assert group_limited["review_groups"]["unmerged"]["pr_numbers"] == [773], group_limited[
        "review_groups"
    ]
    assert group_limited["review_groups"]["merged"]["pr_numbers"] == [770], group_limited[
        "review_groups"
    ]
    assert [item["number"] for item in group_limited["pull_requests"]] == [
        773,
        770,
    ], group_limited["pull_requests"]

    open_only = json.loads(
        run_cli(
            "--format",
            "json",
            "pr-review",
            "--fixture",
            str(FIXTURE),
            "--state",
            "open",
            "--limit",
            "5",
        ).stdout
    )
    assert open_only["summary"]["total_pr_count"] == 3, open_only["summary"]
    assert open_only["summary"]["merged_pr_count"] == 0, open_only["summary"]

    windowed = json.loads(
        run_cli(
            "--format",
            "json",
            "pr-review",
            "--fixture",
            str(FIXTURE),
            "--since",
            "2026-06-27T12:20:00Z",
            "--limit",
            "5",
        ).stdout
    )
    assert windowed["request"]["since"] == "2026-06-27T12:20:00Z", windowed["request"]
    assert windowed["summary"]["total_pr_count"] == 3, windowed["summary"]
    assert windowed["summary"]["open_pr_count"] == 2, windowed["summary"]
    assert windowed["summary"]["merged_pr_count"] == 1, windowed["summary"]
    assert any(item["number"] == 770 for item in windowed["review_sequence"]), windowed["review_sequence"]

    markdown = run_cli("pr-review", "--fixture", str(FIXTURE), "--limit", "1").stdout
    assert "# Project PR Review Queue" in markdown, markdown
    assert "current gh repository" not in markdown, markdown
    assert "state_filter: `all`" in markdown, markdown
    assert "merged=`" in markdown, markdown
    assert "tool contract: run `loopx pr-review` first" in markdown, markdown
    assert "final answer contract: queue/table is only a preface" in markdown, markdown
    assert "## Agent Output Contract" in markdown, markdown
    assert "Do not stop at the queue/table summary" in markdown, markdown
    assert "agent_response_contract.review_execution_contract" in markdown, markdown
    assert "review plan: exact_head=" in markdown, markdown
    assert "remote head SHA" in markdown, markdown
    assert "Required card headings: `动机`, `改动思路`, `具体改动`, `对主干的风险`, `我的整体评价`" in markdown, markdown
    assert "`关键代码讲解`" in markdown, markdown
    assert "## Unmerged PRs" in markdown, markdown
    assert "## Merged PRs" in markdown, markdown
    assert "#770" in markdown, markdown
    assert "## Combined Review Sequence" in markdown, markdown
    assert markdown.index("## Unmerged PRs") < markdown.index("## Merged PRs"), markdown
    assert "risk_hint=`low`" in markdown, markdown
    assert "template below is intentionally blank" in markdown, markdown
    assert "- 推荐阅读顺序:" in markdown, markdown
    assert "- 五块模板（留空给 agentloop 填写）:" in markdown, markdown
    assert "动机（200-350字）" in markdown, markdown
    assert "改动思路（300-500字）" in markdown, markdown
    assert "具体改动（450-800字）" in markdown, markdown
    assert "对主干的风险（250-500字）" in markdown, markdown
    assert "我的整体评价（150-300字）" in markdown, markdown
    assert "main regression risk:" not in markdown, markdown
    assert "## Combined Review Sequence" in markdown, markdown
    assert "PR #773" in markdown, markdown

    print("pr-review-command-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail

repository="${1:-}"
output_json="${2:-}"
count_output="${3:-}"

if [[ ! "$repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ || -z "$output_json" || -z "$count_output" ]]; then
  echo "usage: fetch-github-stargazers.sh OWNER/REPO OUTPUT_JSON COUNT_OUTPUT" >&2
  exit 2
fi
if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "::error title=Missing star-history credential::Set STAR_HISTORY_READ_TOKEN to a classic PAT from an admin/collaborator account with the public_repo scope." >&2
  exit 1
fi

owner="${repository%%/*}"
repo="${repository#*/}"
temp_root="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
pages_file="$(mktemp "$temp_root/loopx-stargazer-pages.XXXXXX.json")"
snapshot_file="$(mktemp "$temp_root/loopx-stargazers.XXXXXX.json")"
cleanup() {
  rm -f "$pages_file" "$snapshot_file"
}
trap cleanup EXIT

retry_delay="${LOOPX_STARGAZER_RETRY_DELAY_SECONDS:-5}"
for attempt in 1 2 3; do
  count_before="$(gh api "repos/$owner/$repo" --jq .stargazers_count)"
  gh api --paginate --slurp \
    -H "Accept: application/vnd.github.star+json" \
    "repos/$owner/$repo/stargazers?per_page=100" \
    > "$pages_file"
  jq '[.[][] | if (.starred_at | type) == "string" then {starred_at: .starred_at} else error("stargazer row is missing starred_at") end]' \
    "$pages_file" > "$snapshot_file"
  count_after="$(gh api "repos/$owner/$repo" --jq .stargazers_count)"
  fetched_count="$(jq 'length' "$snapshot_file")"
  if [[ ! "$count_before" =~ ^[0-9]+$ || ! "$count_after" =~ ^[0-9]+$ || ! "$fetched_count" =~ ^[0-9]+$ ]]; then
    echo "GitHub returned a non-numeric stargazer count" >&2
    exit 1
  fi

  if [[ "$count_before" == "$count_after" && "$fetched_count" -le "$count_after" ]]; then
    install -m 0644 "$snapshot_file" "$output_json"
    printf '%s\n' "$fetched_count" > "$count_output"
    if [[ "$fetched_count" != "$count_after" ]]; then
      echo "::warning title=Aggregate-only stargazers omitted::Fetched all $fetched_count enumerable stargazer events; GitHub reports $count_after aggregate stars." >&2
    fi
    exit 0
  fi

  if [[ "$attempt" == 3 ]]; then
    echo "stargazer snapshot changed or pagination was incomplete: before=$count_before fetched=$fetched_count after=$count_after" >&2
    exit 1
  fi
  sleep "$retry_delay"
done

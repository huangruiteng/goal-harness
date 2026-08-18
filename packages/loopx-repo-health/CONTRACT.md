# Repo-Health Provider Contract

`repo_health_snapshot_v0` is a provider-neutral, public-safe snapshot of GitHub
repository health. The provider collects typed observations from the GitHub
REST API and freezes them into one document; consumers (monthly reports,
community-funnel monitors, content material) render or aggregate the snapshot
but do not reinterpret missing metrics as zero.

## Ownership

| Surface | Owner | Responsibility |
| --- | --- | --- |
| Contract | `loopx-repo-health` extension | Schema, frozen metric ids, boundary rules |
| Observation | GitHub REST collector | Public evidence with typed values or `null` |
| Rendering | `loopx-repo-health` | Deterministic markdown projection |
| Revision | Human owner | Approval before metric semantics change |

## Rules

- All metric values are non-negative integers or `null`; a failed collection is
  represented as a warning plus `null`, never a fabricated number.
- `latency.pr_merge_*` and `latency.first_response_*` are bounded samples; the
  evidence `warnings` list names the sample size.
- `traffic_14d` requires repository access; unavailable surfaces become zero
  counts with a warning, so consumers can distinguish "no traffic" from
  "no access".
- `traffic_14d.paths` is the bounded top-paths list returned by GitHub
  (`traffic/popular/paths`). `traffic_14d.docs_views` is derived from those
  paths with the single classification rule: README (`/readme...`),
  `docs/` tree (including blob/tree links), and `wiki/` tree. The derived
  `uniques` value is the sum of per-path uniques and is not de-duplicated
  across paths.
- Credentials are never part of the request or response packet; authentication
  comes from the process environment only.
- The provider rejects a request with a mismatched `schema_version` before
  doing any network work.

## Evidence

Each snapshot carries `evidence.sources`, `evidence.rate_limit_remaining`, and
`evidence.warnings` so downstream reports can audit freshness and sampling.

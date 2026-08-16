# loopx-repo-health

Public-safe GitHub repo-health snapshot provider for LoopX. It collects a
bounded set of public repository metrics from the GitHub REST API and emits a
frozen `repo_health_snapshot_v0` document that can feed monthly reports,
community-funnel monitoring, and content material.

## Metrics

- Counts: stars, forks, watchers, open issues, releases, contributors, sampled
  PR total, sampled commented-issue total.
- Traffic (14-day window): views and clones (requires repository access).
- Latency: PR merge p25/p75 and first-human-response p25/p75, computed from a
  bounded recent sample.
- Recent star timeline: weekly buckets from the newest stargazer pages.

Every metric comes from public repository data. The provider never accepts or
emits raw trajectories, benchmark evidence, credentials, or private links.

## Auth and boundaries

- Read `GH_TOKEN` or `GITHUB_TOKEN` from the environment; the request packet
  never carries credentials.
- Unauthenticated requests still work for most endpoints, but GitHub now
  requires authentication for the stargazers list, so a token is recommended.
- Rate limits are GitHub's; the collector reports `rate_limit_remaining` in
  evidence and fails fast with an explicit error instead of guessing.
- Latency metrics are samples, not full-history percentiles; the snapshot
  records the sample size in `evidence.warnings`.

## Usage

Managed extension invocation (stdin request → stdout response):

```bash
python3 -m pip install .
loopx extension install --manifest extension.toml --execute --format json
loopx extension run loopx-repo-health --input-json examples/request.json --execute --format json
```

Direct CLI:

```bash
loopx-repo-health --doctor
loopx-repo-health snapshot --owner huangruiteng --repo loopx --format json
loopx-repo-health snapshot --owner huangruiteng --repo loopx --format md
```

`schemas/request.schema.json` and `schemas/response.schema.json` are the
versioned wire contracts. The provider validates its output against
`repo_health_snapshot_v0` before returning it.

## Validation

```bash
python3 smoke/repo_health_snapshot_smoke.py            # offline contract smoke
python3 smoke/repo_health_snapshot_smoke.py --live owner repo   # optional live check
```

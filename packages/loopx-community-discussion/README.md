# loopx-community-discussion

Public-safe community discussion scanner for LoopX. It collects compact
`discussion_fact_v0` facts from public sources — GitHub issues and discussions
plus exact-match Hacker News Algolia — and freezes them into a
`community_discussion_scan_v0` document that can feed periodic reports,
community funnel monitoring, or an operator digest.

## Facts

- GitHub: recent issues in `owner/repo` (internal `[Task]`-style entries
  filtered) and the 50 most recently updated discussions. Maintainer-authored
  items are typed `maintainer_signal`; everyone else is
  `external_discussion`.
- Hacker News: exact `loopx` stories plus `loop engineering` ecosystem
  articles. Typo tolerance is disabled and an exact substring match is
  required, because Algolia's default fuzzy search returns thousands of
  unrelated Loopxo/Looptap/looped-music/CrowdStrike hits.

The provider is metadata-first: title, source URL, author, timestamp,
relevance, and a dedupe key. It never stores raw provider payloads, full post
bodies, credentials, local paths, or private context.

## Auth and boundaries

- Read `GH_TOKEN` or `GITHUB_TOKEN` from the environment for GitHub
  Discussions collection and higher rate limits; the request packet never
  carries credentials.
- Hacker News Algolia is unauthenticated.
- X and Reddit are not bundled. X requires a logged-in browser session (for
  example ego-browser) or the official XMCP provider, and Reddit's public JSON
  endpoints currently return a login wall / rate limit. Both stay exact-gated
  external providers behind the same `discussion_fact_v0` contract.
- This extension performs no external writes. Sending a digest (for example to
  Lark) is a separate, exactly gated delivery step owned by the operator.

## Usage

Managed extension invocation (stdin request → stdout response):

```bash
python3 -m pip install .
loopx extension install --manifest extension.toml --execute --format json
loopx extension run loopx-community-discussion --input-json examples/request.json --execute --format json
```

Direct CLI:

```bash
loopx-community-discussion --doctor
loopx-community-discussion scan --owner huangruiteng --repo loopx --days 14 --format json
loopx-community-discussion scan --owner huangruiteng --repo loopx --days 14 --format md
```

`schemas/fact.schema.json`, `schemas/scan.schema.json`, and the request/response
schemas are the versioned wire contracts. The provider validates its output
against `community_discussion_scan_v0` before returning it.

## Validation

```bash
python3 smoke/community_discussion_smoke.py                     # offline contract smoke
python3 smoke/community_discussion_smoke.py --live owner repo   # optional live check
```

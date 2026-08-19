# Community Discussion Provider Contract

`community_discussion_scan_v0` is a provider-neutral, public-safe snapshot of
recent community discussion around a repository. Collectors emit typed
`discussion_fact_v0` facts; consumers (periodic reports, community funnels,
operator digests) render or aggregate facts but do not reinterpret missing
providers as silence.

## Ownership

| Surface | Owner | Responsibility |
| --- | --- | --- |
| Contract | `loopx-community-discussion` extension | Schema, fact types, boundary rules |
| Observation | GitHub REST/GraphQL + HN Algolia collectors | Public evidence with typed values or warnings |
| Rendering | `loopx-community-discussion` | Deterministic markdown digest |
| Delivery | Operator | Exact-gated external writes (Lark etc.) are never performed by this extension |

## Rules

- Facts are metadata-first: title, source URL, author, published timestamp,
  relevance, and a `dedupe_key`. Raw provider payloads and full post bodies are
  never stored.
- A failed provider is represented as an `evidence.warnings` entry plus the
  surviving facts, never as fabricated facts.
- GitHub internal `[Task]`/`[Benchmark]`/`[Sweep]`/`[Chore]` issues are
  filtered as non-community signals.
- Maintainer-authored items are typed `maintainer_signal`; other authors are
  `external_discussion`, so digests can prioritize user voices.
- Public recommendations from projects and public adoption declarations from
  organizations are typed `adoption_declaration`. They are the highest-bar
  adoption evidence (someone self-identifies as a user and advocates
  publicly); digests must rank them above passive signals and ordinary
  discussion.
- HN collection disables typo tolerance and requires exact substring matches
  to keep the well-known Loopxo/Looptap/looped-music/CrowdStrike noise out.
- Credentials are never part of a request or response packet; GitHub
  authentication comes from the process environment only.
- The provider rejects a request with a mismatched `schema_version` before
  doing any network work.

## Evidence

Each scan carries `evidence.sources`, `evidence.rate_limit_remaining`, and
`evidence.warnings` so downstream reports can audit freshness and partial
provider availability.

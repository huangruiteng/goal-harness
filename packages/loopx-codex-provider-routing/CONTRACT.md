# Contract And Authority Boundary

Protocol: `loopx_codex_provider_routing_extension_v0`

Request: `loopx_codex_provider_routing_request_v0`

Response: `loopx_codex_provider_routing_response_v0`

Catalog: `codex_provider_routing_catalog_v1`

The provider accepts exactly one public-safe operation per invocation and
returns a deterministic JSON result. An input containing credential-shaped
keys fails before any operation runs.

The provider has no Kernel transition authority and no external write
permission. A qualification result is evidence, not permission to edit a
Codex home, install CPA, change a model, start a turn, rotate a credential or
merge an upstream PR.

The catalog defines one bounded account ring, not one ring per visible route.
Auto and Luna enter the same ring through affinity (or its first member for a
cold task); Prefer A and Prefer B select different entry points. The ring is
traversed at most once. A route may then append a terminal fallback tail, but
the tail is not a ring member and is never revisited. Explicit Ark remains a
manual hard pin.

Resilient routes apply two admission filters before ring traversal and
affinity:

1. every candidate must support all modalities required by the complete
   request history;
2. when Fast is selected, every candidate must support the requested service
   tier.

Affinity can reorder only the remaining eligible ring members. If none remain,
the route fails closed before the first visible output or tool call. A
text-only fallback can therefore serve text Auto requests but cannot receive
image history. Luna has no heterogeneous fallback tail.

Codex App settings use the same evidence rule. A selector label is not proof
that a running turn adopted the new model. Qualification requires a durable
settings revision and a turn receipt that matches it. The content-free runtime
snapshot must also report each resilient route's entry point, ordered
candidates, terminal tail and maximum cycle count; catalog compilation alone
cannot qualify a deployment.

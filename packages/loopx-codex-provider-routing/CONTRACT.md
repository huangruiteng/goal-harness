# Contract And Authority Boundary

Protocol: `loopx_codex_provider_routing_extension_v0`

Request: `loopx_codex_provider_routing_request_v0`

Response: `loopx_codex_provider_routing_response_v0`

Catalog: `codex_provider_routing_catalog_v1`

Runtime status: `codex_provider_routing_runtime_status_v0`

Integration candidate: `codex_provider_integration_candidate_v0`

Heartbeat transport qualification: `codex_app_heartbeat_transport_qualification_v0`

Desktop patch qualification: `codex_desktop_patch_qualification_v0`

Quota recovery qualification: `codex_quota_recovery_qualification_v0`

Tool transport qualification: `codex_tool_transport_qualification_v0`

The provider accepts exactly one public-safe operation per invocation and
returns a deterministic JSON result. An input containing credential-shaped
keys fails before any operation runs.

The provider has no Kernel transition authority and no external write
permission. A qualification result is evidence, not permission to edit a
Codex home, install CPA, change a model, start a turn, rotate a credential or
merge an upstream PR.

Heartbeat qualification accepts only symbolic, content-free shape facts. For
an `automation_heartbeat` carrying a `heartbeat_xml` envelope, the conforming
delivery is `user_input` with `message_role=user`. A `tool_output` observation
is non-conforming because it changes the semantic role of the scheduler event;
the provider reports a stable failure code and never recommends prompt or model
tuning as remediation. App inspection, binary changes and process lifecycle
remain outside this read-only extension.

The integration-candidate operation composes with, but does not replace,
LoopX core `integration-branch`. It accepts only public Git refs, full commit
SHAs, symbolic source IDs, source kinds and changed-seam labels. The caller
must supply both current observations and the last successful sync receipt.
Every observed source head must equal its declared exact head, and the ordered
source set must cover every required seam. Base movement, source movement or an
unexpected integration head produces `sync_required`; no Git effect is run.

After a separately authorized core sync, deployment remains operator-owned.
The returned contract requires a content-addressed binary, isolated smoke,
field-level configuration comparison, catalog/retry/runtime readback and a
retained previous binary/config pointer. Task/session stores are preserved in
place and are never copied or deleted as part of candidate maintenance.

Runtime status deliberately has two projections. `host_identity` records only
that the operator's ChatGPT identity is retained but is not projected by the
custom provider; its `route_binding` is always `none`. `route_intent` and
`execution` separately report the requested logical route and the symbolic
provider profiles actually attempted by CPA. A direct Auto hit on B is not a
fallback; fallback is true only after a second candidate was attempted.
`route_intent.fast` is derived from the selected `fast/` route slug. A caller
may include a redundant boolean only when it agrees with that slug.

Account observations may contain symbolic catalog profile IDs, readiness,
bounded success/failure counters and percentage quota windows. The provider
derives `remaining_percent`. Email addresses, auth IDs/files, credentials,
private paths, task IDs and request content are forbidden at the public
boundary.

The catalog defines one bounded account ring, not one ring per visible route.
Auto and Luna enter the same ring through affinity (or its first member for a
cold task); Prefer A and Prefer B select different entry points. The ring is
traversed at most once. A route may then append a terminal fallback tail, but
the tail is not a ring member and is never revisited. Explicit Ark remains a
manual hard pin.

Resilient routes apply baseline admission filters before ring traversal and
affinity:

1. every candidate must support all modalities required by the complete
   request history;
2. when Fast is selected, every candidate must support the requested service
   tier.

A third filter applies when the host requires a specific tool item transport.
Every profile that omits `tool_transports`, including a legacy native Codex
profile, defaults conservatively to `function_call` only. An adapter may declare
`custom_tool_call` only after it has proved that it preserves the raw payload
and item type. A Code Mode request requiring `custom_tool_call` therefore cannot
silently fall through to an unqualified or function-only provider. The separate
qualification operation compares requested and observed item types and requires
completed dispatch.

Affinity can reorder only the remaining eligible ring members. If none remain,
the route fails closed before the first visible output or tool call. A
text-only fallback can therefore serve text Auto requests but cannot receive
image history. Luna has no heterogeneous fallback tail.

Fast is modeled as a selector projection over an existing route. A route may
declare one `fast_selector`; the compiler emits `fast/<route>`, filters its
candidates to Fast-capable profiles and marks its default tier as `fast`.
`normalize_selector_request` consumes only the original selector and optional
service tier: Fast rows resolve to the underlying route and force the wire tier
to `priority`, while ordinary rows preserve the request. A preserved
`priority` tier is nevertheless treated as effective Fast state for candidate
admission, so both the explicit sibling row and the native Fast entry are
limited to Fast-capable providers. It never accepts a prompt or request body.
A Fast request cannot fall through to a provider that does not support Fast.

An applied quota reset is ordered against the observation that created a
provider cooldown. When the reset is newer, the old cooldown is stale: CPA must
invalidate it and probe that account before selecting a fallback. A fresh probe
may either succeed or return a new quota limit; only the latter permits a new
cooldown and fallback. This contract prevents a reset account from remaining
unreachable until an obsolete expiry.

Patched desktop builds have a separate post-build gate. The patch anchor must
be unique for the current build, every changed ASAR member must have matching
per-file integrity, the resulting ASAR header digest must match bundle
metadata, the runtime must be signed and launch, and the patched heartbeat path
must pass readback. Whole-archive hashing is not a substitute for Electron's
header and per-file checks. The provider consumes only booleans and counts;
bundle mutation and signing remain operator effects.

Codex App settings use the same evidence rule. A selector label is not proof
that a running turn adopted the new model. Qualification requires a durable
settings revision and a turn receipt that matches it. The content-free runtime
snapshot must also report each resilient route's entry point, ordered
candidates, terminal tail and maximum cycle count; catalog compilation alone
cannot qualify a deployment.

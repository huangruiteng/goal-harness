# Operator Script And Configuration Migration

This inventory records how the working operator prototype maps into the
public extension. It names responsibilities, not local paths, host identities,
ports, accounts or private receipts.

## Script Inventory

| Prototype responsibility | Disposition | Public owner |
| --- | --- | --- |
| Compile secret-free profiles, one-pass account rings and logical model routes | Migrated and strengthened | `contract.py::compile_catalog`; preferred entry points, terminal fallback tails, modality and Fast eligibility are explicit |
| Generate explicit Fast sibling rows and inject the Fast request tier | Migrated as a public-safe compiler/normalizer contract | `contract.py::compile_catalog` plus `normalize_selector_request`; the live CPA adapter/plugin enforces the same decision before alias mapping |
| Project host identity separately from actual account routing and quota | Migrated | `operator_observations.py` reduces local observations; `contract.py::project_runtime_status` retains the public boundary |
| Generate a Codex catalog from cached model entries, start an isolated App Server, call `model/list` | Migrated | `operator_catalog.py` uses explicit cache/binary references; `selectors.py` shares the existing ring compiler |
| Verify a patched desktop runtime across versioned anchors, ASAR member/header integrity, signature, launch and heartbeat readback | Migrated as a read-only qualification | `qualify_desktop_patch`; patching, signing and process lifecycle remain operator-owned effects |
| Invalidate a provider cooldown after a newer successful quota reset | Migrated as a recovery ordering contract | `qualify_quota_recovery`; CPA owns the live invalidation and bounded reprobe |
| Invalidate incident cooldown and revalidate degraded fallback affinity after a provider-wide outage ends | Migrated as a recovery ordering contract | `qualify_outage_recovery`; CPA owns the live invalidation, bounded probe and binding revalidation |
| Preserve Code Mode tool item shape across heterogeneous fallback | Migrated as admission plus qualification | profile `tool_transports`, `normalize_selector_request` and `qualify_tool_transport`; adapters must prove custom-item preservation before declaring support |
| Reconcile an ordered multi-PR candidate against exact heads and required seams | Migrated as a public-safe planning contract | `reconcile_integration_candidate` returns core `integration-branch` inputs; Git effects remain outside the extension |
| Prepare/start/serve/stop CPA; reconcile OAuth slots; load referenced credentials | Migrated as an explicit local CLI | `operator.py`, `operator_runtime.py` and `operator_settings.py`; private configuration and credentials remain outside Git and the read-only extension protocol |
| Snapshot App/selector configuration, validate hashes and roll back selected files | Planning contract migrated | `upgrade_plan` owns order, matrix and rollback trigger; filesystem effects need a future request-bound execution envelope |
| Scan local config/auth files for secret patterns | Split | `reject_private_material` protects extension input/output; scanning owner-local files remains an operator preflight |
| Emit failover evidence rows | Replaced | `upgrade_plan.required_checks` and `qualify_snapshot.checks` are the public evidence vocabulary; raw evidence directories are excluded |
| Read CC Switch SQLite and enable its failover toggle | Retired | CPA is the only online data plane; CC Switch remains bootstrap/rollback and must not regain routing authority |
| Python routing, transaction, outbox and turn-lease simulators | Reference-only prototypes | Stable rules moved into the runbook, contract and CPA upstream tests; LoopX does not ship a second router implementation |
| Provider history and SSE normalizer prototypes | Upstreamed, not duplicated | CLIProxyAPI PR #5410 supersedes closed PR #5220 as the implementation owner |
| uTLS connection experiments | Upstreamed, not duplicated | CLIProxyAPI PR #5261 is the implementation owner |
| Route-specific fallback ring | Upstreamed, not duplicated | CLIProxyAPI PR #5336 is the implementation owner |
| OpenAI-compatible bounded rate-limit waits | Upstreamed, not duplicated | CLIProxyAPI PR #5435 propagates `Retry-After`, uses a one-minute fallback only for explicit TPM limits, and leaves generic 429 behavior unchanged |
| Delimiterless compatible SSE and recoverable orphan host outputs | Integrated public-safe patch, not duplicated | The CPA integration candidate removes host tool identity but retypes confirmed orphan control output as a user message; qualification must prove instruction follow-through, while unknown, paired and empty outputs remain typed failures |

## Configuration References

The package keeps credential-free examples for every operation, including:

- [`examples/request.json`](examples/request.json): logical profiles and model
  routes backed by one bounded account ring for `compile_catalog`;
- [`examples/normalize-request.json`](examples/normalize-request.json): one
  Fast selector normalization that forces `priority` without accepting a body;
- [`examples/runtime-status.json`](examples/runtime-status.json): dual host and
  route identity projection with symbolic quota/activity observations;
- [`examples/qualification-snapshot.json`](examples/qualification-snapshot.json):
  content-free App/CPA readback for `qualify_snapshot`;
- [`examples/upgrade-request.json`](examples/upgrade-request.json): exact public
  refs and changed seams for `upgrade_plan`.
- [`examples/integration-candidate.json`](examples/integration-candidate.json):
  ordered source refs, exact heads, required seams and last-sync observations
  for `reconcile_integration_candidate`.
- [`examples/desktop-patch.json`](examples/desktop-patch.json): post-build ASAR,
  signature, launch and heartbeat qualification;
- [`examples/quota-recovery.json`](examples/quota-recovery.json): reset/cooldown
  ordering with bounded reprobe;
- [`examples/outage-recovery.json`](examples/outage-recovery.json): incident-end
  ordering with stale cooldown invalidation, bounded probe and affinity revalidation;
- [`examples/tool-transport.json`](examples/tool-transport.json): requested and
  observed tool item transport plus dispatch outcome.

[`templates/codex-app-config.toml`](templates/codex-app-config.toml) and
[`templates/cpa-config.public.yaml`](templates/cpa-config.public.yaml) preserve
the working field shape and retry/Fast defaults. The App keeps its 30/30 outer
recovery budget, while the OpenAI-compatible text fallback gets one additional
provider round and a 65-second cooldown ceiling. They contain placeholders and
omit all credential-bearing CPA sections. The extension never fills those
placeholders or writes the templates into a Codex home.

## Local operator promotion

The effectful adapter is now the optional [local operator](OPERATOR.md), invoked
separately with an explicit private configuration and per-command `--execute`.
The managed extension remains read-only. Fixed target allowlists, dry-run
receipts, snapshots, integrity checks and isolated regression tests accompany
the promotion. Host credentials, artifact pins, service-manager files and
private evidence remain operator-owned; no local prototype path is shipped.

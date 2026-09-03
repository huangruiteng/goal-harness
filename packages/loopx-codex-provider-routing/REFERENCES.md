# Operator Script And Configuration Migration

This inventory records how the working operator prototype maps into the
public extension. It names responsibilities, not local paths, host identities,
ports, accounts or private receipts.

## Script Inventory

| Prototype responsibility | Disposition | Public owner |
| --- | --- | --- |
| Compile secret-free profiles, one-pass account rings and logical model routes | Migrated and strengthened | `contract.py::compile_catalog`; preferred entry points, terminal fallback tails, modality and Fast eligibility are explicit |
| Generate explicit Fast sibling rows and inject the Fast request tier | Migrated as a public-safe compiler/normalizer contract | `contract.py::compile_catalog` plus `normalize_selector_request`; the live CPA adapter/plugin enforces the same decision before alias mapping |
| Project host identity separately from actual A/B routing and quota | Migrated as a public-safe adapter boundary | `contract.py::project_runtime_status`; raw CPA management responses and logs remain operator-local |
| Generate a Codex catalog from cached model entries, start an isolated App Server, call `model/list` | Partially migrated | Catalog contract and content-free readback assertions are public; spawning the host-owned App Server remains an operator adapter |
| Reconcile an ordered multi-PR candidate against exact heads and required seams | Migrated as a public-safe planning contract | `reconcile_integration_candidate` returns core `integration-branch` inputs; Git effects remain outside the extension |
| Prepare/start/serve/stop CPA; reconcile A/B OAuth slots; load third-party API credentials | Private runtime boundary | Not copied. A future permissioned provider may wrap install/status/validate, but login and secret loading stay operator-owned |
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

The package keeps six credential-free examples:

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

[`templates/codex-app-config.toml`](templates/codex-app-config.toml) and
[`templates/cpa-config.public.yaml`](templates/cpa-config.public.yaml) preserve
the working field shape and retry/Fast defaults. The App keeps its 30/30 outer
recovery budget, while the OpenAI-compatible text fallback gets one additional
provider round and a 65-second cooldown ceiling. They contain placeholders and
omit all credential-bearing CPA sections. The extension never fills those
placeholders or writes the templates into a Codex home.

## Future Promotion Gate

An effectful operator adapter can move into this extension only after it has:

1. a request-bound execution envelope with explicit local-write scope;
2. dry-run and readback receipts for every file/process change;
3. exact target allowlists instead of broad home-directory access;
4. secret references that are never returned or copied into LoopX state;
5. idempotent install/upgrade/rollback tests in an isolated temporary home;
6. a stop condition that never deletes a task store or rewrites rollout/SQLite
   history.

Until then, the public extension remains read-only and the private runtime
adapter remains the owner of live effects.

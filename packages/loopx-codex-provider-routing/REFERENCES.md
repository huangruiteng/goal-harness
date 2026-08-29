# Operator Script And Configuration Migration

This inventory records how the working operator prototype maps into the
public extension. It names responsibilities, not local paths, host identities,
ports, accounts or private receipts.

## Script Inventory

| Prototype responsibility | Disposition | Public owner |
| --- | --- | --- |
| Compile secret-free profiles, one-pass account rings and logical model routes | Migrated and strengthened | `contract.py::compile_catalog`; preferred entry points, terminal fallback tails, modality and Fast eligibility are explicit |
| Generate a Codex catalog from cached model entries, start an isolated App Server, call `model/list` | Partially migrated | Catalog contract and content-free readback assertions are public; spawning the host-owned App Server remains an operator adapter |
| Prepare/start/serve/stop CPA; reconcile A/B OAuth slots; load third-party API credentials | Private runtime boundary | Not copied. A future permissioned provider may wrap install/status/validate, but login and secret loading stay operator-owned |
| Snapshot App/selector configuration, validate hashes and roll back selected files | Planning contract migrated | `upgrade_plan` owns order, matrix and rollback trigger; filesystem effects need a future request-bound execution envelope |
| Scan local config/auth files for secret patterns | Split | `reject_private_material` protects extension input/output; scanning owner-local files remains an operator preflight |
| Emit failover evidence rows | Replaced | `upgrade_plan.required_checks` and `qualify_snapshot.checks` are the public evidence vocabulary; raw evidence directories are excluded |
| Read CC Switch SQLite and enable its failover toggle | Retired | CPA is the only online data plane; CC Switch remains bootstrap/rollback and must not regain routing authority |
| Python routing, transaction, outbox and turn-lease simulators | Reference-only prototypes | Stable rules moved into the runbook, contract and CPA upstream tests; LoopX does not ship a second router implementation |
| Provider history and SSE normalizer prototypes | Upstreamed, not duplicated | CLIProxyAPI PR #5220 is the implementation owner |
| uTLS connection experiments | Upstreamed, not duplicated | CLIProxyAPI PR #5261 is the implementation owner |

## Configuration References

The package keeps three credential-free examples:

- [`examples/request.json`](examples/request.json): logical profiles and model
  routes backed by one bounded account ring for `compile_catalog`;
- [`examples/qualification-snapshot.json`](examples/qualification-snapshot.json):
  content-free App/CPA readback for `qualify_snapshot`;
- [`examples/upgrade-request.json`](examples/upgrade-request.json): exact public
  refs and changed seams for `upgrade_plan`.

[`templates/codex-app-config.toml`](templates/codex-app-config.toml) and
[`templates/cpa-config.public.yaml`](templates/cpa-config.public.yaml) preserve
the working field shape and retry/Fast defaults. They contain placeholders and
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

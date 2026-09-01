# LoopX Codex Provider Routing

This optional LoopX extension owns the public-safe integration contract for a
single Codex App using CPA as its multi-subscription and multi-provider data
plane. It packages configuration compilation, qualification readback and
upgrade planning without becoming a model proxy or credential authority.

## Placement

This package is an **extension** that supplies a standalone integration
provider. It is not a built-in capability:

- Codex App owns task settings, turn snapshots and the session store;
- CPA owns credential selection, online routing, retry and stream adaptation;
- the operator owns OAuth/API credentials, process installation and private
  build/rollback receipts;
- LoopX owns this versioned public contract, managed extension lifecycle,
  public-safe qualification results and upgrade gates.

The extension declares no permissions and performs no writes. It does not read
`HOME`, `CODEX_HOME`, auth files, process tables or network endpoints. Callers
must convert local observations into the content-free snapshot schema before
qualification.

## Operations

`compile_catalog`
: Compiles secret-free logical profiles and routes into
  `codex_provider_routing_catalog_v1`. One bounded account ring can back Auto,
  Prefer A, Prefer B and Luna without presenting separate rings to the user.
  Route affinity is only a hint and must be revalidated against required input
  modalities and service tier on every attempt. A terminal text-only fallback
  can serve compatible Sol requests but cannot receive image history; Luna has
  no heterogeneous fallback tail.

`qualify_snapshot`
: Checks the content-free App/CPA readback: visible and hidden routes, input
  modalities, Fast projection with default-off semantics, loopback binding,
  modality-aware affinity, typed route traversal, durable settings revision
  and commit barrier.

`upgrade_plan`
: Produces a bounded upgrade/rollback checklist from public current and target
  refs plus the changed seams. It never installs, switches or deletes a
  runtime.

## Managed Usage

Run these commands from the same activated Python environment:

```bash
python3 -m pip install packages/loopx-codex-provider-routing
loopx extension install \
  --manifest packages/loopx-codex-provider-routing/extension.toml \
  --execute \
  --format json
loopx extension doctor loopx-codex-provider-routing --execute --format json
loopx extension run loopx-codex-provider-routing \
  --input-json packages/loopx-codex-provider-routing/examples/request.json \
  --execute \
  --format json
```

The extension runtime owns install/enable/disable/doctor registration. Package
installation remains an explicit package-manager action; neither operation
downloads CPA or grants credentials.

## Script Migration Boundary

The earlier operator scripts split into three classes:

| Script responsibility | Extension ownership |
| --- | --- |
| Secret-free profile/catalog compiler | Migrated into `compile_catalog` and strengthened with modality/service-tier eligibility |
| App/CPA model readback assertions | Migrated as the content-free `qualify_snapshot` contract |
| Upgrade matrix, snapshot order and rollback triggers | Migrated as `upgrade_plan`; effect execution remains operator-owned |
| CPA process launcher, OAuth login/reconcile, Ark key loading | Excluded; these are provider runtime and credential lifecycle, not LoopX state |
| Direct App config writes, private snapshots and rollback copies | Excluded from v0; require an explicit permissioned execution envelope before productization |
| Raw log/evidence collection | Excluded; callers may submit only content-free error classes and qualification booleans |

The complete responsibility-by-responsibility mapping and credential-free
configuration references are in [`REFERENCES.md`](REFERENCES.md).

The canonical architecture, qualification matrix and public PR lineage are in
[`RUNBOOK.md`](RUNBOOK.md). Reliable SSH egress remains a shared LoopX
integration because it is useful beyond CPA.

## Validation

```bash
python3 packages/loopx-codex-provider-routing/smoke/codex_provider_routing_smoke.py
python3 -m pytest -q tests/extensions/test_colocated_extension_layout.py
loopx check --scan-path packages/loopx-codex-provider-routing
```

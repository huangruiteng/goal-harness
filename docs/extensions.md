# Extensions And Capabilities

Capabilities and extensions are independent dimensions in LoopX:

- a **capability** describes what LoopX can do and the product contract exposed
  to callers;
- an **extension** is a delivery unit that can provide one or more capabilities
  and has its own installation, enablement, disablement, and upgrade lifecycle.

Built-in capabilities and extension-provided capabilities share one registry.
Implementation directories do not become capabilities merely because they live
under `loopx/capabilities/`; registration is explicit.

```text
LoopX Core
|-- capability contracts
|-- built-in capability registrations
`-- extension runtime
      |-- extension A -- provides capabilities
      |-- extension B -- provides capabilities
      `-- extension C -- provides capabilities
```

## Registration Model

Every registered capability declares three provider-facing fields:

- `origin`: `builtin` or `extension`;
- `visibility`: `public` or `internal`;
- `provider_id`: `loopx-core` or the extension manifest id.

The built-in catalog remains the default source. Explicitly enabled extension
manifests are validated and appended in caller order. Duplicate capability or
provider ids fail closed. Internal registrations remain available to the
registry but are omitted from the public catalog.

The initial runtime does not scan arbitrary directories and does not import
extension Python code while reading the catalog. A caller enables a manifest
for one catalog operation explicitly:

```bash
loopx capability list \
  --extension-manifest /path/to/extension.toml \
  --format json

loopx capability show lark-kanban \
  --extension-manifest /path/to/extension.toml \
  --format json
```

This explicit read path establishes the registration contract without
prematurely defining an installer, package repository, or global activation
store. Those lifecycle surfaces can later provide the same validated manifest
paths to the registry.

## Placement Decision For Agents

Before creating a directory, LoopX or an executing agent must answer these
questions in order:

1. **What user outcome and caller-visible contract is being added or changed?**
   Capability ids describe outcomes, not transports. Names such as
   `connector`, `provider`, `adapter`, or `sink` usually describe an extension
   or internal mechanism unless callers use and validate that mechanism as an
   independent product contract. If an existing
   capability already owns that contract, add the implementation to
   `loopx/capabilities/<existing-capability>/` instead of creating a sibling.
2. **Must LoopX core always ship and maintain the implementation?** If yes, it
   may be a built-in capability. A new built-in needs a stable id, a real
   entrypoint or protocol call site, focused validation, and catalog
   registration.
3. **Does the implementation need independent installation, enablement,
   disablement, upgrade, dependencies, credentials, or provider ownership?**
   If yes, it is an extension provider. The capability remains the contract;
   the extension manifest declares that it provides the contract.
4. **Is this only registration or lifecycle machinery shared by all
   extensions?** Put that mechanism in `loopx/extensions/`, not in a provider
   package.
5. **Is this only an internal helper?** Put it in the nearest module that owns
   its change reason. Do not register a capability or create an extension.

Use this placement map after answering the questions:

| Change | Placement |
| --- | --- |
| Existing built-in capability behavior | `loopx/capabilities/<capability-id>/` |
| Built-in catalog and registration contract | `loopx/capabilities/catalog.py` or `registry.py` |
| Generic extension runtime | `loopx/extensions/` |
| Co-located optional provider | `extensions/<extension-id>/` |
| Separately distributed provider | provider-owned package or repository |
| Internal implementation helper | nearest owning module |

Some work belongs on both axes. Finance research should expose the outcome
capability `finance-value-discovery`; public-market, filing, and news sources
can be extension providers of that capability. Shared connector intent,
permission, and approval logic is internal runtime machinery, not another
public capability. The extension directory owns delivery and lifecycle;
capability registration owns the caller-visible promise.

`value-connectors` is an existing compatibility CLI and protocol surface. Do
not use it as the public capability owner for new work. Migrate each profile to
the outcome capability it serves, such as `finance-value-discovery`,
`issue-fix`, or `content-ops`, before retiring the compatibility surface. This
keeps the migration behavior-preserving instead of replacing one broad bucket
with another broad bucket.

Before editing, record a compact rationale in the active todo or plan:

```text
capability_id: <existing-or-new-contract>
provider_id: loopx-core | <extension-id>
origin: builtin | extension
placement: <target-directory-or-package>
reason: <why the nearest existing owner is or is not sufficient>
```

Do not create a new capability directory merely because no current directory
has the feature name. Do not create an extension merely because an external
service is involved: a built-in connector can still belong to an existing
capability when it shares the core release and lifecycle.

## Manifest Contract

An extension manifest is declarative TOML. `[[provides]]` records carry enough
metadata to enter the capability catalog without loading provider code.
The v0 runtime exposes integer extension API version `1` and accepts bounded
integer constraints such as `>=1,<2`; incompatible manifests fail closed.

```toml
schema_version = "loopx_extension_manifest_v0"
id = "loopx-lark"
version = "1.0.0"
requires_loopx_api = ">=1,<2"
permissions = ["read_status", "read_todos", "external_write"]

[[provides]]
id = "lark-kanban"
kind = "projection_sink"
title = "Lark Kanban projection"
status = "active"
visibility = "public"
real_world_anchor = "operator-facing Lark Base projection"
user_value = "Project public-safe LoopX status and todo rows into Lark."
entry_command = "loopx lark-kanban sync"
next_real_step = "Validate one explicitly enabled owner-approved sink."
```

`permissions` are declared provider metadata in this stage. Declaring a
permission does not grant it: existing LoopX goal boundaries, user gates, and
external-write authorization still decide whether an operation may execute.

## Scope Boundaries

This first stage intentionally does not:

- rename or move existing capability implementation directories;
- infer capabilities from Python packages;
- install, enable, disable, or upgrade extension packages;
- import an extension entrypoint during catalog discovery;
- let manifest permissions bypass LoopX control-plane authority.

These omissions keep the registry useful now while leaving package and
lifecycle policy to a later, evidence-backed call site.

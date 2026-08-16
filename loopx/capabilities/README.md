# Capability Implementations

This directory contains capability-owned implementation code and supporting
modules. It is a contributor code boundary, not the shipped capability catalog:
a package existing here does not by itself register or enable a capability.

Use the runtime readback as the source of truth for the installed release:

```bash
loopx capability list --format json
loopx capability show <capability-id> --format json
```

`show` reports the capability's commands, write boundaries, implemented
protocol modules, canonical documentation, and durable validation. Follow
those returned module and document paths instead of maintaining a second
package-to-document index in this README.

## Contributor Navigation

- Start with the [product capability guide](../../docs/capabilities/README.md)
  when choosing a capability by caller outcome.
- Read [`catalog.py`](catalog.py) for built-in registration metadata and
  [`registry.py`](registry.py) for registry behavior.
- Treat packages such as shared context or provider helpers as supporting
  modules unless `loopx capability list` reports a registered capability.
- Use the capability's returned `docs`, `implemented_protocols`, and `smokes`
  fields to move between its contract, implementation, and validation.

Optional providers and their lifecycle belong to the
[extension boundary](../../docs/reference/extensions.md). Installing or
discovering an extension does not grant Kernel authority or turn an
implementation directory into a registered capability.

## Adding Or Moving Capability Code

Name capabilities after caller outcomes. Keep domain policy and typed
transition proposals in the owning capability, provider observations behind
the provider boundary, and durable goal, todo, gate, quota, recovery, and
scheduling truth in the Kernel.

Do not add a new capability path until it has a real entrypoint, catalog
registration, canonical documentation, and focused validation. Update the
catalog metadata when any of those paths move; the CLI readback and existing
catalog validation should remain the maintained cross-reference.

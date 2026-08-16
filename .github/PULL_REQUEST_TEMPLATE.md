## Summary

-

## Issue Or Task

- Closes #
- Contributor task ID:

## Validation

- [ ] `python3 -m py_compile loopx/*.py`
- [ ] `loopx check --scan-root .`
- [ ] Other:

## Type of Change

<!-- Mark the applicable options. -->

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Refactoring (no functional changes)
- [ ] Documentation update
- [ ] Test update

## LoopX Area

<!-- Mark the primary area. Maintainers apply the matching GitHub label. -->

- [ ] Control plane (goals, todos, quota, scheduler, registry, runtime)
- [ ] Benchmark boundary (adapters, runners, verifiers, scoring, evidence)
- [ ] Capability or extension (providers, adapters, skills)
- [ ] Public docs or presentation surface (README, protocols, dashboard)
- [ ] Build, packaging, installer, or CI
- [ ] Host or runtime integration

## Technical Direction

<!-- Select one. Direction labels route review; they do not imply maturity or merge authority. -->

- [ ] Core control-plane hardening
- [ ] Long-horizon benchmark evidence
- [ ] Operator surface and IM integration
- [ ] Shared Goal Authority and cross-host coordination
- [ ] Architecture and research incubator

- Target base branch:
- Direction tracker or promotion unit:

## Boundary Checklist

- [ ] I did not commit `.loopx/`, `.codex/goals/`, live `ACTIVE_GOAL_STATE.md`, credentials, private benchmark traces, verifier output, raw agent sessions, internal document links, or local machine paths.
- [ ] I did not duplicate maintainer-owned benchmark work unless a maintainer split out a public issue for it.
- [ ] I kept the change scoped to the linked issue/task.
- [ ] Every commit includes a DCO `Signed-off-by` trailer (`git commit -s`).

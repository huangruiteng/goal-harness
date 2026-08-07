# Security Policy

## Supported Versions

Security fixes are developed on `main` and released in the latest published
version of LoopX. Earlier releases are not maintained as separate security
branches; users should upgrade to the latest release before reporting a
version-specific regression.

## Reporting A Vulnerability

Please report suspected vulnerabilities through
[GitHub Private Vulnerability Reporting](https://github.com/huangruiteng/loopx/security/advisories/new).
Do not open a public issue, discussion, or pull request for an unpatched
vulnerability.

A useful report includes:

- the affected LoopX version or commit;
- the affected surface and expected security boundary;
- minimal reproduction steps or a proof of concept;
- the potential impact and any known mitigations; and
- a way to contact the reporter for follow-up.

Do not include credentials, private user data, or unrelated internal material.
If a reproduction needs sensitive evidence, describe how the maintainers can
obtain it through the private report instead of attaching it publicly.

The maintainers aim to acknowledge a report within five business days. After
triage, they will coordinate scope, remediation, release, and disclosure with
the reporter. Please allow time for a fix and advisory before publishing
technical details that would put users at risk.

## Scope

This policy covers LoopX source code, distributed packages, installation
paths, and repository-owned automation. Vulnerabilities that exist only in an
upstream dependency should normally be reported to that project; report them
to LoopX as well when LoopX's usage or configuration creates additional risk.

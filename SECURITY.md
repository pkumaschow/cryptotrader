# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| Older tags | ❌ |

Only the current `main` branch receives security fixes.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report vulnerabilities privately via [GitHub Security Advisories](../../security/advisories/new). Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any suggested mitigations if known

You can expect an acknowledgement within **72 hours** and a resolution or status update within **14 days**.

## Supply Chain Security

Every release is built with [SLSA Level 3](https://slsa.dev/spec/v1.0/levels) provenance attestations signed by GitHub's OIDC provider via Sigstore. See [README.md](README.md#supply-chain-security) for verification instructions.

The Docker image is scanned for vulnerabilities on every push using [Docker Scout](https://docs.docker.com/scout/).

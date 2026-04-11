# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| Older tags | ❌ |

Only the current `main` branch receives security fixes.

## Reporting a Vulnerability

Please **do not** open a public issue for security vulnerabilities.

Report vulnerabilities by emailing the maintainer directly or via a confidential GitLab issue. Include:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any suggested mitigations if known

You can expect an acknowledgement within **72 hours** and a resolution or status update within **14 days**.

## Supply Chain Security

Every push generates a [SLSA Level 3](https://slsa.dev/spec/v1.0/levels) provenance attestation signed with a cosign key-pair. See [README.md](README.md#supply-chain-security) for verification instructions.

The Docker image is built and pushed to the GitLab container registry on every push to `main`.

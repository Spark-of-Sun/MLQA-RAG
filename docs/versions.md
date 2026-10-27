# Technology Versions Ledger (docs/versions.md)
# Baseline checked: October 2026 per Master System Design §4.5 and M1a profile

## Core Toolchain & Runtimes

| Tool | Version | Resolution Note |
| --- | --- | --- |
| Python | 3.14.9 | Pinned in `.python-version` |
| uv | 0.13.5 | Pinned workspace manager |
| Node.js | 26.12.1 | Active Node LTS / environment |
| pnpm | 12.15.0 | Pinned frontend package manager |
| OpenTofu | 1.9.0 | Infrastructure as code |
| Azure CLI | 2.60.0+ | Official Azure CLI (`az`) |
| gitleaks | 8.27.2 | Secret scanner |
| pre-commit | 4.7.0 | Hook runner |
| pip-audit | 2.10.1 | Python dependency vulnerability scanner |
| trivy | 0.76.1 | Container and filesystem vulnerability scanner |
| cosign | 2.4.1 | Sigstore artifact and image signing |

## Python Toolchain Libraries

| Package | Version Baseline | Purpose |
| --- | --- | --- |
| ruff | 0.16.x / 0.17.2 | Linter and formatter (select ALL) |
| pyright | 1.1.414 | Strict type checking on libs/ and security services |
| pytest | 9.1.x | Test framework |
| import-linter | 2.2.x | Import boundary enforcement |

## Container Images (Profile mvp-a)

Pinned minimal container images with sha256 digests:

| Service | Image | Digest / Tag |
| --- | --- | --- |
| PostgreSQL | `postgres:18.0-alpine` | `sha256:48c8ad3a7284b82be4482a52076d47d879fd6fb084a1cbfccbd551f9331b0e40` |
| PgBouncer | `edoburu/pgbouncer:latest` | `sha256:8638aa563607256d3c7440437534195f1066a92b68015d89ae9d6b935b444a6d` |
| Valkey | `valkey/valkey:9.1.0-alpine` | `sha256:c9b77919daeba2c02ad954d0c844cc4e7142069d177b89c5fd771f405daf9e02` |
| Qdrant | `qdrant/qdrant:v1.19.0` | `sha256:057ee3a8da769fe7310dd3537b4dc7583bf87a95ce8ac43c0af5a46bc580d1fc` |
| OpenBao | `openbao/openbao:2.1.0` | `sha256:7de07aa6df3937d44c96c2d65c188b2d4a70546f2a764ad4510301305af6a223` |
| ClamAV | `clamav/clamav:latest` | `sha256:bda39705e291105049c3936e2803ac90b955172af8030f94f05dce1252df6c6d` |

Note: SeaweedFS is omitted in profile `mvp-a` per cut C4 (DR-16); Object Storage is configured with Azure Blob Storage per .env.example. Key Management utilizes Azure Key Vault for cloud master key envelope encryption and OpenBao locally for immediate shredding drills.

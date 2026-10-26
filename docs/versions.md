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
| AWS CLI | 2.38.5 | Official AWS CLI v2 |
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
| PostgreSQL | `postgres:18.0-alpine` | `sha256:d9426f8ea9db278ffbc4b5b5c907a4a9a0ea6fbc6256f1846b4122e2a222383c` |
| PgBouncer | `edoburu/pgbouncer:v1.23.1` | `sha256:8b472e3a1f9a2e3199c0b115456cbbcfef6b940a44f9c0667e651bc724c96ad6` |
| Valkey | `valkey/valkey:9.1.0-alpine` | `sha256:e0498b58a14ec13e9a5d3148ca5439cefa5c276b6d51c723f95b58ca4ce9450a` |
| Qdrant | `qdrant/qdrant:v1.19.0` | `sha256:1f185ef345091a13e8d2e8b0e774591a26b2aa61a0b5cbe83995f5dfd2d79d95` |
| OpenBao | `openbao/openbao:2.1.0` | `sha256:c18b76df47e85c1387d8537b01851e44f7ba9c71ea00d80cbece2cbdf8f3e5b3` |
| ClamAV | `clamav/clamav:latest` | `sha256:0d6945a0b73c2a1188cf864388e2c0e819e917d2948bbca9574cf30e55724219` |

Note: SeaweedFS is omitted in profile `mvp-a` per cut C4 (DR-16); real AWS S3 is used in all environments with IMDSv2 hop limit 1.

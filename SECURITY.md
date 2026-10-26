# Security Policy

## Non-Negotiables

- PostgreSQL Row-Level Security (RLS) is the final authority.
- Every tenant and document key is protected via AWS KMS / OpenBao envelope encryption.
- Sentence-gated release: answers require citation verification by `citation_validator` before delivery.
- Secret scanning via `gitleaks` is enforced on every commit.

## Reporting Vulnerabilities

Report security issues directly to the Coordinator or Daniel Reyes (Security Lead).

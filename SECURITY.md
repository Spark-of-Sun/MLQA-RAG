# Security

Report a vulnerability privately to security@onekami.site. Do not open a public issue.

This system stores legal and medical documents. The guarantees it makes, and how each is tested, are
in `docs/architecture.md` and `contracts/`. A change to row-level security policies, the
authorization matrix, key handling or the identity service needs a security review (see CODEOWNERS).

Never commit secrets: `.env`, `*.pem`, `*.key` and `.secrets/` are git-ignored; gitleaks runs as a
pre-commit hook and in CI. Real customer data never enters development, CI or staging.

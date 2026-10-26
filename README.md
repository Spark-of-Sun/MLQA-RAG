
# Legal-Medical QA System (MLQA-RAG)

Multi-tenant question-answering system over legal and medical documents with cryptographic isolation, sentence-level citation verification, and append-only audit logging.

Current Release Target: **M1a** (Profile `mvp-a`).

## Documentation

- System Design: `docs/design/Legal-Medical-QA-Master-System-Design-v3.1.md`
- MVP Report: `docs/design/Legal-Medical-QA-MVP-Prototype-Report-and-Process-v1.0.md`
- Scope Cuts: `docs/design/SCOPE_CUTS_M1a.md`
- Delivery Workflow: `PATCH_WORKFLOW.md`
- Path Ownership: `OWNERSHIP.md`
- Shared Team Status: `status/SHARED_STATUS.md`

## Getting Started

Check your local environment:
```bash
make doctor
```

Run test suite:
```bash
uv run pytest
```

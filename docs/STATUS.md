# Status of the MVP build (honest account)

This is a **partial** build. The data layer, the security libraries and the ingestion core are built
and tested against real servers. The gateway, identity, retrieval, generation, citation-validator
and audit **services**, the **frontend**, and the **deployment files** are **not built**. The zip is
not a deployable product. Nothing here has been run on AWS, Cloudflare or onekami.site.

## Built and tested (real servers in the build sandbox)

| Area | What exists | Evidence |
| --- | --- | --- |
| Workspace | uv workspace, Python 3.14, latest packages, strict ruff/pyright/pytest config, import-boundary contracts | ruff, strict pyright clean; 6 import contracts kept |
| Config | `.env.example` and `.env` with placeholders for every key | no real secrets present |
| Database | PostgreSQL 18 schema, FORCE RLS for the section 5.4 access decision, roles/grants, audit hash chain, 7 generated state machines | gates G1.1-G1.9 pass on real PostgreSQL 18.6; RLS equals the Python oracle on 260 random worlds; 7 injected policy bugs all caught |
| Pooler safety | transaction-local context, fail-closed on reused connections | G1.7 passes on real PgBouncer 1.26.1 (10,000 interleaved transactions, 0 leaks) |
| Keys | envelope encryption, OpenBao + AWS KMS adapters, per-document keys, crypto-erase | G1.10/G1.11 pass on real OpenBao; **AWS KMS test written, NOT run (no AWS credentials)** |
| Security libs | join codes (64/32 char, Luhn check), HPKE sealing, log redaction | 35 tests |
| Auth libs | Auth0 token verification, internal context tokens with certified signer keys | 34 tests; token abuse tests use locally signed tokens, **NOT run against live Auth0** |
| Vector store | principal-derived Qdrant filter, read-only/read-write keys | 25 tests on real Qdrant 1.20; Qdrant result contains RLS result on 60 random worlds |
| Object store + audit client | app-level encrypted objects, sealed audit payloads, crypto-shred | 11 tests on real SeaweedFS/PostgreSQL/OpenBao |
| Ingestion core | parsers (PDF, HTML, JATS, SPL, eCFR, DOCX, TXT), structure-aware chunker, scanner, pipeline | 49 chunking tests on 12 real documents; e2e passed for PDF, contract, regulation, case report, drug label, upload-safety rejections, OCR review, cross-workspace isolation |
| Corpus | fetcher + manifest with licence and SHA-256 | 12 real public documents |

## Not verified
- Ingestion e2e tests for access-change propagation, deletion (crypto-erase) and legal hold are written but were not confirmed passing.
- AWS KMS, Auth0, ClamAV, any LLM, OCR (Tesseract is not installed): code or tests written, nothing run live.
- The chunk minimum of 40 tokens is soft for tables and tiny tail units.
- Corpus is 12 documents, far below the document's 150 + 150 minimum.

## Not built
Gateway, identity, retrieval, generation, citation-validator (V1-V8) and audit **services**; the
Next.js 16 frontend; Dockerfiles, compose, OpenTofu for AWS/Cloudflare/Auth0; CI workflows;
runbooks; the stage gatekeeper. Governance requests, break-glass flows and the operator plane are
deferred by design for the MVP.

## To run the tests
Needs PostgreSQL 18, PgBouncer, Valkey, Qdrant, OpenBao, SeaweedFS running locally (the build
sandbox used downloaded binaries; Docker was not available). See `agent_work/logs/worklog.md`.
`uv sync --all-packages` then `uv run pytest -m "not live_aws"`.

# Debt Register (docs/debt-register.md)
# Maintained by Maya Okafor (Tech Lead)

| ID | Shortcut | Why acceptable in M1 / M1a | Flag or gate | Target | Owner |
| --- | --- | --- | --- | --- | --- |
| DR-1 | Operators are two named staff using cloud IAM with MFA and audit trails | M1 holds public data only | `operator_plane`, G9.7 | M2 | Security lead |
| DR-2 | Tenants are capped at 256 grants | Configuration limit with a clear error | `large_grant_path`, G5.9 | M3 | Tech lead |
| DR-3 | Only `sentence_gated` delivery with the `strip` policy | Default policy; regeneration is a policy value | `delivery_regenerate`, G7.8 | M2 | Tech lead |
| DR-4 | No compression and no answer cache | Optimizations behind existing interfaces | `compression`, `answer_cache`, G6.3, G6.5 | M3 | Tech lead |
| DR-5 | One host, no high availability, no disaster-recovery drill | No customer data | G9.10, Stage 11 | M3 | Release manager |
| DR-6 | Validator calibration on 100 pairs per domain | Precision floor is unchanged; the sample is smaller | G7.3 full | M3 | Domain reviewers |
| DR-7 | 320 live queries for the gated-release proof, not 1,000 | Zero-leak criterion is unchanged | G7.7 full | M3 | QA lead |
| DR-8 | Five critical alerts only | Remaining alerts cover deferred features | G9.3 full | M2 | Security lead |
| DR-9 | Basic per-workspace caps instead of hierarchical quotas | Single organization scale | `quotas_hierarchical`, G9.4 | M2 | Tech lead |
| DR-10 | No DOCX ingestion | PDF, JATS and SPL cover the corpus | `docx_ingest` | M3 | Tech lead |
| DR-11 | No governance, walls or review-queue UI | API and policies exist | `walls_ui`, `governance_requests` | M2 | Product owner |
| DR-12 | Time-to-first-verified-sentence target 8 s | CPU models on one host | G7.12 at 6 s | M3 | Tech lead |
| DR-13 | Corpus of about 38 legal documents, below M1 profile minimums | Enough to prove workflow and isolation on real contracts | G0.8 (`mvp-a`) | M1 | Data steward |
| DR-14 | Legal organizations only; medical domain off | Halves corpus, labels and reviewer work for first cut | `medical_domain`; G0.8, G4.4, G5.3, G7.3 | M1 | Tech lead |
| DR-15 | No OCR, quarantine or review screen; scanned pages fail with `ocr_disabled` | Fails safe: nothing low-confidence is ever embedded | `ocr_quarantine`; G4.5, G4.6, G8.3 | M1 | Data steward |
| DR-16 | AWS S3 in every environment; no SeaweedFS | Developers already use AWS; removes probe and a container | G0.4 | ADR at M1 | Tech lead |
| DR-17 | Three of five critical alerts | Other two need extra jobs | G9.3 full | M1 | Security lead |
| DR-18 | 100 live queries, not 320 | Zero-leak and zero-unverified criteria are unchanged | G7.7, AC4 | M1 | QA lead |
| DR-19 | One passing acceptance run, not three consecutive | M1a is not the release | MG4, AC1 | M1 | QA lead |

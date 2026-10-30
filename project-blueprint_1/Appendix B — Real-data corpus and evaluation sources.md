---
title: Appendix B — Real-data corpus and evaluation sources
---

## Appendix B — Real-data corpus and evaluation sources

`corpus/manifest.toml` is the only fixture source. Every item records `id`, `title`, `source_url`, `license`, `retrieved_at`, `sha256`, `bytes`, `format`, `domain`, `kind`, `pages`, `scanned`, `allowed_use` (`commercial`, `internal_eval_only`, `excluded`) and notes. The loader verifies hashes; the gate fails on any mismatch or missing licence. English-language documents only in v1.

| Domain | Candidate sources (verify the licence of each at Stage 0) | Used for |
| --- | --- | --- |
| Legal contracts | SEC EDGAR material-contract exhibits (public filings); the CUAD dataset of 510 commercial contracts with expert clause annotations (published under a Creative Commons licence) | Ingestion, structure detection gold, retrieval evaluation |
| Legal authority | US court opinions from CourtListener and the Caselaw Access Project (public domain); US Code, CFR and Federal Register from govinfo.gov (public domain); HIPAA rules (45 CFR Parts 160 and 164) | Citation and clause-level retrieval; regulatory filings |
| Legal evaluation | Published retrieval and entailment benchmarks built on real contracts (for example LegalBench-RAG and ContractNLI) | Retrieval floors, entailment calibration |
| Medical narratives | PubMed Central open-access case reports with permissive licences (JATS XML plus PDF) | Structure detection, retrieval, validator calibration |
| Medical structured | DailyMed drug labels (SPL XML); FDA guidance; CDC and WHO guidelines where the licence allows; ClinicalTrials.gov records | Structured chunking, dose and unit matching |
| Medical evaluation | Published biomedical question-answering sets with snippet ground truth (for example BioASQ, after registration), claim-verification sets where licences allow | Retrieval floors, entailment calibration |
| Scanned and OCR | Real public-domain scanned archive PDFs, plus real born-digital pages rasterized with scanner-like transformations so ground-truth text is known exactly | OCR and quarantine gates |
| Credentialed lane (opt-in) | MIMIC-IV-Note or similar under a data use agreement and a self-hosted model only | SOAP-style structure checks; never in shared CI |
| Human labels | A held-out set of at least 300 sentence–chunk pairs per domain labeled by a qualified attorney or clinician | Final authority for validator calibration |

Minimums (G0.8): 150 legal and 150 medical documents; at least 30 scanned multi-page PDFs; at least 10 documents of 100 to 200+ pages; at least 5 JATS, 20 SPL and 20 DOCX items. Non-commercial sets are used only if marked `internal_eval_only` and never shipped. The corpus is refreshed quarterly; a refresh is a manifest change reviewed like code.
# SCOPE_CUTS_M1a.md: the first cut before M1

**Status: proposed, needs coordinator approval (CD-12, CD-13).** Commit under `docs/design/` (coordinator-owned). Read together with the MVP Prototype Report v1.0 (the plan of record) and Master v3.1.

## 1. What this is and what it is not

**M1a** is a first working cut of the MVP: the full workflow on **legal documents only**, with seven cuts. It is **not** the MVP and is never labeled M1. The M1 tag still requires every cut below to be retired, the full `mvp` profile, and three consecutive green acceptance runs (MG4).

**No cut touches a non-negotiable or a safety threshold:** RLS as final authority, the full key hierarchy with deletion guards, hash-chained audit with anchors, sentence-gated release, Auth0 with passkeys, fail-closed behavior, real data only, no mocks, and the lint, type and test gates. Validator precision stays at least 0.99, revocation p99 within 2 seconds, zero cross-scope leaks, zero unverified sentences.

## 2. Honest effect on time

A rough bottom-up estimate against the report's effort table (126 person-weeks):

| Phase | Saved in M1a (person-weeks, rough) | Why |
| --- | --- | --- |
| P0 | 2 | Smaller corpus; no SeaweedFS probe |
| P3 | 5 | No OCR or quarantine; no JATS or SPL parsers |
| P4 | 3 | Legal-only question sets and calibration |
| P5 | 3 | No OCR review screen; two fewer alerts |
| P6 | 2 | One run, 100 queries |
| **Total** | **about 15 (roughly 12 percent)** | |

Most of this is **deferred, not deleted**: the work returns before the M1 tag. The only true saving is SeaweedFS (about 1 person-week). M1a reaches a first working milestone about 12 percent sooner. It will not halve the project. (An earlier chat guess of "about a quarter" was too high; this bottom-up figure replaces it.) The larger time risks are external: Auth0 plan, licences, reviewers, and failed gates.

## 3. The seven cuts

| Cut | Debt | M1a does | Flag or gate | Retire by | Owner |
| --- | --- | --- | --- | --- | --- |
| C1 Corpus size | DR-13 | About 38 legal documents (15 EDGAR, 15 CUAD, 5 opinions, 3 statutes) with at least 3 of 100+ pages | G0.8 (`mvp-a`) | M1 | Data steward (Priya) |
| C2 Legal first | DR-14 | Legal organizations only. No JATS or SPL parsers, medical corpus, clinician reviews, medical question sets or medical calibration pairs | `medical_domain`; G0.8, G4.4, G5.3, G7.3 medical parts | M1 | Tech lead (Maya), domain reviewers |
| C3 Scanned later | DR-15 | No OCR, quarantine or review screen; a page with no usable text layer fails with `ocr_disabled` and is never embedded | `ocr_quarantine`; G4.5, G4.6, G8.3 OCR flow | M1 | Data steward (Priya) |
| C4 Real S3 | DR-16 | AWS S3 in every environment; no SeaweedFS or probe; IMDSv2 hop limit 1 and per-service credentials so containers cannot borrow the host role | G0.4 (S3 capability check replaces the probe) | ADR at M1 | Tech lead (Maya) |
| C5 Three alerts | DR-17 | Audit-chain or anchor failure; boot self-test or role drift; key scheduled-deletion or key-policy event | G9.3 (five alerts) | M1 | Security lead (Daniel) |
| C6 Live queries | DR-18 | 100 live queries (50 questions x 2 tenants) | G7.7, AC4 | M1 (320) | QA lead (Hana) |
| C7 Acceptance runs | DR-19 | One passing run | MG4, AC1 | M1 (three consecutive) | QA lead (Hana) |

## 4. Profile `mvp-a` against `mvp`

| Item | `mvp` (M1) | `mvp-a` (M1a) |
| --- | --- | --- |
| Legal documents | 60 minimum | 35 minimum (about 38 targeted) |
| Medical documents | 60 minimum | 0 |
| Scanned multi-page PDFs | 10 | 0 |
| Documents of 100+ pages | 3 | 3 |
| Parsers | PDF text layer, sanitized HTML, JATS, SPL | PDF text layer, sanitized HTML |
| OCR and quarantine | on | off |
| Questions | 160 | 50 (40 answerable, 10 unanswerable), legal |
| Live queries | 320 | 100 |
| Labeled calibration pairs | 100 per domain | 100 legal |
| Domain reviewers | attorney and clinician | attorney |
| Deployment types | legal, medical, both | legal |
| Object store | SeaweedFS in Compose | AWS S3 |
| Critical alerts | 5 | 3 |
| Acceptance runs | 3 consecutive | 1 passing |
| Safety thresholds | fixed | **identical** |

## 5. M1a exit

- MG1 (flags), MG2 (no demo path), MG3 (continuity), MG5 (verified run report) and MG6 (data admission) pass.
- One acceptance run passes on profile `mvp-a`: legal workspaces, 100 live queries with zero unverified sentences, the isolation suite, the three alerts triggered for real, and every W or N step that needs a disabled flag listed as "not in profile".
- The report states `profile: mvp-a`, lists DR-13 to DR-19 as open, and cannot be labeled M1. The tag is `m1a-<n>`, never `m1`.

## 6. Getting from M1a to M1 (retire the cuts)

1. C2 and C1: medical corpus, JATS and SPL parsers, medical question sets and pairs, clinician reviewer; flag `medical_domain` on with G4.4, G5.3, G7.3 (medical parts).
2. C3: OCR, quarantine, review screen; flag `ocr_quarantine` on with G4.5, G4.6, G8.3.
3. C5: add the two alerts (database write rejection 42501; admin role outside an approved membership).
4. C4: ADR deciding S3 only versus adding a local store.
5. C6 and C7: 320 live queries and three consecutive green runs on profile `mvp` with all cuts retired. Flags go on only with signed gate attestations (C8).

## 7. New risks from the cuts

| Risk | Mitigation |
| --- | --- |
| Deferred work piles up after M1a | Debt register with owners and a target; flags bound to gates |
| Containers on the EC2 host borrow the instance role and reach S3 or KMS | IMDSv2 hop limit 1, minimal instance role, per-service credentials (Daniel), metadata blocked in Compose (Maya) |
| Legal-only calibration does not transfer to medical text | Re-measure precision on medical pairs before the M1 tag; the model may change |
| Unreachable medical and OCR states are untested end to end | Generated state-machine tests cover all states at database level; end-to-end tests arrive with the flags |
| M1a is mistaken for M1 | Profile label in the report, tag rule in the gatekeeper |

## 8. Debt register entries (for Maya's `docs/debt-register.md`)

| ID | Shortcut | Why acceptable in M1a | Flag or gate | Target | Owner |
| --- | --- | --- | --- | --- | --- |
| DR-13 | Corpus of about 38 legal documents, below the M1 profile minimums | Enough to prove the workflow and isolation on real contracts | G0.8 (`mvp-a`) | M1 | Data steward |
| DR-14 | Legal organizations only; medical domain off | Halves corpus, labels and reviewer work for the first cut | `medical_domain`; G0.8, G4.4, G5.3, G7.3 medical | M1 | Tech lead |
| DR-15 | No OCR, quarantine or review screen; scanned pages fail with `ocr_disabled` | Fails safe: nothing low-confidence is ever embedded | `ocr_quarantine`; G4.5, G4.6, G8.3 | M1 | Data steward |
| DR-16 | AWS S3 in every environment; no SeaweedFS | Developers already use AWS; removes the probe and a container | G0.4 | ADR at M1 | Tech lead |
| DR-17 | Three of five critical alerts | The other two (42501 write rejection; admin role outside membership) need extra jobs | G9.3 full | M1 | Security lead |
| DR-18 | 100 live queries, not 320 | Zero-leak and zero-unverified criteria are unchanged | G7.7, AC4 | M1 | QA lead |
| DR-19 | One passing acceptance run, not three consecutive | M1a is not the release | MG4, AC1 | M1 | QA lead |

## 9. Flags to add to `contracts/features.toml`

| Flag | `mvp-a` | `mvp` | Enables | Bound gates |
| --- | --- | --- | --- | --- |
| `medical_domain` | off | on | Medical deployment type, JATS and SPL parsers, medical sets | G0.8, G4.4, G5.3, G7.3 |
| `ocr_quarantine` | off | on | OCR, quarantine, `ocr_review` flow and screen | G4.5, G4.6, G8.3 |

## 10. Impact per developer

| Developer | Change |
| --- | --- |
| Maya | Profile `mvp-a`, two flags, S3 doctor check and metadata block, DR-13 to DR-19, two alerts |
| Daniel | Legal-only deployment type, S3 bucket and `ingestion`-only credential, IMDS hardening, one alert |
| Priya | Legal-only corpus, no JATS, SPL or OCR, S3 storage |
| Lucas | 50 legal questions, 100 queries, 100 legal pairs, attorney reviewer only |
| Hana | One run, 100 queries, report labeled `mvp-a`, no OCR screen |

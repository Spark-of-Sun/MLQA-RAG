# Acceptance Criteria Checklist (Release M1a)
# Reference: Legal-Medical-QA-MVP-Prototype-Report-and-Process-v1.0.md §9

| Criterion | Requirement | Verification Method | M1a Target |
|---|---|---|---|
| **AC1** | Complete workflow execution (W1 to W15) | Acceptance run on `mvp-a` profile | 1 passing run |
| **AC2** | Role and onboarding enforcement | Onboarding API & passkey verification | Verified |
| **AC3** | Zero cross-scope leaks | Isolation suite across multi-tenant queries | 0 leaks allowed |
| **AC4** | Zero unverified sentences | 100 live queries through `citation_validator` | 0 unverified allowed |
| **AC5** | Validator precision | 100 labeled legal calibration pairs | Precision >= 0.99 |
| **AC6** | Fast revocation | Auth0 token revocation timing | p99 <= 2.0 seconds |
| **AC7** | Operability & alerts | 3 critical alerts triggered for real | Verified |
| **AC8** | Continuity checks | MG1 to MG3 layout and schema continuity | Verified |

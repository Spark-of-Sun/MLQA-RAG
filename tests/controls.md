# Negative and Positive Control Instruments
# Reference: Master System Design §19.1 & 00_shared_rules_reference.md §9

Per project rules, no mock data or fake customers exist. Negative testing relies solely on registered control instruments tagged with `@pytest.mark.control`:

## 1. Malware Control
- **EICAR Test Signature**: Used exclusively to verify ClamAV detection and rejection in `services/ingestion/`.
- **Malformed PDF Structure**: PDF without valid header bytes (`%PDF-`) to verify scanner failure codes.

## 2. Secrets Scanning Control
- **Planted Secret Vectors**: Known dummy keys matching entropy rules used exclusively in `tests/isolation/` to verify `gitleaks` pre-commit and CI detection.

## 3. Boundary & Cross-Scope Canary
- **Synthetic Cross-Org Tenant ID**: `00000000-0000-0000-0000-000000000000` passed as header to verify immediate 403 Forbidden rejection and zero RLS row returns.

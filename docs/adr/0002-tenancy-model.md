# ADR 0002: Tenancy model

**Status:** Accepted

## Decision
Organization (customer, own KMS key) contains Workspaces (one per admin, the isolation unit) contain Tenants (end users). The customer is the Organization; 'tenant' means the end user.

## Why
Matches the doc's roles and the Super Admin boundary (control plane only). Pooled infrastructure with row-level security by default; a silo tier per organization is a mapping change.

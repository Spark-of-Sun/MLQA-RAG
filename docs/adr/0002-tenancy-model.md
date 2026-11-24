# ADR 0002: Tenancy model

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 1.2, 5 (5.1 to 5.4), 10.2, 10.10; decisions D5, D7; gates G1.4, G1.5, G1.6

## Context

Customers are law firms and hospital systems. Inside one customer, several admins each run their own group of
people, and those groups must not see each other. The owner of the customer account governs admins but must
not read documents. The model has to be cheap to run for hundreds of customers and still offer physical
separation to a customer whose contract requires it.

## Decision

- Hierarchy (1.2, 5.1): platform, then organization (one customer, Super Admin plus optional co-owner, own KMS
  key, own Auth0 Organization), then workspace (one per admin, the isolation unit, mutually invisible), then
  tenant (member of exactly one workspace).
- Every table, vector payload, object key, cache key and audit event carries `org_id`; everything beneath an
  admin also carries `workspace_id`. Foreign keys are composite (`org_id`, `workspace_id`, ...), so a row cannot
  point into another workspace.
- Roles are fixed in v1 (Super Admin, Admin, Tenant). Changing role means off-boarding and re-onboarding.
- D7: one membership per user in v1. The `memberships` table already supports several, so multi-membership
  needs no migration later.
- The Super Admin boundary holds at three levels (5.3): no Gateway route to content, no service code path, and
  no database policy on documents, chunks, tenant memberships, walls or audit payloads.
- One access-decision function (5.4, eight ordered rules: inactive deny, wall deny, owner allow, admin on
  matter, tenant grant with tier ceiling, emergency exception, break-glass, deny). RLS policies, the vector
  filter builder and the Python test oracle all implement it.
- D5 (10.10): pooled infrastructure by default, with FORCE RLS and per-organization keys. An `OrgRouter` in
  `lmqa_db` maps `org_id` to its connection set (database DSN, vector collection or cluster, bucket, KMS key);
  a silo customer gets a different mapping through the same interface.

## Alternatives considered

- Database per organization by default: rejected because migrations and connection pools across hundreds of
  databases are costly; pooled storage with RLS and a key per organization gives most of the isolation. Kept as
  the silo tier.
- One Auth0 Organization per workspace: rejected because Auth0 Organizations are flat and SSO and branding are
  customer-level concerns (8.1).
- Application-only filtering (`WHERE workspace_id = ...` in code): rejected because one missed filter leaks; the
  database must deny by default (principle 1).
- Multiple memberships per user in v1: deferred; it widens every scope calculation and is not needed yet.

## Consequences

- Positive: isolation is enforced by PostgreSQL even if application code asks for the wrong rows; silo
  customers need no second code path.
- Positive: erasure by key destruction works per organization, workspace and document (ADR 0005).
- Negative: RLS policy overhead on every query, measured against the budget of 20% at 10,000 grants per user
  (section 22); policies need a differential test to be trusted.
- Proven by G1.4 (RLS equals the oracle on at least 20,000 generated scenarios), G1.5 (Super Admin reads zero
  content rows), G1.6 (cross-workspace references fail for every foreign key) and G5.4 (provenance isolation).

## Current state

Built as designed in the MVP ([docs/mvp.md](../mvp.md), "Built, as designed"): organization, workspace and
member with one membership per person; the Super Admin has no route, service path or RLS policy on content;
RLS on documents, chunks, shares, queries and the ledger with a fail-closed context.

Differences: the MVP access rule is a simplified form of 5.4 (private, shared with the workspace, or shared
with named people); matters, confidentiality tiers, walls, emergency access and break-glass are deviation 10
(Stage 5). `OrgRouter` and the silo tier are not built; everything is pooled in one database. The G1.4
oracle test and the Stage 1 gate suite are not yet written (deviation 13).

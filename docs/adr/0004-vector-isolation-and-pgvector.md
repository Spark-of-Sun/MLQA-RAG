# ADR 0004: Vector isolation and the pgvector alternative

- Status: Accepted, MVP deviation in force (date 2026-11-22)
- Blueprint: sections 10.1, 10.5, 10.6, 22; decision D16; defects DEF-01, DEF-47; gates G5.1, G5.2, G5.4,
  G5.8, G5.9, G10.8

## Context

Retrieval needs approximate nearest-neighbour search over many workspaces. Qdrant scopes JWT access by
collection and by read or write, not by payload, so in a shared collection a missing tenant filter is not
rejected by Qdrant (DEF-01). Its JWT signing secret is also the API key, so any holder can mint any token.
The vector store therefore cannot be an isolation boundary for pooled data. Embeddings and sparse terms can
also leak source content, so the store is sensitive in its own right.

## Decision

- PostgreSQL RLS is the only final authority (10.1). The vector store narrows search for recall and speed.
- D16 pooled default: one shared Qdrant collection per embedding version, `workspace_id` as an `is_tenant`
  payload field. `lmqa_vectorstore` is the only code that holds a Qdrant client; its query, delete-by-filter and
  payload-update functions take a principal, build the filter themselves and have no unfiltered variant. Point
  lookups by ID are never made with user-supplied IDs.
- Filters always contain `org_id` and `workspace_id`, plus the 5.4 rules (owner, matter grants with tier
  ceiling, `must_not` on walled matters). If no filter can be built, the answer is 403.
- Postgres cross-check: Qdrant returns chunk IDs only; retrieval fetches chunk text from PostgreSQL under RLS.
  An ID that Postgres refuses is dropped and counted; a scope mismatch found by the reconciler is a high alert.
- More than 256 granted matters: over-fetch and cross-check (workspace and visibility filter, up to 500
  candidates, RLS discards the rest, widen up to a cap).
- Separate keys: read-only for `retrieval`, read-write for `ingestion`. Index changes flow through the
  `index_outbox` and the reconciler (10.6); PostgreSQL decides and the index follows.
- High-assurance tier: one collection per workspace with a collection-scoped JWT minted by a small
  vector-access broker, which Qdrant itself enforces.
- pgvector is the evaluated alternative and the fallback if Stage 10 load tests show the filtering wrapper and
  over-fetch path cannot meet the section 22 budgets (DEF-47).

## Alternatives considered

- pgvector as the default: vectors fall under the same RLS as every other row, which removes this class of
  problem. Not chosen as the default because filtered approximate search at tens of millions of vectors per
  workspace is the Stage 10 risk. Kept as the fallback.
- Collection per workspace for everyone: Qdrant enforces it, but many collections are costly to operate.
  Offered as the silo tier only.
- Trusting Qdrant payload filters as a boundary: rejected (DEF-01).
- Encrypting vectors: rejected; search cannot run over ciphertext, so protection is access control.

## Consequences

- Positive: a filter bug in the wrapper cannot return foreign text, because text comes from PostgreSQL under RLS.
- Negative: two stores to keep consistent (outbox, indexer, reconciler); a mismatch metric to watch.
- Negative: the retrieval budget (p95 800 ms with 5,000 grants at 1,000,000 chunks) must be met by the
  wrapper and over-fetch path.
- Proven by G5.1 (no query without a principal; retrieval key cannot write), G5.2 (network reach), G5.4
  (provenance isolation; vector result set is a superset of or equal to RLS's), G5.8 (stale index safety),
  G5.9 and G10.8 (large grant sets within budget).

## Current state

The MVP uses pgvector in PostgreSQL behind the same `lmqa_vectorstore` library (deviation 2 in
[docs/mvp.md](../mvp.md)). Dense search is pgvector cosine similarity inside the caller's RLS scope, so
vectors fall under the same policies as chunks; the explicit workspace filter is defence in depth.
`libs/lmqa_vectorstore/src/lmqa_vectorstore/search.py` documents this. Qdrant 1.20.0 runs in Compose and
the Stage 0 test `test_qdrant_keys_are_enforced` in `tests/integration/test_stage0_infra.py` checks its keys,
but no product path uses it yet.

Revisit at the Stage 10 load tests: if pgvector meets the section 22 budgets, an ADR addendum may keep it;
otherwise Qdrant with the wrapper above replaces it.

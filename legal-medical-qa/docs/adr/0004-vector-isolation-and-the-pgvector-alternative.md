# ADR 0004: Vector isolation and the pgvector alternative

**Status:** Accepted

## Decision
Qdrant narrows search (a filter built only from a principal) but is NOT a security boundary: PostgreSQL RLS is the final authority and every returned ID is cross-checked. A collection-per-workspace tier exists for high assurance. pgvector remains the fallback if filtered ANN cannot meet the latency budget at scale.

## Why
Qdrant's JWT access control is per collection, not per payload, so a missing filter is not rejected by the database. The cross-check makes a filter bug a counted mismatch, not a leak. Differential tests prove the filter result contains the RLS result.

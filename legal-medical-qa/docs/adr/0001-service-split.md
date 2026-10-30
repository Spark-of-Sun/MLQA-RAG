# ADR 0001: Service split

**Status:** Accepted

## Decision
Eight services (gateway, identity, ingestion, retrieval, generation, citation_validator, audit, ops), each its own deployable, image and database role. The Gateway orchestrates; services never call each other.

## Why
Independent blast radius and least privilege per service; import-linter enforces the boundaries (6 contracts). Cost: more moving parts than a monolith; chosen because the isolation guarantees are the product.

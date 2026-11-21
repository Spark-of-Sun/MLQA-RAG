# ADR 0003: Auth0 authenticates, PostgreSQL authorizes

**Status:** Accepted

## Decision
Auth0 owns login, MFA and passkeys. Role, workspace, status, grants, walls and approvals live in PostgreSQL, resolved per request from the `principal_v` view; the token's role claim is advisory and a mismatch is refused.

## Why
Suspension must take effect in seconds, which a JWT cannot do; a per-request status check plus pub/sub invalidation can.

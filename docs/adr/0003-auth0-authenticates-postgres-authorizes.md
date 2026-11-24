# ADR 0003: Auth0 authenticates, PostgreSQL authorizes

- Status: Accepted (date 2026-11-22)
- Blueprint: sections 8 (8.1 to 8.10), 1.2; decisions D8, D13, D30; defects DEF-09, DEF-19, DEF-58;
  gates G0.7, G2.6, G2.7, G3.1, G3.2, G3.4, G8.5

## Context

Login, passkeys, MFA, breached-password checks and SSO are hard to build and easy to get wrong, so a managed
identity provider should own them. Authorization is different: a suspended admin must lose access within
seconds, and a JWT cannot be recalled before it expires. If role or workspace came from a token claim, a
suspension would wait for the token to expire and a mistaken Auth0 configuration could grant a role.

## Decision

- Auth0 owns sign-up, login, password policy, passkeys and MFA factors, and holds one Auth0 Organization per
  our organization (not per workspace). Three Auth0 roles exist per tenant; only `identity` assigns them.
- PostgreSQL is the source of truth for role, workspace, status, grants, walls and approvals. The Gateway
  verifies the token and resolves the principal from Valkey and PostgreSQL on every request. The role claim is
  advisory for BFF routing only; a mismatch with the database denies the request and raises an alert (DEF-09).
- Token checks (8.5): RS256 only (`none` and HS256 rejected), exact `iss`, `aud` equal to the API identifier,
  allowed `azp`, `exp` and `nbf` with at most 30 s skew, `org_id` equal to the active membership's organization.
  Access tokens live 10 minutes; refresh tokens rotate with reuse detection.
- Two APIs: `main` (Organization required) and `onboarding` (Organization denied, onboarding endpoints only).
  The BFF is a Regular Web Application using Authorization Code with PKCE.
- D13: passkeys or WebAuthn are mandatory for Super Admins and admins, with two phishing-resistant authenticators
  for governance and step-up within 5 minutes (RFC 9470 challenge shape). SMS, voice and email OTP are disabled.
- D30: `@auth0/nextjs-auth0` v4 with a server-side session store in Valkey; the browser holds only an opaque
  httpOnly session ID (DEF-58).
- Revocation (8.6): state change and `principal_version` bump in one transaction, cache delete and pub/sub
  invalidation, then Auth0 membership removal and session end. Targets: p99 2 s for new requests, hard bound
  5 s with pub/sub down; open streams cut within 2 s, 15 s fallback.
- Auth0 configuration is OpenTofu code in `infra/auth0/`, drift-tested. There is no mock identity provider (DEF-10).

## Alternatives considered

- Roles and workspace in token claims as the authority: rejected; suspension would lag token expiry and the
  Action becomes an authorization component.
- Self-built authentication: rejected; passkeys, breached-password detection and SSO federation are a large,
  security-critical surface that Auth0 already operates.
- Auth0 Organization per workspace: rejected (flat model, customer-level SSO and branding, DEF-19).
- SDK default stateless cookie session: rejected for production because tokens sit in the browser and the
  session cannot be revoked server-side.

## Consequences

- Positive: suspension takes effect in seconds; an Auth0 misconfiguration cannot by itself grant data access.
- Negative: a database read (or cache hit) per request; dependency on Auth0 plan features (BAA add-on, M2M
  allowance, D8 to confirm before any PHI).
- Proven by G0.7 (tenant as code, real login), G2.6 and G2.7 (privileged strength, claim contract), G3.1
  (token abuse returns 401), G3.2 (principal from the database), G3.4 (revocation SLO), G8.5 (no tokens in the browser).

## Current state

The MVP uses Auth0 Universal Login through the Next.js SDK; the Gateway checks RS256 tokens for issuer,
audience and expiry, and takes role and status from PostgreSQL only ([docs/mvp.md](../mvp.md), "Built, as
designed"). Deviations: one API audience and no Auth0 Organizations, passkeys or step-up (deviation 7, Stage 2);
the SDK's encrypted session cookie instead of a server-side store, with the access-token endpoint disabled
(deviation 8, Stage 8); one idle and absolute limit for every role (deviation 14); suspension applies on the
next request without pub/sub (deviation 9, Stage 3).

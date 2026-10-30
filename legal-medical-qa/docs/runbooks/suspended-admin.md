# Runbook: an administrator is suspended, removed, or unreachable

**What happens automatically on suspend:** the workspace becomes `frozen`; every tenant is suspended with reason
`workspace_frozen`; the Admin Code is disabled; sessions are revoked within seconds. Data is retained and unreadable.

* **Reactivate (same person):** Manage Admins -> Reactivate. Only tenants suspended *by the cascade* come back; a
  tenant the admin had suspended separately stays suspended. The Admin Code stays dead until the admin rotates it.
* **Replace the admin:** the `successor_transfer` governance flow is deferred in this MVP (feature flag
  `governance_requests`). Until it ships, leave the workspace frozen; it is unreadable by anyone. After 30 days with
  no decision it should be sealed (the sealing job is part of the deferred lifecycle work).
* **Lost Super Admin:** see `org-recovery.md`.

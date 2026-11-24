# Runbook: The Super Admin identity is lost

1. If a co-owner exists, the co-owner acts as owner; add a new co-owner (`co_owner_set`).
2. Otherwise `operator_support` opens `owner_recovery` at the request of the organization's authorized signatory, verified out of band.
3. Approvals: `security_officer` and a different `operator_support` lead (three distinct operators). Every admin and the co-owner are notified and can veto within 72 hours.
4. After the wait the new owner identity is bound; the old one is removed and its Auth0 sessions revoked.

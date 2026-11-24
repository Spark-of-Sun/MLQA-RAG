# Runbook: An admin was suspended or removed

1. The workspace is `frozen`; its tenants are suspended with reason `workspace_frozen` and its codes are disabled (7.7).
2. To continue the workspace with a new admin, the Super Admin starts a `successor_transfer` governance request; a co-owner (or an operator `security_officer` after out-of-band confirmation) approves; after 72 hours the successor becomes active and cascade-suspended tenants are restored.
3. With no successor for 30 days the workspace is sealed (keys withdrawn, escrow kept). Unsealing needs `workspace_unseal` (two people, 72 hours).

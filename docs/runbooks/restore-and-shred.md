# Runbook: Restore from backup without un-shredding

1. Restore PostgreSQL to the target point in time into an isolated environment, per organization (12.9).
2. Before accepting any traffic run tombstone replay for the organization: every document, workspace and audit-month key that the ledger records as destroyed is shredded again in the restored copy.
3. Restore Qdrant from snapshot, then run the reconciler: vectors of shredded documents are orphans and are deleted.
4. Verify: a sample of tombstoned documents fails to decrypt; the audit chain verifies; then open traffic.

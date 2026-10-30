# Runbook: restoring a backup without resurrecting deleted data

Per-organization deletion is safe by key destruction. For a single document or workspace the wrapped key may still
exist in an older backup (at most 35 days). The `deletion_tombstones` table is mirrored to the Object Lock tombstone
bucket outside the backup set.

1. Restore PostgreSQL to a **new** instance and keep it off the network.
2. **Before it accepts any traffic**, replay the tombstone ledger: for every tombstone, set `doc_keys.wrapped_key = NULL,
   state = 'destroyed'` for documents, and delete the workspace key rows for destroyed workspaces. (The replay tool
   is an open item: write it before the first restore drill, gate G9.6.)
3. Run the reconciler per workspace so vectors and objects that should not exist are removed.
4. Restore per organization, never the whole platform at once.
5. Verify: decrypting a tombstoned document must fail (`DocumentKeyDestroyedError`).

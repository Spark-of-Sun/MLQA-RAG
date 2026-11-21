# Runbook: a KMS key deletion / disable / policy event paged

**Signal:** the `keyguard` SNS topic (EventBridge on ScheduleKeyDeletion, DisableKey, CancelKeyDeletion,
PutKeyPolicy, DeleteImportedKeyMaterial, EnableKey). Every such event is a potential permanent data loss.

1. **Was it approved?** A legitimate destruction has two approvals in a `governance_requests` row of kind
   `org_delete` / `workspace_destroy` and a finished waiting window. If there is no matching record, treat it as an attack.
2. **Restore first, investigate second (restoring is deliberately easy):**
   `aws kms cancel-key-deletion --key-id <id>` then `aws kms enable-key --key-id <id>`. One person can do this.
3. **Find the caller:** CloudTrail `userIdentity` for the event. Only `keyguard-destroyer` and `key-admin` can succeed;
   a success by anyone else means a key policy or SCP has drifted: run `uv run python infra/keyguard/lint.py infra/aws`.
4. **Open items:** the automatic responder (cancel and re-enable within 60 seconds) is not written yet, so step 2 is manual.

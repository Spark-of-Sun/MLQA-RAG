# Runbook: a join code has leaked

**Signal:** the new-country / burst alert on code use, a user reports pasting a code in a public place, or
`join_attempts` shows a spike of `rejected` rows for one `lookup_id`.

1. **Kill the code now.** The Super Admin (Organization Code) or the workspace admin (Admin Code) opens
   Manage Admins / Manage Tenants and generates a new code. Generating retires the old one instantly
   (`join_codes.state = 'rotated'`); there is no grace period.
2. **Review pending requests.** Rotation does not auto-approve anything; pending requests stay pending. Reject
   any you do not recognise. Active members are unaffected.
3. **Look at what the code did.** In `audit_event`, filter `action IN ('admin.join_requested', 'tenant.join_requested')`
   for the code's window. The true failure reason of every rejected attempt is in `join_attempts.true_reason`.
4. **If an admin was approved from a leaked code:** suspend them (Manage Admins -> Suspend). This freezes the
   workspace, suspends its tenants with reason `workspace_frozen`, disables the Admin Code and signs everyone out
   within seconds (principal-version bump plus pub/sub). Reactivate only after you have verified the person.
5. **Prevent a repeat:** prefer an email-bound invite for admins, and keep the default `manual` approval for tenants.

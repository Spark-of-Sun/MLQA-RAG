# Runbook: the Super Admin lost access

The designed path is `owner_recovery`: three distinct operators, notice to every admin and any co-owner (who can
veto), and a 72 hour wait, after which a new Super Admin identity is attached and must enrol two passkeys.

**Status in this MVP:** `owner_recovery`, the operator plane (`ops` service) and the co-owner flow are NOT built
(feature flag `operator_plane` is off). Until they are:

1. Do not reset anyone's Auth0 password or MFA to "recover" the account: recovery must never downgrade (doc 8.4).
2. Verify the customer's authorised signatory out of band (call a number from the contract, not from the request).
3. Escalate to the engineering lead: a Super Admin membership can only be re-parented by a reviewed, audited database
   change made by two people. Record both approvers in the ticket and write an `audit_append` event.

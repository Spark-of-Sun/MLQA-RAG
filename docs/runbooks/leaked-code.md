# Runbook: A join code was leaked

1. In Manage admins (Organization Code) or Manage members (Admin Code), choose **Generate code**. Rotation moves the old code to `rotated` at once; it can no longer be redeemed.
2. Review pending requests that arrived since the leak and reject any you do not recognize. A leaked code only creates *pending* requests: nobody gets access without approval (blueprint 7.3, 7.4).
3. Check the audit trail for `code.*` events and the alert `code_failure_burst`.
4. If an approval was given in error, suspend the membership: access ends on the next request; open streams are cut within 2 s.

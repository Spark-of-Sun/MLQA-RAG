# Runbook: A KMS key deletion or disable event fired

1. The KeyGuard responder already acted: an event without an approved KeyGuard record is cancelled and the key re-enabled within 60 s (12.5). Confirm in the page payload (`action`).
2. Confirm the key state: `aws kms describe-key --key-id <arn>` shows `Enabled`.
3. Find the principal in the CloudTrail event. Any principal other than `keyguard-destroyer` or `key-admin` means the preventive controls failed: open a security incident and an ADR addendum (19.7).
4. If the event was approved (a destruction ritual in progress), verify the request ID in the session tags matches an executable governance request.

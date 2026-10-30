# KMS: the platform trust root and the storage key. Per-organization CMKs are created at runtime by the
# identity service (one per organization, multi-Region, with a separate escrow key in the vault account).
#
# KeyGuard (doc 12.5): an explicit DENY on the destructive actions for every principal except the two named
# roles. A key policy deny beats every IAM allow, so a compromised service role cannot delete a key.

data "aws_iam_policy_document" "trust_root" {
  statement {
    sid       = "EnableIamPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid       = "KeyGuardDenyDestructiveActions"
    effect    = "Deny"
    actions   = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:PutKeyPolicy", "kms:DeleteImportedKeyMaterial"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "aws:PrincipalArn"
      values   = [var.keyguard_destroyer_role_arn, var.key_admin_role_arn]
    }
  }
}

# ECC P-256 sign and verify only: it signs one-hour signer certificates, never individual requests (doc 9.1).
# Asymmetric keys cannot auto-rotate: create a new key every 90 days and trust both during the overlap.
resource "aws_kms_key" "trust_root" {
  description              = "${local.prefix} context-token trust root (signs signer certificates)"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = "ECC_NIST_P256"
  deletion_window_in_days  = 30
  policy                   = data.aws_iam_policy_document.trust_root.json
}

resource "aws_kms_alias" "trust_root" {
  name          = "alias/${local.prefix}-trust-root"
  target_key_id = aws_kms_key.trust_root.key_id
}

data "aws_iam_policy_document" "storage_key" {
  statement {
    sid       = "EnableIamPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }
  statement {
    sid       = "KeyGuardDenyDestructiveActions"
    effect    = "Deny"
    actions   = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:PutKeyPolicy", "kms:DeleteImportedKeyMaterial"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "aws:PrincipalArn"
      values   = [var.keyguard_destroyer_role_arn, var.key_admin_role_arn]
    }
  }
}

# Server-side encryption of the buckets (defense in depth under the application-level envelope encryption).
resource "aws_kms_key" "storage" {
  description             = "${local.prefix} S3 server-side encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.storage_key.json
}

resource "aws_kms_alias" "storage" {
  name          = "alias/${local.prefix}-storage"
  target_key_id = aws_kms_key.storage.key_id
}

# AWS dev and CI accounts (blueprint 4.6, 12, 13.4, Stage 0 and 1). Apply per environment:
#   tofu -chdir=infra/aws init && tofu -chdir=infra/aws plan -var env=dev -var github_repo=<owner/repo>
# Credentials come from an SSO profile locally and from GitHub OIDC in CI; no static keys exist anywhere.

terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

variable "env" {
  type = string
  validation {
    condition     = contains(["dev", "ci", "staging", "prod"], var.env)
    error_message = "env must be dev, ci, staging or prod"
  }
}
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "replica_region" {
  type    = string
  default = "us-west-2"
}
variable "github_repo" {
  type    = string
  default = ""
}
variable "oncall_webhook_url" {
  type      = string
  default   = ""
  sensitive = true
}
variable "anchor_retention_days" {
  type    = number
  default = 2190 # six years (13.8 baseline, confirm with counsel: D10)
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "lmqa", env = var.env, managed_by = "opentofu" } }
}

data "aws_caller_identity" "me" {}

locals {
  account_id    = data.aws_caller_identity.me.account_id
  name          = "lmqa-${var.env}"
  window_days   = 30
  service_roles = [for s in ["identity", "ingestion", "retrieval", "generation", "validator", "audit", "gateway"] : "arn:aws:iam::${local.account_id}:role/${local.name}-svc-${s}"]
}

# --- trust root: asymmetric key that signs hour-long signer certificates (9.1, D29) -------------------------------
resource "aws_kms_key" "trust_root" {
  description              = "${local.name} context-token trust root"
  customer_master_key_spec = "ECC_NIST_P256"
  key_usage                = "SIGN_VERIFY"
  deletion_window_in_days  = local.window_days
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Admin", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${local.account_id}:role/key-admin" }, Action = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:PutKeyPolicy", "kms:TagResource"], Resource = "*" },
      { Sid = "RootReadOnly", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }, Action = ["kms:DescribeKey", "kms:GetKeyPolicy", "kms:ListResourceTags"], Resource = "*" },
      # Only the gateway signs signer certificates, about once per instance per hour (G3.5). Every service verifies.
      { Sid = "GatewaySigns", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${local.account_id}:role/${local.name}-svc-gateway" }, Action = ["kms:Sign"], Resource = "*" },
      { Sid = "ServicesVerify", Effect = "Allow", Principal = { AWS = local.service_roles }, Action = ["kms:GetPublicKey", "kms:Verify"], Resource = "*" },
      { Sid = "DenyDestruction", Effect = "Deny", Principal = { AWS = "*" }, Action = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:PutKeyPolicy"], Resource = "*",
      Condition = { ArnNotLike = { "aws:PrincipalArn" = ["arn:aws:iam::${local.account_id}:role/keyguard-destroyer", "arn:aws:iam::${local.account_id}:role/key-admin"] } } },
    ]
  })
}
resource "aws_kms_alias" "trust_root" {
  name          = "alias/${local.name}-trust-root"
  target_key_id = aws_kms_key.trust_root.key_id
}

# --- audit anchor bucket: Object Lock in compliance mode (13.4, G0.9, G9.1) ---------------------------------------
resource "aws_s3_bucket" "anchor" {
  bucket              = "${local.name}-audit-anchor-${local.account_id}"
  object_lock_enabled = true
}
resource "aws_s3_bucket_versioning" "anchor" {
  bucket = aws_s3_bucket.anchor.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_object_lock_configuration" "anchor" {
  bucket = aws_s3_bucket.anchor.id
  rule {
    default_retention {
      mode = var.env == "prod" ? "COMPLIANCE" : "GOVERNANCE"
      days = var.env == "prod" ? var.anchor_retention_days : 30
    }
  }
}
resource "aws_s3_bucket_public_access_block" "anchor" {
  bucket                  = aws_s3_bucket.anchor.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- tombstone ledger: outside the backup set, Object Lock (12.9) ------------------------------------------------
resource "aws_s3_bucket" "tombstones" {
  bucket              = "${local.name}-tombstones-${local.account_id}"
  object_lock_enabled = true
}
resource "aws_s3_bucket_versioning" "tombstones" {
  bucket = aws_s3_bucket.tombstones.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_object_lock_configuration" "tombstones" {
  bucket = aws_s3_bucket.tombstones.id
  rule {
    default_retention {
      mode = var.env == "prod" ? "COMPLIANCE" : "GOVERNANCE"
      days = 400
    }
  }
}
resource "aws_s3_bucket_public_access_block" "tombstones" {
  bucket                  = aws_s3_bucket.tombstones.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- KeyGuard roles (12.5): destroyer (workflow only), key admin (MFA), responder (restore only) ------------------
data "aws_iam_policy_document" "keyguard_destroyer_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "AWS"
      identifiers = [aws_iam_role.keyguard_workflow.arn]
    }
    condition {
      test     = "Null"
      variable = "aws:RequestTag/lmqa:approval_1"
      values   = ["false"]
    }
    condition {
      test     = "Null"
      variable = "aws:RequestTag/lmqa:approval_2"
      values   = ["false"]
    }
  }
}
resource "aws_iam_role" "keyguard_workflow" {
  name = "keyguard-workflow"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}
resource "aws_iam_role" "keyguard_destroyer" {
  name               = "keyguard-destroyer"
  assume_role_policy = data.aws_iam_policy_document.keyguard_destroyer_trust.json
}
resource "aws_iam_role_policy" "keyguard_destroyer" {
  role = aws_iam_role.keyguard_destroyer.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:DescribeKey"], Resource = "*" }]
  })
}
resource "aws_iam_role" "keyguard_responder" {
  name = "keyguard-responder"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}
resource "aws_iam_role_policy" "keyguard_responder" {
  role = aws_iam_role.keyguard_responder.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["kms:CancelKeyDeletion", "kms:EnableKey", "kms:DescribeKey", "kms:ListResourceTags"], Resource = "*" },
      { Effect = "Allow", Action = ["dynamodb:Scan"], Resource = aws_dynamodb_table.keyguard_approvals.arn },
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "*" },
    ]
  })
}
resource "aws_dynamodb_table" "keyguard_approvals" {
  name         = "${local.name}-keyguard-approvals"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_id"
  attribute {
    name = "request_id"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
}

# Responder: EventBridge rule on CloudTrail KMS events -> Lambda (package built by `make keyguard-package`).
resource "aws_lambda_function" "responder" {
  function_name = "${local.name}-keyguard-responder"
  role          = aws_iam_role.keyguard_responder.arn
  runtime       = "python3.13"
  handler       = "responder.handler"
  filename      = "${path.module}/build/keyguard-responder.zip"
  timeout       = 30
  environment {
    variables = {
      KEYGUARD_APPROVALS_TABLE = aws_dynamodb_table.keyguard_approvals.name
      ONCALL_WEBHOOK_URL       = var.oncall_webhook_url
    }
  }
}
resource "aws_cloudwatch_event_rule" "kms_events" {
  name = "${local.name}-kms-key-events"
  event_pattern = jsonencode({
    source        = ["aws.kms"]
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = { eventName = ["ScheduleKeyDeletion", "DisableKey", "CancelKeyDeletion", "PutKeyPolicy", "DeleteImportedKeyMaterial", "ImportKeyMaterial"] }
  })
}
resource "aws_cloudwatch_event_target" "responder" {
  rule = aws_cloudwatch_event_rule.kms_events.name
  arn  = aws_lambda_function.responder.arn
}
resource "aws_lambda_permission" "events" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.responder.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.kms_events.arn
}

# --- GitHub OIDC for CI (no static keys) --------------------------------------------------------------------------
resource "aws_iam_openid_connect_provider" "github" {
  count           = var.github_repo == "" ? 0 : 1
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}
resource "aws_iam_role" "ci" {
  count = var.github_repo == "" ? 0 : 1
  name  = "${local.name}-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github[0].arn }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*" }
      }
    }]
  })
}
resource "aws_iam_role_policy" "ci" {
  count = var.github_repo == "" ? 0 : 1
  role  = aws_iam_role.ci[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["kms:CreateKey", "kms:CreateAlias", "kms:TagResource", "kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey", "kms:EnableKeyRotation", "kms:ListResourceTags", "kms:CancelKeyDeletion", "kms:EnableKey"], Resource = "*" },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:GetObjectRetention"], Resource = ["${aws_s3_bucket.anchor.arn}/*", "${aws_s3_bucket.tombstones.arn}/*"] },
    ]
  })
}

output "trust_root_key_arn" { value = aws_kms_key.trust_root.arn }
output "audit_anchor_bucket" { value = aws_s3_bucket.anchor.bucket }
output "tombstone_bucket" { value = aws_s3_bucket.tombstones.bucket }
output "ci_role_arn" { value = try(aws_iam_role.ci[0].arn, null) }

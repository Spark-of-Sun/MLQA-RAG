# One IAM role per service, assumed by that service's Kubernetes service account only (IRSA, doc 9.2).
# No role below can schedule deletion of, disable, or change the policy of any key (doc 4.2, 12.5): those
# actions are never granted, and the key policies deny them to everyone but the two KeyGuard roles.

data "aws_iam_policy_document" "assume" {
  for_each = local.eks ? toset(local.services) : toset([])
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_host}:sub"
      values   = ["system:serviceaccount:${var.kubernetes_namespace}:${replace(each.key, "_", "-")}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider_host}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "service" {
  for_each             = local.eks ? toset(local.services) : toset([])
  name                 = "${local.prefix}-${replace(each.key, "_", "-")}"
  assume_role_policy   = data.aws_iam_policy_document.assume[each.key].json
  max_session_duration = 3600
}

# Cryptographic use of the per-organization keys: always with an encryption context, only for our aliases.
data "aws_iam_policy_document" "org_key_use" {
  statement {
    sid       = "UseOrganizationKeysWithContext"
    actions   = ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:ReEncrypt*", "kms:DescribeKey"]
    resources = ["arn:${local.partition}:kms:*:${local.account_id}:key/*"]
    condition {
      test     = "ForAnyValue:StringLike"
      variable = "kms:ResourceAliases"
      values   = ["alias/lmqa-org-*", "alias/lmqa-escrow-*"]
    }
    condition {
      test     = "Null"
      variable = "kms:EncryptionContextKeys"
      values   = ["false"]
    }
  }
}

data "aws_iam_policy_document" "sign_with_trust_root" {
  statement {
    sid       = "SignCertificatesOnly"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [aws_kms_key.trust_root.arn]
  }
}

# Verifying only: services need the public key to check certificates.
data "aws_iam_policy_document" "verify_trust_root" {
  statement {
    sid       = "ReadTrustRootPublicKey"
    actions   = ["kms:GetPublicKey", "kms:DescribeKey"]
    resources = [aws_kms_key.trust_root.arn]
  }
}

data "aws_iam_policy_document" "create_org_keys" {
  statement {
    sid       = "ProvisionOrganizationKeys"
    actions   = ["kms:CreateKey", "kms:CreateAlias", "kms:TagResource", "kms:ReplicateKey", "kms:EnableKeyRotation", "kms:PutKeyPolicy"]
    resources = ["*"]
    # PutKeyPolicy is allowed ONLY here and only at creation; the key policy of every key then denies it to all but key-admin.
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["lmqa"]
    }
  }
}

data "aws_iam_policy_document" "documents_bucket" {
  statement {
    sid       = "ObjectStore"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:DeleteObjectVersion", "s3:ListBucket", "s3:ListBucketVersions", "s3:GetBucketVersioning"]
    resources = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
  }
  statement {
    sid       = "ServerSideEncryptionKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.storage.arn]
  }
}

data "aws_iam_policy_document" "anchor_bucket" {
  statement {
    sid       = "WriteAnchors"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:PutObjectRetention"]
    resources = [aws_s3_bucket.worm["audit-anchors"].arn, "${aws_s3_bucket.worm["audit-anchors"].arn}/*"]
  }
  statement {
    sid       = "ServerSideEncryptionKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.storage.arn]
  }
}

data "aws_iam_policy_document" "tombstone_bucket" {
  statement {
    sid       = "WriteTombstones"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.worm["tombstones"].arn, "${aws_s3_bucket.worm["tombstones"].arn}/*"]
  }
  statement {
    sid       = "ServerSideEncryptionKey"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt"]
    resources = [aws_kms_key.storage.arn]
  }
}

locals {
  # service -> the policy documents it receives. The Gateway holds NO decrypt capability (doc 4.2).
  grants = {
    gateway            = [data.aws_iam_policy_document.sign_with_trust_root.json]
    citation_validator = [data.aws_iam_policy_document.org_key_use.json, data.aws_iam_policy_document.sign_with_trust_root.json]
    identity           = [data.aws_iam_policy_document.org_key_use.json, data.aws_iam_policy_document.create_org_keys.json, data.aws_iam_policy_document.verify_trust_root.json, data.aws_iam_policy_document.tombstone_bucket.json]
    ingestion          = [data.aws_iam_policy_document.org_key_use.json, data.aws_iam_policy_document.documents_bucket.json, data.aws_iam_policy_document.verify_trust_root.json, data.aws_iam_policy_document.tombstone_bucket.json]
    retrieval          = [data.aws_iam_policy_document.org_key_use.json, data.aws_iam_policy_document.verify_trust_root.json]
    generation         = [data.aws_iam_policy_document.org_key_use.json, data.aws_iam_policy_document.verify_trust_root.json]
    audit              = [data.aws_iam_policy_document.org_key_use.json, data.aws_iam_policy_document.anchor_bucket.json, data.aws_iam_policy_document.verify_trust_root.json]
  }
}

resource "aws_iam_role_policy" "service" {
  for_each = local.eks ? { for pair in flatten([for svc, docs in local.grants : [for i, doc in docs : { key = "${svc}-${i}", svc = svc, doc = doc }]]) : pair.key => pair } : {}
  name     = each.key
  role     = aws_iam_role.service[each.value.svc].id
  policy   = each.value.doc
}

# ---- single_host mode (first staging run only) --------------------------------------------------------------
# One EC2 instance role for every service. Every service on the host can therefore use every grant above,
# EXCEPT that destruction of keys is still impossible (never granted, and the key policies deny it).
# Move to deployment_mode = "eks" before real customer data.

data "aws_iam_policy_document" "host_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  count                = local.eks ? 0 : 1
  name                 = "${local.prefix}-host"
  assume_role_policy   = data.aws_iam_policy_document.host_assume.json
  max_session_duration = 3600
}

resource "aws_iam_instance_profile" "host" {
  count = local.eks ? 0 : 1
  name  = "${local.prefix}-host"
  role  = aws_iam_role.host[0].name
}

resource "aws_iam_role_policy" "host" {
  for_each = local.eks ? {} : { for i, doc in distinct(flatten(values(local.grants))) : tostring(i) => doc }
  name     = "host-${each.key}"
  role     = aws_iam_role.host[0].id
  policy   = each.value
}

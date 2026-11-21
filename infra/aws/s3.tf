# Buckets (doc 12.3, 12.8): documents (application-encrypted objects), audit anchors and the tombstone
# ledger (Object Lock, compliance mode: nobody, not even the root user, can delete or shorten retention).

resource "aws_s3_bucket" "documents" {
  bucket = "${local.prefix}-documents-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.storage.arn
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  # The quarantine prefix holds plaintext uploads only until scanning and encryption finish (doc 12.3).
  rule {
    id     = "expire-quarantine"
    status = "Enabled"
    filter {
      prefix = "quarantine/"
    }
    expiration {
      days = 1
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
  # Backups and old versions are gone within 35 days, which bounds the window for small-scope deletions (doc 12.9).
  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 35
    }
  }
}

# Presigned PUT uploads come straight from the browser, so the bucket needs CORS for exactly our origin.
resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  cors_rule {
    allowed_origins = ["https://${var.domain}"]
    allowed_methods = ["PUT"]
    allowed_headers = ["content-type", "x-amz-checksum-sha256", "x-amz-sdk-checksum-algorithm"]
    expose_headers  = ["ETag"]
    max_age_seconds = 300
  }
}

resource "aws_s3_bucket_policy" "documents_tls_only" {
  bucket = aws_s3_bucket.documents.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---- Object Lock buckets: audit anchors and the tombstone ledger -------------------------------------------

resource "aws_s3_bucket" "worm" {
  for_each            = toset(["audit-anchors", "tombstones"])
  bucket              = "${local.prefix}-${each.key}-${local.account_id}"
  object_lock_enabled = true
}

resource "aws_s3_bucket_public_access_block" "worm" {
  for_each                = aws_s3_bucket.worm
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "worm" {
  for_each = aws_s3_bucket.worm
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "worm" {
  for_each = aws_s3_bucket.worm
  bucket   = each.value.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.storage.arn
    }
  }
}

resource "aws_s3_bucket_object_lock_configuration" "worm" {
  for_each = aws_s3_bucket.worm
  bucket   = each.value.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.anchor_retention_days
    }
  }
  depends_on = [aws_s3_bucket_versioning.worm]
}

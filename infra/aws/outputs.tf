output "trust_root_key_id" {
  description = "Set as KMS_TRUST_ROOT_ID for the gateway, the validator and every verifying service."
  value       = aws_kms_key.trust_root.key_id
}

output "documents_bucket" {
  description = "Set as OBJECT_STORE_BUCKET."
  value       = aws_s3_bucket.documents.bucket
}

output "audit_anchor_bucket" {
  value = aws_s3_bucket.worm["audit-anchors"].bucket
}

output "tombstone_bucket" {
  value = aws_s3_bucket.worm["tombstones"].bucket
}

output "service_role_arns" {
  description = "Annotate each Kubernetes service account with its role (eks.amazonaws.com/role-arn). Empty in single_host mode."
  value       = { for name, role in aws_iam_role.service : name => role.arn }
}

output "host_instance_profile" {
  description = "Attach to the single EC2 host (deployment_mode = single_host)."
  value       = local.eks ? null : aws_iam_instance_profile.host[0].name
}

output "ci_role_arn" {
  description = "The role GitHub Actions assumes through OIDC to push images."
  value       = aws_iam_role.ci.arn
}

output "image_repositories" {
  value = { for name, repo in aws_ecr_repository.image : name => repo.repository_url }
}

output "keyguard_alert_topic" {
  value = aws_sns_topic.keyguard.arn
}

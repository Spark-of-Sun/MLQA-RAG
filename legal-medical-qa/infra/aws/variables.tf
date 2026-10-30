variable "region" {
  description = "Primary AWS Region."
  type        = string
  default     = "us-east-1"
}

variable "dr_region" {
  description = "Disaster-recovery Region (multi-Region key replicas, cross-Region copies)."
  type        = string
  default     = "us-west-2"
}

variable "environment" {
  description = "staging or production. Production keys always use the 30 day deletion window."
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "domain" {
  description = "The public domain the browser uses (CORS for presigned uploads)."
  type        = string
  default     = "onekami.site"
}

variable "keyguard_destroyer_role_arn" {
  description = "The ONLY role that may schedule or disable a key, and only through the KeyGuard workflow (two approvers, doc 12.5)."
  type        = string
}

variable "key_admin_role_arn" {
  description = "The ONLY role that may change a key policy (MFA and a change ticket)."
  type        = string
}

variable "security_oncall_email" {
  description = "Receives the page when a key deletion, disable or key-policy event occurs (within 60 seconds)."
  type        = string
}

variable "deployment_mode" {
  description = "eks: one least-privilege role per service (IRSA), the production shape. single_host: ONE instance role for every service on one EC2 host, for a first staging run only (it is a privilege compromise: any service can use every grant)."
  type        = string
  default     = "eks"
  validation {
    condition     = contains(["eks", "single_host"], var.deployment_mode)
    error_message = "deployment_mode must be eks or single_host."
  }
}

variable "eks_oidc_provider_arn" {
  description = "ARN of the cluster's IAM OIDC provider (IRSA). Required when deployment_mode = eks."
  type        = string
  default     = ""
}

variable "eks_oidc_provider_host" {
  description = "Host of the OIDC provider, e.g. oidc.eks.us-east-1.amazonaws.com/id/EXAMPLE. Required when deployment_mode = eks."
  type        = string
  default     = ""
}

variable "kubernetes_namespace" {
  type    = string
  default = "lmqa"
}

variable "github_repository" {
  description = "owner/name of the repository whose CI may push images (GitHub OIDC; no static keys)."
  type        = string
  default     = "onekami/legal-medical-qa"
}

variable "anchor_retention_days" {
  description = "Object Lock compliance retention for audit anchors and the tombstone ledger (about seven years)."
  type        = number
  default     = 2555
}

terraform {
  required_version = ">= 1.9"
  required_providers {
    auth0 = {
      source  = "auth0/auth0"
      version = "~> 1.59"
    }
  }
}

# Configure with AUTH0_DOMAIN, AUTH0_CLIENT_ID and AUTH0_CLIENT_SECRET of a *management* M2M application
# (used only by this tofu run, never by the platform). One tenant per environment: dev, ci, staging, prod.
provider "auth0" {}

variable "domain" {
  description = "Public domain of the web application."
  type        = string
  default     = "onekami.site"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "ci", "staging", "prod"], var.environment)
    error_message = "environment must be dev, ci, staging or prod."
  }
}

variable "app_base_url" {
  description = "Exact base URL of the frontend (callbacks and logout URLs match it exactly)."
  type        = string
  default     = "https://onekami.site"
}

variable "claims_namespace" {
  type    = string
  default = "https://claims.onekami.site"
}

variable "blocked_email_domains" {
  description = "Disposable-email domains refused at sign-up (pre-user-registration Action)."
  type        = list(string)
  default     = ["mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com", "yopmail.com", "trashmail.com"]
}

locals {
  api_main       = "https://api.${var.domain}"
  api_onboarding = "https://onboarding.${var.domain}"
}

terraform {
  required_version = ">= 1.9"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.28"
    }
  }
}

# The API token comes from CLOUDFLARE_API_TOKEN (never from code). Scope it to this zone only:
# Zone:DNS:Edit, Zone:Zone Settings:Edit, Zone:Firewall Services:Edit (or Zone WAF:Edit).
provider "cloudflare" {}

variable "domain" {
  type    = string
  default = "onekami.site"
}

variable "account_id" {
  description = "Cloudflare account ID that owns the zone."
  type        = string
}

variable "origin_hostname" {
  description = "Public hostname of the AWS load balancer in front of the frontend, e.g. k8s-lmqa-xxxx.us-east-1.elb.amazonaws.com."
  type        = string
}

variable "auth0_custom_domain_target" {
  description = "The CNAME target Auth0 gives you for the custom login domain login.<domain>. Leave empty until the Auth0 custom domain exists."
  type        = string
  default     = ""
}

variable "spf_record" {
  description = "SPF text for the apex if mail is sent from this domain (e.g. 'v=spf1 include:amazonses.com -all'). Empty creates nothing."
  type        = string
  default     = ""
}

variable "dmarc_record" {
  type    = string
  default = "v=DMARC1; p=quarantine; rua=mailto:dmarc@onekami.site"
}

data "cloudflare_zone" "site" {
  filter = {
    name    = var.domain
    account = { id = var.account_id }
  }
}

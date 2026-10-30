terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.71"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { project = "lmqa", environment = var.environment, managed_by = "opentofu" }
  }
}

# The disaster-recovery Region: multi-Region key replicas and the cross-Region anchor copy (doc 12.8).
provider "aws" {
  alias  = "dr"
  region = var.dr_region
  default_tags {
    tags = { project = "lmqa", environment = var.environment, managed_by = "opentofu" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  prefix     = "lmqa-${var.environment}"
  eks        = var.deployment_mode == "eks"
  services   = ["gateway", "identity", "ingestion", "retrieval", "generation", "citation_validator", "audit"]
}

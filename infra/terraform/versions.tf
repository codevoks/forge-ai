# Phase 13: reviewable AWS deployment design. This configuration is authored,
# formatted, and validated (see docs/architecture/deployment-hardening.md) but
# never applied by any default command. No backend is configured, so
# `terraform init` never requires a pre-existing S3/DynamoDB state store —
# the zero-cost local demo needs zero AWS resources to exist. A production
# deployment would configure a remote backend (S3 + DynamoDB lock table)
# separately, only when a real deployment is explicitly approved.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "forge-ai"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

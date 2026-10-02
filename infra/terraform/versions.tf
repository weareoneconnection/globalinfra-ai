terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Intentionally not configured here: point this at your own remote state
  # backend (S3 + DynamoDB lock table, Terraform Cloud, etc.) before running
  # `terraform init` against a real environment. A local/default backend is
  # fine for `terraform validate` and reviewing `terraform plan` only.
  # backend "s3" {}
}

provider "aws" {
  region = var.region
}

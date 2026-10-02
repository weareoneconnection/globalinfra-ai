# Reference starter for the "Pilot" stage of docs/ARCHITECTURE.md's
# deployment evolution (managed PostgreSQL/Redis/object storage, private
# networking, ahead of SSO + Kubernetes in the "Enterprise" stage).
#
# This is a worked AWS example, not a certified production baseline: review
# sizing, IAM boundaries, backup windows, multi-AZ/DR posture and the single
# NAT gateway below against your own compliance requirements before you
# `terraform apply` this anywhere real. Equivalent Azure (VNet/Azure
# Database for PostgreSQL/Azure Cache for Redis/Key Vault) or GCP (VPC/Cloud
# SQL/Memorystore/Cloud KMS) resources exist for every block here; swap the
# provider and resources if that is your target cloud.

locals {
  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "${var.project_name}-${var.environment}"
  cidr = var.vpc_cidr

  azs             = var.availability_zones
  private_subnets = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i)]
  public_subnets  = [for i, az in var.availability_zones : cidrsubnet(var.vpc_cidr, 4, i + 8)]

  enable_nat_gateway   = true
  single_nat_gateway   = true # one shared NAT keeps this cheap to try; use one-per-AZ for real pilot/production resilience
  enable_dns_hostnames = true

  tags = local.tags
}

resource "aws_kms_key" "data" {
  description             = "${var.project_name}-${var.environment} data-at-rest encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.tags
}

resource "aws_s3_bucket" "documents" {
  bucket = "${var.project_name}-${var.environment}-documents"
  tags   = local.tags
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.data.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_security_group" "postgres" {
  name_prefix = "${var.project_name}-${var.environment}-postgres-"
  description = "Allow Postgres only from inside this environment's VPC"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "Postgres from inside the VPC only"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

module "postgres" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"

  identifier = "${var.project_name}-${var.environment}"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = 50
  storage_encrypted = true
  kms_key_id        = aws_kms_key.data.arn

  db_name                     = "globalinfra"
  username                    = "globalinfra"
  port                        = 5432
  manage_master_user_password = true

  multi_az               = true
  create_db_subnet_group = true
  subnet_ids             = module.vpc.private_subnets
  vpc_security_group_ids = [aws_security_group.postgres.id]

  backup_retention_period = 7
  deletion_protection     = true

  tags = local.tags
}

resource "aws_security_group" "redis" {
  name_prefix = "${var.project_name}-${var.environment}-redis-"
  description = "Allow Redis only from inside this environment's VPC"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "Redis from inside the VPC only"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.tags
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.project_name}-${var.environment}-redis"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "${var.project_name}-${var.environment}-redis"
  description                = "GlobalInfra AI cache / session store"
  engine                     = "redis"
  node_type                  = var.redis_node_type
  num_cache_clusters         = 2
  automatic_failover_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  tags = local.tags
}

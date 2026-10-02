output "vpc_id" {
  description = "ID of the environment VPC."
  value       = module.vpc.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (API/worker/cache/database placement)."
  value       = module.vpc.private_subnets
}

output "documents_bucket" {
  description = "S3 bucket for uploaded project documents (encrypted, not publicly accessible)."
  value       = aws_s3_bucket.documents.bucket
}

output "kms_key_arn" {
  description = "KMS key ARN used for data-at-rest encryption (S3, RDS)."
  value       = aws_kms_key.data.arn
}

output "postgres_endpoint" {
  description = "Managed PostgreSQL connection endpoint."
  value       = module.postgres.db_instance_endpoint
  sensitive   = true
}

output "postgres_master_user_secret_arn" {
  description = "Secrets Manager ARN holding the generated master password (manage_master_user_password = true)."
  value       = module.postgres.db_instance_master_user_secret_arn
  sensitive   = true
}

output "redis_primary_endpoint" {
  description = "Primary endpoint for the managed Redis replication group."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  sensitive   = true
}

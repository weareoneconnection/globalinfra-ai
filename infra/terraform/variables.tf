variable "project_name" {
  description = "Short name used to prefix all resources, e.g. \"globalinfra\"."
  type        = string
  default     = "globalinfra"
}

variable "environment" {
  description = "Deployment environment name, e.g. \"pilot\" or \"staging\". Keep production in its own state/account."
  type        = string
  default     = "pilot"
}

variable "region" {
  description = "AWS region for this environment. Swap the provider block in versions.tf (and the resources in main.tf) for Azure/GCP equivalents if that is your target cloud."
  type        = string
  default     = "ap-southeast-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the environment VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zones" {
  description = "AZs to spread private/public subnets across. Three AZs is the minimum for a realistic pilot; adjust to match the chosen region."
  type        = list(string)
  default     = ["ap-southeast-1a", "ap-southeast-1b", "ap-southeast-1c"]
}

variable "db_instance_class" {
  description = "RDS instance class for the managed PostgreSQL database."
  type        = string
  default     = "db.t4g.medium"
}

variable "redis_node_type" {
  description = "ElastiCache node type for the managed Redis replication group."
  type        = string
  default     = "cache.t4g.small"
}

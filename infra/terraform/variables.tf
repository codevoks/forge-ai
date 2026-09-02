variable "aws_region" {
  description = "AWS region for the Forge deployment."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name (e.g. staging, production). Never 'local' — the zero-cost path never provisions AWS."
  type        = string
  default     = "staging"

  validation {
    condition     = var.environment != "local"
    error_message = "The zero-cost local profile must never be provisioned against AWS; choose staging or production."
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the Forge VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "availability_zone_count" {
  description = "Number of availability zones to spread public/private subnets across."
  type        = number
  default     = 2
}

variable "database_instance_class" {
  description = "RDS instance class for the authoritative Postgres database."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_allocated_storage_gb" {
  description = "Initial RDS storage in GiB."
  type        = number
  default     = 20
}

variable "redis_node_type" {
  description = "ElastiCache node type for queue/coordination Redis."
  type        = string
  default     = "cache.t4g.micro"
}

variable "api_container_image" {
  description = "Container image reference for the API service (built by CI, pushed to a registry the pipeline controls)."
  type        = string
}

variable "worker_container_image" {
  description = "Container image reference for the worker service."
  type        = string
}

variable "api_desired_count" {
  description = "Desired ECS task count for the API service."
  type        = number
  default     = 2
}

variable "worker_desired_count" {
  description = "Desired ECS task count for the worker service."
  type        = number
  default     = 2
}

variable "certificate_arn" {
  description = "ACM certificate ARN for the public HTTPS listener. Provisioned and validated out-of-band before deployment; never created by this configuration."
  type        = string
  default     = ""
}

output "alb_dns_name" {
  description = "Public DNS name for the Forge load balancer."
  value       = aws_lb.forge.dns_name
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.forge.name
}

output "database_endpoint" {
  description = "RDS endpoint (host:port). Credentials live only in Secrets Manager, never in Terraform output."
  value       = aws_db_instance.forge.endpoint
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.forge.primary_endpoint_address
}

output "database_secret_arn" {
  description = "Secrets Manager ARN holding RDS credentials; workloads resolve this via their scoped execution role, never a static key."
  value       = aws_secretsmanager_secret.database.arn
}

# Redis is disposable coordination only (D-002) — losing it delays work but
# never loses acknowledged workflow state, so a single-node replication
# group is an acceptable, explicit tradeoff for cost in non-production
# environments; production enables automatic failover.

resource "aws_elasticache_subnet_group" "forge" {
  name       = "forge-${var.environment}-redis"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "forge" {
  replication_group_id       = "forge-${var.environment}"
  description                = "Forge queue/coordination Redis (disposable; not authoritative)"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.environment == "production" ? 2 : 1
  automatic_failover_enabled = var.environment == "production"
  port                       = 6379

  subnet_group_name  = aws_elasticache_subnet_group.forge.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  tags = { Name = "forge-${var.environment}-redis" }
}

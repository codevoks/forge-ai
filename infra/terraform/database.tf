# RDS is authoritative (D-002); it is never publicly reachable, is
# encrypted at rest with a customer-managed KMS key, and takes automated
# encrypted backups. The master password is generated and stored only in
# Secrets Manager, never in Terraform state as plaintext output.

resource "aws_kms_key" "database" {
  description             = "Forge ${var.environment} RDS encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_db_subnet_group" "forge" {
  name       = "forge-${var.environment}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "forge-${var.environment}-db-subnet-group" }
}

resource "random_password" "database_master" {
  length  = 32
  special = false
}

resource "aws_db_instance" "forge" {
  identifier     = "forge-${var.environment}"
  engine         = "postgres"
  engine_version = "17"
  instance_class = var.database_instance_class

  allocated_storage     = var.database_allocated_storage_gb
  max_allocated_storage = var.database_allocated_storage_gb * 5
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.database.arn

  db_name  = "forge"
  username = "forge_admin"
  password = random_password.database_master.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.forge.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false

  multi_az                     = var.environment == "production"
  backup_retention_period      = 14
  backup_window                = "03:00-04:00"
  maintenance_window           = "mon:04:30-mon:05:30"
  copy_tags_to_snapshot        = true
  deletion_protection          = var.environment == "production"
  skip_final_snapshot          = var.environment != "production"
  final_snapshot_identifier    = var.environment == "production" ? "forge-${var.environment}-final" : null
  performance_insights_enabled = true

  tags = { Name = "forge-${var.environment}-postgres" }
}

resource "aws_secretsmanager_secret" "database" {
  name        = "forge/${var.environment}/database"
  description = "Forge RDS master credentials; workloads assume a scoped IAM role to read this, never a static key."
  kms_key_id  = aws_kms_key.database.arn
}

resource "aws_secretsmanager_secret_version" "database" {
  secret_id = aws_secretsmanager_secret.database.id
  secret_string = jsonencode({
    engine   = "postgres"
    host     = aws_db_instance.forge.address
    port     = aws_db_instance.forge.port
    dbname   = aws_db_instance.forge.db_name
    username = aws_db_instance.forge.username
    password = random_password.database_master.result
  })
}

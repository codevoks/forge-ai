# Private networking: RDS, ElastiCache, and ECS tasks live in private
# subnets with no public IPs; only the ALB is internet-facing. Egress from
# private subnets goes through a NAT gateway so workers/API can still reach
# outbound HTTPS (model/tool providers, MCP servers) under explicit
# per-integration policy, never a wide-open route.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "forge" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "forge-${var.environment}-vpc" }
}

resource "aws_internet_gateway" "forge" {
  vpc_id = aws_vpc.forge.id
  tags   = { Name = "forge-${var.environment}-igw" }
}

resource "aws_subnet" "public" {
  count                   = var.availability_zone_count
  vpc_id                  = aws_vpc.forge.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false

  tags = { Name = "forge-${var.environment}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = var.availability_zone_count
  vpc_id            = aws_vpc.forge.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + var.availability_zone_count)
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = { Name = "forge-${var.environment}-private-${count.index}" }
}

resource "aws_eip" "nat" {
  count  = var.availability_zone_count
  domain = "vpc"
  tags   = { Name = "forge-${var.environment}-nat-eip-${count.index}" }
}

resource "aws_nat_gateway" "forge" {
  count         = var.availability_zone_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = { Name = "forge-${var.environment}-nat-${count.index}" }

  depends_on = [aws_internet_gateway.forge]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.forge.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.forge.id
  }

  tags = { Name = "forge-${var.environment}-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = var.availability_zone_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = var.availability_zone_count
  vpc_id = aws_vpc.forge.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.forge[count.index].id
  }

  tags = { Name = "forge-${var.environment}-private-rt-${count.index}" }
}

resource "aws_route_table_association" "private" {
  count          = var.availability_zone_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

resource "aws_security_group" "alb" {
  name        = "forge-${var.environment}-alb"
  description = "Public HTTPS entry point only; no inbound from anywhere else."
  vpc_id      = aws_vpc.forge.id

  ingress {
    description = "HTTPS from the internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "To ECS tasks only"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = { Name = "forge-${var.environment}-alb-sg" }
}

resource "aws_security_group" "ecs_tasks" {
  name        = "forge-${var.environment}-ecs-tasks"
  description = "API/worker tasks: inbound only from the ALB, outbound for DB/Redis/egress via NAT."
  vpc_id      = aws_vpc.forge.id

  ingress {
    description     = "API port from the ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Outbound (DB, Redis, egress-controlled third parties via NAT)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "forge-${var.environment}-ecs-tasks-sg" }
}

resource "aws_security_group" "database" {
  name        = "forge-${var.environment}-database"
  description = "RDS Postgres: inbound only from ECS tasks, no public reachability."
  vpc_id      = aws_vpc.forge.id

  ingress {
    description     = "Postgres from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = { Name = "forge-${var.environment}-database-sg" }
}

resource "aws_security_group" "redis" {
  name        = "forge-${var.environment}-redis"
  description = "ElastiCache Redis: inbound only from ECS tasks, no public reachability."
  vpc_id      = aws_vpc.forge.id

  ingress {
    description     = "Redis from ECS tasks"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  tags = { Name = "forge-${var.environment}-redis-sg" }
}

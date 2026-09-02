# ECS Fargate: no EC2 hosts to patch, tasks run in private subnets with no
# public IP, and only the ALB (a separate, narrowly-scoped security group)
# can reach them. Container images are referenced by digest/tag pushed by
# CI, never built here.
#
# `forge_api.config.Settings` reads one FORGE_DATABASE_URL DSN string, not
# separate host/username/password variables; a production entrypoint would
# assemble the DSN from these injected secret fields (or Settings would gain
# a DSN-assembly path) before the process starts. That adapter is
# intentionally not built here — this configuration is a reviewable design,
# not a wired production deployment.

resource "aws_cloudwatch_log_group" "api" {
  name              = "/forge/${var.environment}/api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/forge/${var.environment}/worker"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "forge" {
  name = "forge-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "forge-${var.environment}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_container_image
      essential = true
      portMappings = [
        { containerPort = 8000, protocol = "tcp" }
      ]
      readonlyRootFilesystem = true
      user                   = "10001:10001"
      environment = [
        { name = "FORGE_ENVIRONMENT", value = var.environment },
        { name = "FORGE_EXTERNAL_INTEGRATIONS", value = "disabled" }
      ]
      secrets = [
        {
          name      = "FORGE_DATABASE_HOST"
          valueFrom = "${aws_secretsmanager_secret.database.arn}:host::"
        },
        {
          name      = "FORGE_DATABASE_USERNAME"
          valueFrom = "${aws_secretsmanager_secret.database.arn}:username::"
        },
        {
          name      = "FORGE_DATABASE_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.database.arn}:password::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.api.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "forge-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name                   = "worker"
      image                  = var.worker_container_image
      essential              = true
      readonlyRootFilesystem = true
      user                   = "10001:10001"
      environment = [
        { name = "FORGE_ENVIRONMENT", value = var.environment },
        { name = "FORGE_EXTERNAL_INTEGRATIONS", value = "disabled" }
      ]
      secrets = [
        {
          name      = "FORGE_DATABASE_HOST"
          valueFrom = "${aws_secretsmanager_secret.database.arn}:host::"
        },
        {
          name      = "FORGE_DATABASE_USERNAME"
          valueFrom = "${aws_secretsmanager_secret.database.arn}:username::"
        },
        {
          name      = "FORGE_DATABASE_PASSWORD"
          valueFrom = "${aws_secretsmanager_secret.database.arn}:password::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_lb" "forge" {
  name                       = "forge-${var.environment}"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = aws_subnet.public[*].id
  drop_invalid_header_fields = true

  tags = { Name = "forge-${var.environment}-alb" }
}

resource "aws_lb_target_group" "api" {
  name        = "forge-${var.environment}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.forge.id
  target_type = "ip"

  health_check {
    path                = "/v1/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 15
    timeout             = 5
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.forge.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.forge.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_ecs_service" "api" {
  name            = "forge-${var.environment}-api"
  cluster         = aws_ecs_cluster.forge.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.ecs_tasks.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name            = "forge-${var.environment}-worker"
  cluster         = aws_ecs_cluster.forge.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.ecs_tasks.id]
  }
}

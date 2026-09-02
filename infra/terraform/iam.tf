# Least-privilege workload identities. The execution role only pulls
# images, writes logs, and reads the specific secrets this deployment
# creates (no wildcard secretsmanager:* — Q-007/D-007's "code owns
# authorization" principle extends to infrastructure IAM too). The task
# role is intentionally empty until a real AWS SDK call from application
# code justifies a permission; Forge does not call AWS APIs today.

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "forge-${var.environment}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "ecs_task_execution_secrets" {
  statement {
    sid       = "ReadOnlyForgeSecretsThisDeploymentOwns"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.database.arn]
  }
  statement {
    sid       = "DecryptWithForgeDatabaseKmsKeyOnly"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.database.arn]
  }
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name   = "forge-${var.environment}-secrets-read"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_task_execution_secrets.json
}

resource "aws_iam_role" "ecs_task" {
  name               = "forge-${var.environment}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

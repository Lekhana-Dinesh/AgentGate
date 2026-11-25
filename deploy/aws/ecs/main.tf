data "aws_iam_policy_document" "ecs_task_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "task_runtime_app" {
  statement {
    sid = "PayloadKmsAccess"

    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:GenerateDataKey",
    ]

    resources = [var.payload_kms_key_arn]
  }

  dynamic "statement" {
    for_each = length(local.checkpoint_bucket_resources) == 0 ? [] : [1]

    content {
      sid = "AuditCheckpointObjectWriteRead"

      actions = [
        "s3:GetObject",
        "s3:PutObject",
      ]

      resources = [local.checkpoint_bucket_resources[1]]
    }
  }

  dynamic "statement" {
    for_each = length(local.checkpoint_bucket_resources) == 0 ? [] : [1]

    content {
      sid = "AuditCheckpointBucketList"

      actions = [
        "s3:ListBucket",
      ]

      resources = [local.checkpoint_bucket_resources[0]]
    }
  }
}

data "aws_iam_policy_document" "execution_secrets" {
  dynamic "statement" {
    for_each = length(local.all_secret_arns) == 0 ? [] : [1]

    content {
      sid = "ResolveInjectedSecrets"

      actions = [
        "secretsmanager:GetSecretValue",
        "ssm:GetParameter",
        "ssm:GetParameters",
      ]

      resources = local.all_secret_arns
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "task_execution_secrets" {
  count  = length(local.all_secret_arns) == 0 ? 0 : 1
  name   = "${var.name_prefix}-ecs-execution-secrets"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

resource "aws_iam_role" "task_runtime_app" {
  name               = "${var.name_prefix}-ecs-app-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

resource "aws_iam_role_policy" "task_runtime_app" {
  name   = "${var.name_prefix}-ecs-app-task-runtime"
  role   = aws_iam_role.task_runtime_app.id
  policy = data.aws_iam_policy_document.task_runtime_app.json
}

resource "aws_iam_role" "task_runtime_web" {
  name               = "${var.name_prefix}-ecs-web-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume_role.json
  tags               = local.tags
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name_prefix}/api"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/ecs/${var.name_prefix}/web"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.name_prefix}/worker"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "scheduler" {
  name              = "/ecs/${var.name_prefix}/scheduler"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/ecs/${var.name_prefix}/migrate"
  retention_in_days = var.cloudwatch_log_retention_days
  tags              = local.tags
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.tags
}

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "ALB ingress for AgentGate web and API services"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each          = toset(var.alb_ingress_cidrs)
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  description       = "Allow HTTP ingress to the ALB"
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  for_each          = var.alb_certificate_arn == null ? toset([]) : toset(var.alb_ingress_cidrs)
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Allow HTTPS ingress to the ALB"
}

resource "aws_vpc_security_group_egress_rule" "alb_all" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow outbound ALB traffic"
}

resource "aws_security_group" "api_tasks" {
  name        = "${var.name_prefix}-api-tasks"
  description = "Security group for AgentGate API ECS tasks"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_security_group" "web_tasks" {
  name        = "${var.name_prefix}-web-tasks"
  description = "Security group for AgentGate web ECS tasks"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_security_group" "background_tasks" {
  name        = "${var.name_prefix}-background-tasks"
  description = "Security group for AgentGate worker, scheduler, and migration ECS tasks"
  vpc_id      = var.vpc_id
  tags        = local.tags
}

resource "aws_vpc_security_group_ingress_rule" "api_tasks_from_alb" {
  security_group_id            = aws_security_group.api_tasks.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  description                  = "Allow ALB traffic to the API task"
}

resource "aws_vpc_security_group_ingress_rule" "web_tasks_from_alb" {
  security_group_id            = aws_security_group.web_tasks.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 3000
  to_port                      = 3000
  ip_protocol                  = "tcp"
  description                  = "Allow ALB traffic to the web task"
}

resource "aws_vpc_security_group_egress_rule" "api_tasks_all" {
  security_group_id = aws_security_group.api_tasks.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow API ECS tasks to reach external dependencies"
}

resource "aws_vpc_security_group_egress_rule" "web_tasks_all" {
  security_group_id = aws_security_group.web_tasks.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow web ECS tasks to reach external dependencies"
}

resource "aws_vpc_security_group_egress_rule" "background_tasks_all" {
  security_group_id = aws_security_group.background_tasks.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "Allow background ECS tasks to reach external dependencies"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_api_tasks" {
  count                        = var.rds_security_group_id == null ? 0 : 1
  security_group_id            = var.rds_security_group_id
  referenced_security_group_id = aws_security_group.api_tasks.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Allow AgentGate API ECS tasks to reach RDS PostgreSQL"
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_background_tasks" {
  count                        = var.rds_security_group_id == null ? 0 : 1
  security_group_id            = var.rds_security_group_id
  referenced_security_group_id = aws_security_group.background_tasks.id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  description                  = "Allow AgentGate background ECS tasks to reach RDS PostgreSQL"
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_api_tasks" {
  count                        = var.redis_security_group_id == null ? 0 : 1
  security_group_id            = var.redis_security_group_id
  referenced_security_group_id = aws_security_group.api_tasks.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
  description                  = "Allow AgentGate API ECS tasks to reach Redis"
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_background_tasks" {
  count                        = var.redis_security_group_id == null ? 0 : 1
  security_group_id            = var.redis_security_group_id
  referenced_security_group_id = aws_security_group.background_tasks.id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
  description                  = "Allow AgentGate background ECS tasks to reach Redis"
}

resource "aws_lb" "this" {
  name               = substr("${var.name_prefix}-alb", 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.alb_subnet_ids
  idle_timeout       = 60
  tags               = local.tags
}

resource "aws_lb_target_group" "api" {
  name        = substr("${var.name_prefix}-api-tg", 0, 32)
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/ready"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
  }

  tags = local.tags
}

resource "aws_lb_target_group" "web" {
  name        = substr("${var.name_prefix}-web-tg", 0, 32)
  port        = 3000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    path                = "/login"
    matcher             = "200-399"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
  }

  tags = local.tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.alb_certificate_arn == null ? "forward" : "redirect"

    dynamic "redirect" {
      for_each = var.alb_certificate_arn == null ? [] : [1]

      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    dynamic "forward" {
      for_each = var.alb_certificate_arn == null ? [1] : []

      content {
        target_group {
          arn = aws_lb_target_group.web.arn
        }
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.alb_certificate_arn == null ? 0 : 1
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.alb_certificate_arn

  default_action {
    type = "forward"

    target_group_arn = aws_lb_target_group.web.arn
  }
}

locals {
  routing_listener_arn = var.alb_certificate_arn == null ? aws_lb_listener.http.arn : aws_lb_listener.https[0].arn
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = local.routing_listener_arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    host_header {
      values = [var.public_api_host]
    }
  }
}

resource "aws_lb_listener_rule" "web" {
  listener_arn = local.routing_listener_arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }

  condition {
    host_header {
      values = [var.public_app_host]
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_runtime_app.arn

  container_definitions = jsonencode([
    {
      name      = "api"
      image     = var.api_image_uri
      essential = true
      command   = ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        for name, value in local.api_env_map : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, arn in local.api_secret_map : {
          name      = name
          valueFrom = arn
        } if arn != null && trimspace(arn) != ""
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready')\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${var.name_prefix}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.web_cpu)
  memory                   = tostring(var.web_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_runtime_web.arn

  container_definitions = jsonencode([
    {
      name      = "web"
      image     = var.web_image_uri
      essential = true
      command   = ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
      portMappings = [
        {
          containerPort = 3000
          hostPort      = 3000
          protocol      = "tcp"
        }
      ]
      environment = [
        for name, value in local.web_env_map : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, arn in local.web_secret_map : {
          name      = name
          valueFrom = arn
        } if arn != null && trimspace(arn) != ""
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.web.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "node -e \"fetch('http://127.0.0.1:3000/login').then((response)=>process.exit(response.ok?0:1)).catch(()=>process.exit(1))\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_runtime_app.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.api_image_uri
      essential = true
      command   = ["python", "-m", "app.worker"]
      environment = [
        for name, value in local.worker_env_map : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, arn in local.worker_secret_map : {
          name      = name
          valueFrom = arn
        } if arn != null && trimspace(arn) != ""
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"from pathlib import Path; import sys; data = Path('/proc/1/cmdline').read_bytes(); sys.exit(0 if b'app.worker' in data else 1)\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_task_definition" "scheduler" {
  count                    = var.enable_scheduler ? 1 : 0
  family                   = "${var.name_prefix}-scheduler"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.scheduler_cpu)
  memory                   = tostring(var.scheduler_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_runtime_app.arn

  container_definitions = jsonencode([
    {
      name      = "scheduler"
      image     = var.api_image_uri
      essential = true
      command   = ["python", "-m", "app.scheduler"]
      environment = [
        for name, value in local.scheduler_env_map : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, arn in local.scheduler_secret_map : {
          name      = name
          valueFrom = arn
        } if arn != null && trimspace(arn) != ""
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.scheduler.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"from pathlib import Path; import sys; data = Path('/proc/1/cmdline').read_bytes(); sys.exit(0 if b'app.scheduler' in data else 1)\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_task_definition" "migrate" {
  family                   = "${var.name_prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.migrate_cpu)
  memory                   = tostring(var.migrate_memory)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task_runtime_app.arn

  container_definitions = jsonencode([
    {
      name      = "migrate"
      image     = var.api_image_uri
      essential = true
      command   = ["python", "-m", "alembic", "upgrade", "head"]
      environment = [
        for name, value in local.api_env_map : {
          name  = name
          value = value
        }
      ]
      secrets = [
        for name, arn in local.api_secret_map : {
          name      = name
          valueFrom = arn
        } if arn != null && trimspace(arn) != ""
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.migrate.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])

  tags = local.tags
}

resource "aws_ecs_service" "api" {
  name                               = "${var.name_prefix}-api"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.api.arn
  desired_count                      = var.api_desired_count
  launch_type                        = "FARGATE"
  health_check_grace_period_seconds  = 60
  enable_execute_command             = false
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50

  network_configuration {
    assign_public_ip = var.assign_public_ip
    subnets          = var.service_subnet_ids
    security_groups  = concat([aws_security_group.api_tasks.id], var.ecs_task_additional_security_group_ids)
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http, aws_lb_target_group.api]
  tags       = local.tags
}

resource "aws_ecs_service" "web" {
  name                               = "${var.name_prefix}-web"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.web.arn
  desired_count                      = var.web_desired_count
  launch_type                        = "FARGATE"
  health_check_grace_period_seconds  = 60
  enable_execute_command             = false
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50

  network_configuration {
    assign_public_ip = var.assign_public_ip
    subnets          = var.service_subnet_ids
    security_groups  = concat([aws_security_group.web_tasks.id], var.ecs_task_additional_security_group_ids)
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 3000
  }

  depends_on = [aws_lb_listener.http, aws_lb_target_group.web]
  tags       = local.tags
}

resource "aws_ecs_service" "worker" {
  name                               = "${var.name_prefix}-worker"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.worker.arn
  desired_count                      = var.worker_desired_count
  launch_type                        = "FARGATE"
  enable_execute_command             = false
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50

  network_configuration {
    assign_public_ip = var.assign_public_ip
    subnets          = var.service_subnet_ids
    security_groups  = concat([aws_security_group.background_tasks.id], var.ecs_task_additional_security_group_ids)
  }

  tags = local.tags
}

resource "aws_ecs_service" "scheduler" {
  count                              = var.enable_scheduler ? 1 : 0
  name                               = "${var.name_prefix}-scheduler"
  cluster                            = aws_ecs_cluster.this.id
  task_definition                    = aws_ecs_task_definition.scheduler[0].arn
  desired_count                      = var.scheduler_desired_count
  launch_type                        = "FARGATE"
  enable_execute_command             = false
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50

  network_configuration {
    assign_public_ip = var.assign_public_ip
    subnets          = var.service_subnet_ids
    security_groups  = concat([aws_security_group.background_tasks.id], var.ecs_task_additional_security_group_ids)
  }

  tags = local.tags
}

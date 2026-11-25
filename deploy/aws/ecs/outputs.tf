output "ecs_cluster_name" {
  description = "Created ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "alb_dns_name" {
  description = "ALB DNS name for ingress testing before DNS cutover."
  value       = aws_lb.this.dns_name
}

output "alb_security_group_id" {
  description = "Security group ID attached to the ALB."
  value       = aws_security_group.alb.id
}

output "api_task_security_group_id" {
  description = "Security group ID attached to the API ECS service."
  value       = aws_security_group.api_tasks.id
}

output "web_task_security_group_id" {
  description = "Security group ID attached to the web ECS service."
  value       = aws_security_group.web_tasks.id
}

output "background_task_security_group_id" {
  description = "Security group ID attached to worker, scheduler, and migration ECS tasks."
  value       = aws_security_group.background_tasks.id
}

output "api_service_name" {
  description = "API ECS service name."
  value       = aws_ecs_service.api.name
}

output "web_service_name" {
  description = "Web ECS service name."
  value       = aws_ecs_service.web.name
}

output "worker_service_name" {
  description = "Worker ECS service name."
  value       = aws_ecs_service.worker.name
}

output "scheduler_service_name" {
  description = "Scheduler ECS service name when enabled."
  value       = var.enable_scheduler ? aws_ecs_service.scheduler[0].name : null
}

output "migration_task_definition_arn" {
  description = "Task definition ARN for the one-off migration task."
  value       = aws_ecs_task_definition.migrate.arn
}

output "task_execution_role_arn" {
  description = "Shared ECS task execution role ARN used for image pulls, logs, and secret resolution."
  value       = aws_iam_role.task_execution.arn
}

output "app_task_runtime_role_arn" {
  description = "Runtime IAM role ARN used by API, worker, scheduler, and migration tasks."
  value       = aws_iam_role.task_runtime_app.arn
}

output "web_task_runtime_role_arn" {
  description = "Runtime IAM role ARN used by the web task."
  value       = aws_iam_role.task_runtime_web.arn
}

output "migration_run_task_example" {
  description = "Example AWS CLI command shape for running the migration task."
  value = format(
    "aws ecs run-task --cluster %s --task-definition %s --launch-type FARGATE --network-configuration \"awsvpcConfiguration={subnets=[%s],securityGroups=[%s],assignPublicIp=%s}\"",
    aws_ecs_cluster.this.name,
    aws_ecs_task_definition.migrate.arn,
    join(",", formatlist("\"%s\"", var.service_subnet_ids)),
    join(",", formatlist("\"%s\"", concat([aws_security_group.background_tasks.id], var.ecs_task_additional_security_group_ids))),
    var.assign_public_ip ? "ENABLED" : "DISABLED",
  )
}

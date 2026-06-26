output "lambda_function_arn" {
  description = "Lambda 함수 ARN"
  value       = aws_lambda_function.alert.arn
}

output "eventbridge_rule_arn" {
  description = "EventBridge 규칙 ARN"
  value       = aws_cloudwatch_event_rule.s3_access_change.arn
}
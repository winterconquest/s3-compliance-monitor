variable "slack_webhook_url" {
  description = "Slack Incoming Webhook URL"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "lambda_function_name" {
  description = "Lambda 함수 이름"
  type        = string
  default     = "s3-public-access-alert"
}

variable "eventbridge_rule_name" {
  description = "EventBridge 규칙 이름"
  type        = string
  default     = "s3-public-access-block-rule"
}
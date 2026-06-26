provider "aws"{
    region = var.aws_region
}

# Lambda 코드를 zip으로
data "archive_file" "lambda_zip" {
    type        = "zip"
    source_file = "${path.module}/lambda/alert.py"
    output_path = "${path.module}/lambda_function.zip"
}

# Lambda IAM Role
resource "aws_iam_role" "lambda_role" {
    name = "${var.lambda_function_name}-role"

    assume_role_policy = jsonencode({
        Version = "2012-10-17"
        Statement = [
            {
                Effect = "Allow"
                Principal = {
                    Service = "lambda.amazonaws.com"
                }
                Action = "sts:AssumeRole"
            }
        ]
    })
}

# Lambda의 CloudWatch Logs 쓰기 권한
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda 함수
resource "aws_lambda_function" "alert" {
  function_name = var.lambda_function_name
  role          = aws_iam_role.lambda_role.arn

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  runtime = "python3.12"
  handler = "alert.lambda_handler"
  timeout = 10

  environment {
    variables = {
      SLACK_WEBHOOK_URL = var.slack_webhook_url
    }
  }
}

# EventBridge 규칙
resource "aws_cloudwatch_event_rule" "s3_access_change" {
  name        = var.eventbridge_rule_name
  description = "S3 퍼블릭 액세스 설정 변경 이벤트 감지"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["s3.amazonaws.com"]
      eventName   = ["PutBucketPublicAccessBlock"]
    }
  })
}


# EventBridge가 Lambda 호출
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.s3_access_change.name
  target_id = "SendToLambda"
  arn       = aws_lambda_function.alert.arn
}


# 6. EventBridge가 Lambda 호출할 권한
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alert.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.s3_access_change.arn
}
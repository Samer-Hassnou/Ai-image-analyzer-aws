########################################
# Terraform & Providers
########################################
terraform {
  required_version = ">= 1.4.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.9"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

########################################
# Variables
########################################
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefix for resource naming"
  type        = string
  default     = "imganlzrv2"
}

variable "lambda_memory_mb" {
  description = "Lambda memory size"
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout"
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CloudWatch log retention"
  type        = number
  default     = 14
}

variable "default_min_confidence" {
  description = "Default Rekognition MinConfidence when client doesn't send it"
  type        = number
  default     = 60
}

variable "uploads_expire_days" {
  description = "Auto-delete uploads after N days (S3 lifecycle)"
  type        = number
  default     = 1 # حذف بعد يوم واحد
}

# حدّ يومي (3 صور/اليوم)
variable "daily_quota_limit" {
  description = "Daily analyze limit per user"
  type        = number
  default     = 3
}

########################################
# Random suffix
########################################
resource "random_id" "suffix" {
  byte_length = 4
}

locals {
  suffix_hex = random_id.suffix.hex
  prefix     = var.project_name
}

########################################
# S3 Bucket (private + SSE + CORS + Lifecycle)
########################################
resource "aws_s3_bucket" "images" {
  bucket        = "${var.project_name}-images-${local.suffix_hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "block_public" {
  bucket                  = aws_s3_bucket.images.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sse" {
  bucket = aws_s3_bucket.images.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "cors" {
  bucket = aws_s3_bucket.images.id
  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "POST", "GET", "HEAD"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "lc" {
  bucket = aws_s3_bucket.images.id
  rule {
    id     = "expire-uploads"
    status = "Enabled"
    filter { prefix = "uploads/" }

    expiration {
      days = var.uploads_expire_days
    }
  }
}

########################################
# DynamoDB — quota 3/day with TTL (expires at UTC midnight)
########################################
resource "aws_dynamodb_table" "quota" {
  name         = "${local.prefix}-quota-${local.suffix_hex}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk" # user scope
  range_key    = "sk" # YYYY-MM-DD

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "expires"
    enabled        = true
  }

  tags = {
    App = local.prefix
  }
}

########################################
# IAM for Lambda
########################################
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-lambda-role-${local.suffix_hex}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Action    = "sts:AssumeRole",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_custom" {
  name = "${var.project_name}-lambda-custom-${local.suffix_hex}"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect : "Allow",
        Action : ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
        Resource : [
          aws_s3_bucket.images.arn,
          "${aws_s3_bucket.images.arn}/*"
        ]
      },
      {
        Effect : "Allow",
        Action : ["s3:ListBucket"],
        Resource : [aws_s3_bucket.images.arn]
      },
      {
        Effect : "Allow",
        Action : ["rekognition:DetectLabels", "rekognition:ListCollections"],
        Resource : "*"
      },
      # DynamoDB quota table
      {
        Effect : "Allow",
        Action : ["dynamodb:UpdateItem", "dynamodb:GetItem"],
        Resource : aws_dynamodb_table.quota.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

########################################
# CloudWatch Log Group
########################################
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${var.project_name}-fn-${local.suffix_hex}"
  retention_in_days = var.log_retention_days
}

########################################
# Lambda Function
########################################
resource "aws_lambda_function" "fn" {
  function_name    = "${var.project_name}-fn-${local.suffix_hex}"
  role             = aws_iam_role.lambda_exec.arn
  runtime          = "python3.11"
  handler          = "app.lambda_handler"
  filename         = "lambda.zip"
  source_code_hash = filebase64sha256("lambda.zip")

  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds

  environment {
    variables = {
      BUCKET_NAME            = aws_s3_bucket.images.bucket
      UPLOAD_PREFIX          = "uploads/"
      DEFAULT_MIN_CONFIDENCE = tostring(var.default_min_confidence)

      # Quota
      QUOTA_TABLE = aws_dynamodb_table.quota.name
      QUOTA_LIMIT = tostring(var.daily_quota_limit)
      
    }
  }

  tracing_config { mode = "Active" }
  depends_on = [aws_cloudwatch_log_group.lambda_logs]
}

########################################
# API Gateway HTTP API (CORS via Lambda responses)
########################################
resource "aws_apigatewayv2_api" "http_api" {
  name          = "${var.project_name}-api-${local.suffix_hex}"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda_proxy" {
  api_id                 = aws_apigatewayv2_api.http_api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.fn.invoke_arn
  payload_format_version = "2.0"
}

# Public routes
resource "aws_apigatewayv2_route" "health_get" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "analyze_post" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "POST /analyze"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

# Admin route (bypasses quota if caller is same AWS account) — requires SigV4 (AWS_IAM)
resource "aws_apigatewayv2_route" "analyze_post_admin" {
  api_id             = aws_apigatewayv2_api.http_api.id
  route_key          = "POST /admin/analyze"
  target             = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
  authorization_type = "AWS_IAM"
}

# OPTIONS (CORS handled by Lambda headers)
resource "aws_apigatewayv2_route" "health_options" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "OPTIONS /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "analyze_options" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "OPTIONS /analyze"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_route" "analyze_admin_options" {
  api_id    = aws_apigatewayv2_api.http_api.id
  route_key = "OPTIONS /admin/analyze"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_proxy.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http_api.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowAPIGatewayInvoke-${local.suffix_hex}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http_api.execution_arn}/*/*"
}

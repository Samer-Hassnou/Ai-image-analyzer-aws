# outputs.tf

output "s3_bucket_name" {
  description = "Private S3 bucket used for uploads"
  value       = aws_s3_bucket.images.bucket
}

output "api_base_url" {
  description = "Base URL for HTTP API"
  value       = aws_apigatewayv2_stage.default.invoke_url
}

 output "healthcheck_url" {
  description = "GET this URL to test API ↔ Lambda"
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/health"
}

output "analyze_url" {
  description = "POST JSON/Base64 here to analyze & store image"
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/analyze"
}

output "admin_analyze_url" {
  description = "POST here with SigV4 (AWS_IAM). Bypasses daily quota when caller is same AWS account."
  value       = "${trimsuffix(aws_apigatewayv2_stage.default.invoke_url, "/")}/admin/analyze"
}

output "quota_table_name" {
  description = "DynamoDB table that tracks per-user daily quota"
  value       = aws_dynamodb_table.quota.name
}

provider "aws" {
  region = "ap-northeast-2"
}

resource "aws_s3_bucket" "compliance_bucket" {
  bucket = "ks-compliance-bucket-01"
}

resource "aws_s3_bucket_public_access_block" "compliance_bucket_pab" {
  bucket = aws_s3_bucket.compliance_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "compliance_bucket_versioning" {
  bucket = aws_s3_bucket.compliance_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}
#버전 관리

#trivy:ignore:AWS-0089
#trivy:ignore:AWS-0132
resource "aws_s3_bucket" "log_bucket" {
  bucket = "ks-compliance-log-bucket-01"
}
#로그 버킷 & trivy 무시 처리

resource "aws_s3_bucket_logging" "compliance_bucket_logging" {
  bucket        = aws_s3_bucket.compliance_bucket.id
  target_bucket = aws_s3_bucket.log_bucket.id
  target_prefix = "logs/"
}
#로깅 설정

resource "aws_kms_key" "s3_key" {
  description             = "S3 compliance bucket encryption key"
  deletion_window_in_days = 10
  enable_key_rotation = true #1년마다 자동 교체
}
#key 삭제 대기 시간

resource "aws_s3_bucket_server_side_encryption_configuration" "compliance_bucket_sse" {
  bucket = aws_s3_bucket.compliance_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.s3_key.arn
      sse_algorithm     = "aws:kms"
    }
  }
}
#KMS KEY

resource "aws_s3_bucket_versioning" "log_bucket_versioning" {
  bucket = aws_s3_bucket.log_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}
#로그 버킷 버저닝

resource "aws_s3_bucket_public_access_block" "log_bucket_pab" {
  bucket = aws_s3_bucket.log_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
#로그 버킷 퍼블릭 엑세스 차단
# variables.tf
# EKS의 변수 정의

variable "cluster_name" {
  description = "클러스터 이름"
  type        = string
  default     = "s3-monitor-eks"
}

variable "cluster_version" {
  description = "클러스터 버전"
  type        = string
  default     = "1.35"
}

variable "aws_region" {
  description = "리소스를 배포할 AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "vpc_cidr" {
  description = "VPC의 CIDR 블록"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Public Subnet의 CIDR 블록"
  type        = list(string)
  default     = ["10.0.0.0/20", "10.0.16.0/20"]
}

variable "private_subnet_cidrs" {
  description = "Private Subnet의 CIDR 블록"
  type        = list(string)
  default     = ["10.0.32.0/20", "10.0.48.0/20"]
}

variable "availability_zones" {
  description = "AZ 리스트"
  type        = list(string)
  default     = ["ap-northeast-2a", "ap-northeast-2c"]
}


variable "node_instance_type" {
  description = "노드 타입"
  type        = string
  default     = "t3.medium"
}

variable "node_desired_size" {
  description = "원하는 노드 사이즈"
  type        = number
  default     = 2
}
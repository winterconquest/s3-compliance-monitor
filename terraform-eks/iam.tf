resource "aws_iam_role" "cluster_role" {
  name = "${var.cluster_name}-iam-role-cluster"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "eks.amazonaws.com" }
      }
    ]
  })
}

resource "aws_iam_role" "node_role" {
  name = "${var.cluster_name}-iam-role-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "ec2.amazonaws.com" }
      }
    ]
  })
}

#trust policy
data "aws_iam_policy_document" "s3_monitor_irsa_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.eks.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:sub"
      values   = ["system:serviceaccount:default:s3-monitor-sa"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(aws_iam_openid_connect_provider.eks.url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

#permission policy
data "aws_iam_policy_document" "s3_monitor_permissions" {
  statement {
    sid    = "S3ReadForCompliance"
    effect = "Allow"
    actions = [
      "s3:ListAllMyBuckets",
      "s3:GetBucketTagging",
      "s3:GetBucketPublicAccessBlock",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "S3RemediateWrite"
    effect = "Allow"
    actions = [
      "s3:PutBucketPublicAccessBlock",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "IAMReadForCompliance"
    effect = "Allow"
    actions = [
      "iam:ListUsers",
      "iam:ListGroupsForUser",
      "iam:ListAttachedGroupPolicies",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "CloudTrailReadForCompliance"
    effect = "Allow"
    actions = [
      "cloudtrail:LookupEvents",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "workernode_policy" {
  role       = aws_iam_role.node_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "cni_policy" {
  role       = aws_iam_role.node_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "container_readonly" {
  role       = aws_iam_role.node_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_role" "s3_monitor_irsa" {
  name               = "s3-monitor-irsa-role"
  assume_role_policy = data.aws_iam_policy_document.s3_monitor_irsa_trust.json
}

resource "aws_iam_policy" "s3_monitor_permissions" {
  name   = "s3-monitor-irsa-permissions"
  policy = data.aws_iam_policy_document.s3_monitor_permissions.json
}

resource "aws_iam_role_policy_attachment" "s3_monitor_irsa_attach" {
  role       = aws_iam_role.s3_monitor_irsa.name
  policy_arn = aws_iam_policy.s3_monitor_permissions.arn
}

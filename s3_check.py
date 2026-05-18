import boto3
from botocore.exceptions import ClientError

s3 = boto3.client('s3')
response = s3.list_buckets()

def check_buckets(response):
    results=[]
    for bucket in response["Buckets"]:
        bucket_name = bucket.get("Name")
        try:
            result = s3.get_public_access_block(Bucket=bucket_name)
            config = result["PublicAccessBlockConfiguration"]
            if all(config.values()):
                results.append({"bucket": bucket_name, "status": "퍼블릭 엑세스 차단 상태"})
            else:
                results.append({"bucket": bucket_name, "status": "위험 - 퍼블릭 액세스 허용됨"})
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "NoSuchPublicAccessBlockConfiguration":
                results.append({"bucket": bucket_name, "status": "위험 - 퍼블릭 액세스 블록 설정 없음"})
            elif error_code == "NoSuchBucket":
                results.append({"bucket": bucket_name, "status": "에러 - 버킷 없음"})
    return results

check_buckets(response)
print(check_buckets(response))
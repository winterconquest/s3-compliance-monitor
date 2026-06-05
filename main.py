from fastapi import FastAPI
import boto3
import json
from botocore.exceptions import ClientError

app = FastAPI()
s3 = boto3.client('s3')
cloudtrail = boto3.client('cloudtrail')
iam = boto3.client('iam')

def is_exempted(bucket_name):
    try:
        response = s3.get_bucket_tagging(Bucket=bucket_name)
        tag_set = response["TagSet"]
        
        is_exempt = any(
            tag["Key"] == "AllowPublic" and tag["Value"] == "true"
            for tag in tag_set
        )

        return is_exempt

    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchTagSet":
            return False
        raise

@app.get("/")
def root():
    return {"message": "S3 컴플라이언스 대시보드"}

@app.get("/s3-status")
def s3_status():
    s3_response = s3.list_buckets()
    results=[]
    for bucket in s3_response["Buckets"]:
        bucket_name = bucket.get("Name")
        try:
            result = s3.get_public_access_block(Bucket=bucket_name)
            config = result["PublicAccessBlockConfiguration"]
            if all(config.values()):
                results.append({"bucket": bucket_name, "status": "<퍼블릭 액세스 차단 상태>"})
            else:
                results.append({"bucket": bucket_name, "status": "경고!! - <퍼블릭 액세스 허용됨>"})
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "NoSuchPublicAccessBlockConfiguration":
                results.append({"bucket": bucket_name, "status": "경고!! - <퍼블릭 액세스 블록 설정 없음>"})
            elif error_code == "NoSuchBucket":
                results.append({"bucket": bucket_name, "status": "에러 - <버킷 없음>"})
    return results
    

@app.get("/trail-history")
def trail_history(limit: int = 5): #기본값 5
    trail_response = cloudtrail.lookup_events(
    LookupAttributes=[ #특정 이벤트만 골라서 가져옴
        {
            "AttributeKey": "EventName",
            "AttributeValue": "PutBucketPublicAccessBlock"
        }
    ],
    MaxResults=limit # /trail-history?limit=5 
    )
    results=[]
    for event in trail_response.get('Events',[]):
        user = event.get('Username')
        eventtime = event.get('EventTime')
        resources = event.get('Resources', [])
        bucket_name = resources[0].get('ResourceName') if resources else "N/A"
        
        detail = json.loads(event["CloudTrailEvent"])
        config = detail["requestParameters"]["PublicAccessBlockConfiguration"]

        event_dic = {
            "time": eventtime,
            "user": user,
            "bucket": bucket_name,
            "status": "<차단 되어 있음>" if all(config.values()) else ("[!!!퍼블릭 액세스 허용된 상태!!!]"),
        }
        results.append(event_dic)
    return results

@app.get("/iam-status")
def check_iam_users():
    user_list = iam.list_users()
    results=[]
    for user in user_list.get('Users',[]): #key가 Users
        user_name = user.get('UserName')
        response = iam.list_groups_for_user(UserName=user_name)

        for group in response.get('Groups',[]):
            policies = iam.list_attached_group_policies(GroupName=group['GroupName'])

            for policy in policies.get('AttachedPolicies',[]):
                policy_arn = policy.get('PolicyArn')  # 여기서 ARN을 동적으로 받음
                # 정책 상세 내용 조회
                version = iam.get_policy(PolicyArn=policy_arn)["Policy"]["DefaultVersionId"]
                document = iam.get_policy_version(PolicyArn=policy_arn, VersionId=version)
                statements = document["PolicyVersion"]["Document"]["Statement"]


                for stmt in statements:
                    actions = stmt.get('Action')
                    resources = stmt.get('Resource')

                    if (actions == "*" or actions == ["*"]) and (resources == "*" or resources == ["*"]):
                        status = "!!!과도한 권한 부여됨!!!"
                    else:
                        status = "적정 권한 부여됨"

                    iam_dic = {
                        "user": user_name,
                        "group": group['GroupName'],
                        "policy": policy['PolicyName'],
                        "status": status,
                    }
                    results.append(iam_dic)

    return results

@app.get("/remediate")
def remediate(bucket_name: str, dry_run: bool = True):
    if dry_run:
        return {"bucket": bucket_name, "status": f"dry-run 여부 - {dry_run}"}
    
    if is_exempted(bucket_name):
        return {"bucket": bucket_name, "status": "AllowPublic=true로 인해 제외됨"}
    
    try: 
        s3.put_public_access_block( #HTTP 상태 코드 등이 담긴 메타데이터만 반환
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True
            }
        )
        return {"bucket": bucket_name, "status": "<퍼블릭 액세스 차단 적용된 상태>"}

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "AccessDenied":
            return {"bucket": bucket_name, "status": f"접근 실패 - {error_code}"}
        elif error_code == "NoSuchBucket":
            return {"bucket": bucket_name, "status": "에러 - <버킷 없음>"}
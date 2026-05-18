from fastapi import FastAPI
import boto3
import json
from botocore.exceptions import ClientError

app = FastAPI()
s3 = boto3.client('s3')
cloudtrail = boto3.client('cloudtrail')



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
                results.append({"bucket": bucket_name, "status": "<퍼블릭 엑세스 차단 상태>"})
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
    
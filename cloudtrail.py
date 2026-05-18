
import boto3
import json

cloudtrail = boto3.client('cloudtrail')


response = cloudtrail.lookup_events(
    LookupAttributes=[
        {
            "AttributeKey": "EventName",
            "AttributeValue": "PutBucketPublicAccessBlock"
        }
    ],
    MaxResults=5
)

def cldtrl_bucket(response):
    results=[]
    for event in response.get('Events',[]):
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
            "status": "[차단 되어 있음]" if all(config.values()) else ("[!!!퍼블릭 액세스 허용된 상태!!!]"),
        }
        results.append(event_dic)
    print("-"*10)
    return results

trail_history = cldtrl_bucket(response)

def cloudtrial_logs(trail_history):
    return "\n----------\n".join([
        f"시간: {item['time']}\n이름: {item['user']}\n버킷: {item['bucket']}\n{item['status']}" 
        for item in trail_history
    ]) + "\n----------"

print(cloudtrial_logs(trail_history))
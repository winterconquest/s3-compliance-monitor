import json
import os
import urllib.request

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]


def lambda_handler(event, context):
    # 1. 이벤트에서 필요한 정보 추출
    detail = event.get("detail", {})
    user_identity = detail.get("userIdentity", {})
    request_parameters = detail.get("requestParameters", {})
    
    user = user_identity.get("userName") or user_identity.get("arn", "Unknown")
    event_time = detail.get("eventTime", "Unknown")
    event_name = detail.get("eventName", "Unknown")
    bucket_name = request_parameters.get("bucketName", "Unknown")
    
    # 2. 차단 설정값 확인
    config = request_parameters.get("PublicAccessBlockConfiguration", {})
    is_safe = all(config.values()) if config else False
    status = "안전" if is_safe else "위험 — 일부 차단 해제됨"
    
    # 3. Slack 메시지 포맷팅
    message = {
        "text": f"*S3 퍼블릭 액세스 설정 변경 감지*\n"
                f"• 버킷: `{bucket_name}`\n"
                f"• 변경자: `{user}`\n"
                f"• 시간: `{event_time}`\n"
                f"• 이벤트: `{event_name}`\n"
                f"• 상태: *{status}*"
    }
    
    # 4. Slack Webhook 호출
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=json.dumps(message).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    with urllib.request.urlopen(req) as response:
        response_body = response.read().decode("utf-8")
    
    return {
        "statusCode": 200,
        "body": json.dumps({"slack_response": response_body})
    }
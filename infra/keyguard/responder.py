"""KeyGuard responder (blueprint 12.5 detective control), deployed as an AWS Lambda behind an EventBridge rule on
CloudTrail KMS events. It pages security for every watched event and, when the event has no approved KeyGuard
record, cancels the deletion and re-enables the key. Its role may only CancelKeyDeletion, EnableKey and DescribeKey.

Approved records are read from the KeyGuard table in DynamoDB (`KEYGUARD_APPROVALS_TABLE`), written by the KeyGuard
workflow when a destruction plan is authorized: {request_id: [key ARNs]}.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import boto3

from lmqa_keys.keyguard import KeyEvent, respond
from lmqa_keys.providers import AwsKmsProvider


def _approved() -> dict[str, set[str]]:
    table = boto3.resource("dynamodb").Table(os.environ["KEYGUARD_APPROVALS_TABLE"])
    items = table.scan(ProjectionExpression="request_id, key_arns").get("Items", [])
    return {str(i["request_id"]): set(i.get("key_arns", [])) for i in items}


def _page(summary: dict[str, Any]) -> None:
    url = os.environ.get("ONCALL_WEBHOOK_URL")
    if not url:
        return
    body = json.dumps({"severity": "critical", "source": "keyguard", **summary}).encode()
    req = urllib.request.Request(  # noqa: S310 - webhook URL comes from operator config
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 - webhook URL comes from operator config


def handler(event: dict[str, Any], _context: Any) -> dict[str, str]:
    key_event = KeyEvent.from_cloudtrail(event.get("detail", {}))
    provider = AwsKmsProvider(region=os.environ.get("AWS_REGION", "us-east-1"))
    action = respond(provider, key_event, _approved())
    summary = {
        "event": key_event.event_name,
        "key": key_event.key_ref,
        "principal": key_event.principal_arn,
        "action": action,
    }
    _page(summary)
    return summary

# KeyGuard, detective layer (doc 12.5): any schedule-deletion, disable, key-policy or cancel event pages
# security on-call within 60 seconds. The automated RESPONDER that cancels an unapproved deletion and
# re-enables the key is a small Lambda that is NOT written yet (open item, gate G1.12 and G9.12).

resource "aws_sns_topic" "keyguard" {
  name              = "${local.prefix}-keyguard-alerts"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "oncall" {
  topic_arn = aws_sns_topic.keyguard.arn
  protocol  = "email"
  endpoint  = var.security_oncall_email
}

resource "aws_cloudwatch_event_rule" "key_events" {
  name        = "${local.prefix}-kms-destructive-events"
  description = "Key deletion, disable, policy and cancel events"
  event_pattern = jsonencode({
    source      = ["aws.kms"]
    detail-type = ["AWS API Call via CloudTrail"]
    detail = {
      eventSource = ["kms.amazonaws.com"]
      eventName   = ["ScheduleKeyDeletion", "DisableKey", "CancelKeyDeletion", "PutKeyPolicy", "DeleteImportedKeyMaterial", "EnableKey"]
    }
  })
}

resource "aws_cloudwatch_event_target" "page" {
  rule = aws_cloudwatch_event_rule.key_events.name
  arn  = aws_sns_topic.keyguard.arn
}

data "aws_iam_policy_document" "sns_from_events" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.keyguard.arn]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_sns_topic_policy" "keyguard" {
  arn    = aws_sns_topic.keyguard.arn
  policy = data.aws_iam_policy_document.sns_from_events.json
}

"""
Lambda handler for Amazon Connect scheduling notification events.

Triggered by EventBridge when a Connect "Scheduling Rules Matched" event fires.
Calls the Connect CreateNotification API to notify the affected agent(s).
"""

import json
import os
import logging
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

connect_client = boto3.client("connect")

INSTANCE_ID = os.environ["CONNECT_INSTANCE_ID"]
FALLBACK_RECIPIENT_ARNS = [
    arn.strip()
    for arn in os.environ.get("NOTIFICATION_RECIPIENT_ARNS", "").split(",")
    if arn.strip()
]


def get_affected_recipients(event: dict) -> list[str]:
    """
    Extract the affected agent ARN(s) from the event.

    The agent ARN lives in the top-level 'resources' array.
    Agent ARNs contain '/agent/' in the path, while instance ARNs do not.
    """
    resources = event.get("resources", [])

    # Filter to only agent ARNs (skip the instance ARN)
    agent_arns = [r for r in resources if "/agent/" in r]

    if agent_arns:
        return agent_arns

    # Fallback to configured defaults
    logger.warning(
        "No agent-specific recipients found in event resources, using fallback recipients"
    )
    return FALLBACK_RECIPIENT_ARNS


def build_notification_message(detail: dict) -> str:
    """Build a human-readable notification message from the event detail."""
    rule_name = detail.get("ruleName", "")
    action_name = detail.get("actionName", "")

    # Use the rule/action name to provide context if available
    if rule_name:
        return f"Your schedule has been updated (rule: {rule_name}). Please check your schedule in Amazon Connect."

    return "A schedule change has occurred. Please check your schedule in Amazon Connect."


def lambda_handler(event: dict, context) -> dict:
    """
    Handle EventBridge 'Scheduling Rules Matched' events and create
    Connect notifications for the affected agent(s).

    Event structure:
    {
        "version": "0",
        "id": "...",
        "detail-type": "Scheduling Rules Matched",
        "source": "aws.connect",
        "account": "<ACCOUNT_ID>",
        "time": "...",
        "region": "<REGION>",
        "resources": [
            "arn:aws:connect:<REGION>:<ACCOUNT_ID>:instance/...",
            "arn:aws:connect:<REGION>:<ACCOUNT_ID>:instance/.../agent/..."
        ],
        "detail": {
            "ruleName": "Schedule-Update-Notification",
            "actionName": "Schedule-Update-Notification",
            "instanceArn": "arn:aws:connect:...",
            "version": "1.0"
        }
    }
    """
    # Print the raw event for debugging in CloudWatch Logs
    print("=== RAW EVENTBRIDGE EVENT ===")
    print(json.dumps(event, indent=2))
    print("=== END RAW EVENT ===")

    logger.info("Received event: %s", json.dumps(event))

    detail = event.get("detail", {})
    message = build_notification_message(detail)
    recipients = get_affected_recipients(event)

    if not recipients:
        logger.error("No recipients found — cannot send notification")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "No recipients available"}),
        }

    logger.info(
        "Sending notification: recipients=%s, message=%s",
        recipients,
        message,
    )

    try:
        response = connect_client.create_notification(
            InstanceId=INSTANCE_ID,
            Recipients=recipients,
            Priority="HIGH",
            Content={
                "en_US": message,
            },
            ClientToken=str(uuid.uuid4()),
        )

        notification_id = response.get("NotificationId")
        logger.info("Notification created successfully: %s", notification_id)

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": "Notification sent successfully",
                    "notificationId": notification_id,
                    "recipients": recipients,
                }
            ),
        }

    except connect_client.exceptions.ResourceNotFoundException as e:
        logger.error("Connect instance or resource not found: %s", str(e))
        raise
    except connect_client.exceptions.InvalidParameterException as e:
        logger.error("Invalid parameter in CreateNotification call: %s", str(e))
        raise
    except Exception as e:
        logger.error("Unexpected error creating notification: %s", str(e))
        raise

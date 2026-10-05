# Amazon Connect Schedule Notification Handler

This project deploys an EventBridge rule and Lambda function that automatically sends
notifications to agents/supervisors when Amazon Connect scheduling events occur.

`template.yaml` is a **self-contained CloudFormation template** — the Lambda code is
inlined, so there is no build step, no S3 bucket, and no SAM CLI required. You deploy it
directly from the AWS console or with a single CLI command, supplying your own Amazon
Connect instance ID and recipient ARNs as parameters.

## Architecture

```
Amazon Connect Scheduling
        │
        ▼
  EventBridge Rule  ──────►  Lambda Function  ──────►  Connect CreateNotification API
  (filters schedule                                     (sends notification to recipients)
   events)
```

## Parameters (you provide these)

| Parameter | Required | Description |
|---|---|---|
| `ConnectInstanceId` | Yes | Your Amazon Connect instance ID — the GUID only, **not** the full ARN. Found in the Connect console or after `instance/` in the instance ARN. |
| `NotificationRecipientArns` | Yes | Comma-separated recipient ARNs (Connect user ARNs or the instance ARN) used as a fallback when a triggering event has no agent-specific recipient. |

### Finding your values

- **Instance ID** — in the Amazon Connect console, open your instance; the ID is the GUID
  in the instance ARN: `arn:aws:connect:<region>:<account-id>:instance/<INSTANCE_ID>`.
- **Recipient ARNs** — a user ARN looks like
  `arn:aws:connect:<region>:<account-id>:instance/<INSTANCE_ID>/agent/<AGENT_ID>`.

## Deploy — AWS Console (easiest)

1. Open the **CloudFormation** console → **Create stack** → **With new resources**.
2. Choose **Upload a template file**, select `template.yaml`, and click **Next**.
3. Enter a **Stack name** (e.g. `connect-schedule-notifications`) and fill in
   `ConnectInstanceId` and `NotificationRecipientArns`.
4. On the review step, check **"I acknowledge that AWS CloudFormation might create IAM
   resources"**, then **Submit**.

That's it — no packaging, no build.

## Deploy — AWS CLI

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name connect-schedule-notifications \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      ConnectInstanceId=<YOUR_CONNECT_INSTANCE_ID> \
      NotificationRecipientArns=<ARN1>,<ARN2>
```

`CAPABILITY_IAM` is required because the stack creates an execution role for the Lambda.

## Prerequisites

- An AWS account with permission to create Lambda, IAM, EventBridge, and CloudWatch Logs
  resources.
- An Amazon Connect instance with scheduling enabled.

## How it works

The EventBridge rule matches Amazon Connect scheduling events (`source: aws.connect`,
detail type `Scheduling Rules Matched`) and invokes the Lambda. The function extracts the
affected agent ARN(s) from the event's `resources` array and falls back to
`NotificationRecipientArns` when none are present, then calls the Connect
`CreateNotification` API with `HIGH` priority.

## Editing the Lambda code

The authoritative source lives at `src/handler.py`. The template embeds a copy inline
under `Resources.ScheduleNotificationFunction.Properties.Code.ZipFile`. If you change the
handler logic, update both so they stay in sync. (Inline code must stay under the 4096
character CloudFormation limit; if it grows beyond that, switch to a packaged deployment.)

## Cleanup

```bash
aws cloudformation delete-stack --stack-name connect-schedule-notifications
```

Or delete the stack from the CloudFormation console.

# Amazon Connect Schedule Notification Handler

This project deploys the end-to-end automation that notifies agents when a **published
schedule is updated** in Amazon Connect — including the Amazon Connect Rules-engine rule
itself.

`template.yaml` is a **self-contained CloudFormation template**. All Lambda code is
inlined, so there is no build step, no S3 bucket, and no SAM CLI required. You deploy it
directly from the AWS console or with a single CLI command, supplying your own instance
ID and the agents to notify.

## What the stack creates

| Resource | Purpose |
|---|---|
| **Amazon Connect rule** (`OnScheduleUpdate`) | Fires when a published schedule is updated for the targeted agents and generates an EventBridge event. Created via a CloudFormation custom resource (Lambda-backed, calls `connect:CreateRule`). |
| **EventBridge rule** | Captures the Connect event and invokes the notification Lambda. |
| **Notification Lambda** | Calls the Connect `CreateNotification` API to notify the affected agent(s). |
| **IAM roles, log groups, Lambda permission** | Supporting resources. |

## How it works

```
Published schedule updated
        │
        ▼
  Amazon Connect rule  ──────►  EventBridge event  ──────►  EventBridge rule
  (created by this stack)        (detail.actionName)         (created by this stack)
                                                                   │
                                                                   ▼
                                                           Notification Lambda
                                                                   │
                                                                   ▼
                                                     Connect CreateNotification API
```

CloudFormation builds the EventBridge rule before the Connect rule (via `DependsOn`), so
the Connect rule only starts emitting events once the downstream plumbing exists.

## Parameters (you provide these)

| Parameter | Required | Default | Description |
|---|---|---|---|
| `ConnectInstanceId` | Yes | — | Your Amazon Connect instance ID — the GUID only, **not** the full ARN. |
| `TargetAgentIds` | Yes | — | At least one agent to target in the Connect rule. Each entry may be an agent user ID (GUID) **or** a full agent ARN; the agent ID is extracted automatically. Amazon Connect requires a scheduling rule to specify at least one schedule resource condition, so this cannot be empty. |
| `NotificationRecipientArns` | Yes | — | Comma-separated fallback recipient ARNs used by the Lambda when a triggering event has no agent-specific recipient. |
| `ConnectRuleName` | No | `Schedule-Update-Notification` | Name of the created Connect rule (chars `0-9 a-z A-Z . _ -`). |
| `EventBridgeActionName` | No | `Schedule-Update-Notification` | Arbitrary label Connect stamps into the event as `detail.actionName`. |

### Finding your values

- **Instance ID** — in the Amazon Connect console, open your instance; the ID is the GUID
  in the instance ARN: `arn:aws:connect:<region>:<account-id>:instance/<INSTANCE_ID>`.
- **Agent IDs / ARNs** — an agent ARN looks like
  `arn:aws:connect:<region>:<account-id>:instance/<INSTANCE_ID>/agent/<AGENT_ID>`. You can
  pass either the full ARN or just `<AGENT_ID>`.

## Prerequisites

- An AWS account with permission to create Lambda, IAM, EventBridge, CloudWatch Logs, and
  Amazon Connect **rule** resources.
- An Amazon Connect instance with **scheduling enabled** (Agent scheduling must be set up,
  with schedules being published).
- The deploying principal's credentials must be allowed to call
  `connect:CreateRule` / `connect:UpdateRule` / `connect:DeleteRule` on the instance (the
  custom-resource Lambda's own role already grants these; this note is about any SCP/
  permission boundary on your account).

> This stack does **not** enable Amazon Connect scheduling itself — it only creates the
> rule that reacts to schedule updates. Scheduling must already be configured in your
> instance.

## Deploy — AWS Console (easiest)

1. Open the **CloudFormation** console → **Create stack** → **With new resources**.
2. Choose **Upload a template file**, select `template.yaml`, click **Next**.
3. Enter a **Stack name** and fill in `ConnectInstanceId`, `TargetAgentIds` (at least one
   agent), and `NotificationRecipientArns` (leave the optional parameters at their defaults
   unless you need to change them).
4. On the review step, check **"I acknowledge that AWS CloudFormation might create IAM
   resources"**, then **Submit**.

## Deploy — AWS CLI

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name connect-schedule-notifications \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
      ConnectInstanceId=<YOUR_CONNECT_INSTANCE_ID> \
      TargetAgentIds=<AGENT_ID_OR_ARN_1>,<AGENT_ID_OR_ARN_2> \
      NotificationRecipientArns=<ARN1>,<ARN2>
```

`CAPABILITY_IAM` is required because the stack creates execution roles for the Lambdas.
`TargetAgentIds` must contain at least one agent — Amazon Connect requires a scheduling
rule to specify at least one schedule resource condition.

## EventBridge event pattern

The EventBridge rule matches the Connect scheduling event:

```json
{
  "source": ["aws.connect"],
  "detail-type": ["Scheduling Rules Matched"]
}
```

## Editing the Lambda code

The authoritative sources live in `src/`:

- `src/handler.py` — the notification Lambda.
- `src/connect_rule_resource.py` — the custom-resource Lambda that manages the Connect rule.

The template embeds a copy of each inline under the respective
`Resources.<Function>.Properties.Code.ZipFile`. If you change handler logic, update both
the `src/` file and the inline copy so they stay in sync. Inline code must stay under the
4096-character CloudFormation limit; if it grows beyond that, switch to a packaged
deployment.

## Troubleshooting a failed deploy

If a deploy fails and the stack ends up in `ROLLBACK_COMPLETE`, you must delete it before
redeploying — CloudFormation cannot update a rolled-back stack:

```bash
aws cloudformation delete-stack --stack-name connect-schedule-notifications
```

A failed first deploy can also leave an orphaned Lambda log group (Lambda auto-creates it
on first run). If a retry fails with `Resource ... already exists` for
`/aws/lambda/connect-schedule-rule-manager` or `/aws/lambda/connect-schedule-notification-handler`,
delete the orphaned group and redeploy:

```bash
aws logs delete-log-group --log-group-name /aws/lambda/connect-schedule-rule-manager
```

To see why the Connect rule failed to create, read the custom-resource Lambda's logs:

```bash
aws logs tail /aws/lambda/connect-schedule-rule-manager --since 15m
```

## Cleanup

```bash
aws cloudformation delete-stack --stack-name connect-schedule-notifications
```

Deleting the stack also deletes the Amazon Connect rule it created (the custom resource
calls `connect:DeleteRule` on stack delete).

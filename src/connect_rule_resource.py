"""CFN custom resource: manage the Connect OnScheduleUpdate rule (create/update/delete)."""
import json
import logging

import boto3
import cfnresponse

log = logging.getLogger()
log.setLevel(logging.INFO)
connect = boto3.client("connect")

EVENT_SOURCE = "OnScheduleUpdate"


def agent_ids(props):
    raw = props.get("TargetAgentIds", [])
    if isinstance(raw, str):
        raw = raw.split(",")
    out = []
    for e in raw:
        e = (e or "").strip()
        if not e:
            continue
        if "/agent/" in e:
            out.append(e.split("/agent/", 1)[1])
        elif ":" not in e and "/" not in e:
            out.append(e)
        else:
            log.warning("Ignoring non-agent target: %s", e)
    seen = set()
    return [a for a in out if not (a in seen or seen.add(a))]


def build_function(ids):
    return json.dumps({
        "Version": "2022-11-25",
        "RuleFunction": {
            "Operator": "AND",
            "Operands": [{
                "Operator": "CONTAINS_ANY",
                "ComparisonValue": "$.Scheduling.ImpactedAgents[*].Id",
                "Operands": ids,
                "Negate": False,
            }],
        },
    })


def find_rule_id(instance_id, name):
    paginator = connect.get_paginator("list_rules")
    for page in paginator.paginate(InstanceId=instance_id, EventSourceName=EVENT_SOURCE):
        for s in page.get("RuleSummaryList", []):
            if s.get("Name") == name:
                return s.get("RuleId")
    return None


def create_or_update(props):
    instance_id = props["ConnectInstanceId"]
    name = props["RuleName"]
    ids = agent_ids(props)
    if not ids:
        raise ValueError(
            "TargetAgentIds is empty. A Connect scheduling rule requires at least one "
            "agent to target; provide one or more agent IDs/ARNs in TargetAgentIds."
        )
    log.info("Rule %s targeting %d agent(s)", name, len(ids))
    function = build_function(ids)
    actions = [{
        "ActionType": "GENERATE_EVENTBRIDGE_EVENT",
        "EventBridgeAction": {"Name": props["EventBridgeActionName"]},
    }]
    existing = find_rule_id(instance_id, name)
    if existing:
        log.info("Updating rule %s (%s)", name, existing)
        connect.update_rule(RuleId=existing, InstanceId=instance_id, Name=name,
                            Function=function, Actions=actions, PublishStatus="PUBLISHED")
        return existing
    log.info("Creating rule %s", name)
    resp = connect.create_rule(InstanceId=instance_id, Name=name,
                               TriggerEventSource={"EventSourceName": EVENT_SOURCE},
                               Function=function, Actions=actions, PublishStatus="PUBLISHED")
    return resp["RuleId"]


def delete(props, physical_id):
    instance_id = props["ConnectInstanceId"]
    rid = physical_id if (physical_id and len(physical_id) == 36) else find_rule_id(
        instance_id, props["RuleName"])
    if not rid:
        log.info("No rule to delete; skipping")
        return
    log.info("Deleting rule %s", rid)
    connect.delete_rule(InstanceId=instance_id, RuleId=rid)


def lambda_handler(event, context):
    log.info("Event: %s", json.dumps(event))
    rt = event["RequestType"]
    props = event.get("ResourceProperties", {})
    pid = event.get("PhysicalResourceId")
    try:
        if rt in ("Create", "Update"):
            rid = create_or_update(props)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {"RuleId": rid}, rid)
        elif rt == "Delete":
            delete(props, pid)
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, pid)
        else:
            raise ValueError("Unknown request type: " + rt)
    except Exception as e:
        log.exception("Custom resource failed")
        cfnresponse.send(event, context, cfnresponse.FAILED,
                         {"Error": "%s: %s" % (type(e).__name__, e)}, pid)

"""Monthly AWS cost notifications and automatic Rasterizer service recovery."""

import json
import math
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

import boto3
from botocore.exceptions import ClientError


REGION = os.environ.get("AWS_REGION", "us-east-2")
ACCOUNT_ID = os.environ["ACCOUNT_ID"]
BUDGET_NAME = os.environ["BUDGET_NAME"]
MONTHLY_LIMIT = Decimal(os.environ.get("MONTHLY_LIMIT_USD", "100"))
WARNING_PERCENT = Decimal(os.environ.get("WARNING_PERCENT", "75"))
OPERATOR_TOPIC_ARN = os.environ["OPERATOR_TOPIC_ARN"]
ENVIRONMENTS = {
    "production": {
        "label": "Production",
        "table_name": os.environ["PRODUCTION_RUNTIME_TABLE_NAME"],
        "pipe_name": os.environ["PRODUCTION_PIPE_NAME"],
        "public_url": os.environ["PRODUCTION_PUBLIC_URL"].rstrip("/"),
    },
    "staging": {
        "label": "Serverless staging",
        "table_name": os.environ["STAGING_RUNTIME_TABLE_NAME"],
        "pipe_name": os.environ["STAGING_PIPE_NAME"],
        "public_url": os.environ["STAGING_PUBLIC_URL"].rstrip("/"),
    },
}

budgets = boto3.client("budgets", region_name="us-east-1")
pipes = boto3.client("pipes", region_name=REGION)
sns = boto3.client("sns", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
tables = {name: dynamodb.Table(config["table_name"]) for name, config in ENVIRONMENTS.items()}
notification_table = tables["production"]

CONTROL_KEY = {"pk": "SYSTEM#SERVICE", "sk": "CONTROL"}


def next_month_start(now=None):
    current = datetime.fromtimestamp(now or time.time(), tz=timezone.utc)
    year, month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    return datetime(year, month, 1, tzinfo=timezone.utc)


def current_period(now=None):
    return datetime.fromtimestamp(now or time.time(), tz=timezone.utc).strftime("%Y-%m")


def action_url(environment, action):
    public_url = ENVIRONMENTS[environment]["public_url"]
    return f"{public_url}/admin.html?{urlencode({'service_action': action})}"


def publish_once(marker, subject, message, period):
    marker_name = f"cost_notice_{marker}_period"
    try:
        notification_table.update_item(
            Key=CONTROL_KEY,
            UpdateExpression=f"SET {marker_name}=:period, updated_at=:now",
            ConditionExpression=f"attribute_not_exists({marker_name}) OR {marker_name} <> :period",
            ExpressionAttributeValues={":period": period, ":now": int(time.time())},
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    try:
        sns.publish(TopicArn=OPERATOR_TOPIC_ARN, Subject=subject[:100], Message=message)
    except Exception:
        notification_table.update_item(Key=CONTROL_KEY, UpdateExpression=f"REMOVE {marker_name}")
        raise
    return True


def ensure_pipe_running(environment):
    pipe_name = ENVIRONMENTS[environment]["pipe_name"]
    state = str(pipes.describe_pipe(Name=pipe_name).get("CurrentState") or "")
    if state not in {"RUNNING", "STARTING"}:
        pipes.start_pipe(Name=pipe_name)


def resume_if_due(environment, now=None):
    now = int(now or time.time())
    table = tables[environment]
    item = table.get_item(Key=CONTROL_KEY, ConsistentRead=True).get("Item") or {}
    if str(item.get("status") or "active") != "paused" or int(item.get("resumes_at") or 0) > now:
        return False
    ensure_pipe_running(environment)
    table.update_item(
        Key=CONTROL_KEY,
        UpdateExpression="SET #status=:active, updated_at=:now, updated_by=:actor REMOVE pause_reason, resumes_at",
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={":active": "active", ":now": now, ":actor": "automatic-monthly-reset"},
    )
    return True


def environment_status(environment):
    item = tables[environment].get_item(Key=CONTROL_KEY, ConsistentRead=True).get("Item") or {}
    return "PAUSED" if str(item.get("status") or "active") == "paused" else "RUNNING"


def environment_actions(environment):
    label = ENVIRONMENTS[environment]["label"]
    return (
        f"{label} - current state: {environment_status(environment)}\n"
        f"  Pause: {action_url(environment, 'pause')}\n"
        f"  Continue / leave running: {action_url(environment, 'continue')}\n"
        f"  Start / re-enable if paused: {action_url(environment, 'resume')}\n"
    )


def budget_spend():
    result = budgets.describe_budget(AccountId=ACCOUNT_ID, BudgetName=BUDGET_NAME)["Budget"]
    spend = Decimal(str((result.get("CalculatedSpend") or {}).get("ActualSpend", {}).get("Amount", "0")))
    limit = Decimal(str((result.get("BudgetLimit") or {}).get("Amount", MONTHLY_LIMIT)))
    return spend, limit


def handler(event, _context):
    now = int(time.time())
    resumed = [name for name in ENVIRONMENTS if resume_if_due(name, now)]
    spend, limit = budget_spend()
    period = current_period(now)
    percent = Decimal("0") if not limit else spend * Decimal("100") / limit
    next_cycle = next_month_start(now)
    days_left = max(0, math.ceil((next_cycle.timestamp() - now) / 86400))
    common = (
        f"AWS account spend for {period}: ${spend:.2f} of the ${limit:.2f} monthly allowance "
        f"({percent:.1f}%).\n\n"
    )
    sent = None
    if spend >= limit:
        message = common + (
            f"The monthly allowance has been exceeded. There are {days_left} day(s) left before the next "
            f"billing cycle begins on {next_cycle:%B %d, %Y} (UTC).\n\n"
            "No action will be taken automatically. Production and staging can be controlled independently; "
            "changing one does not change the other. Each link opens an authenticated administrator confirmation.\n\n"
            f"{environment_actions('production')}\n"
            f"{environment_actions('staging')}\n"
            "Ignore this email to leave both environments running.\n"
        )
        sent = "overspend" if publish_once(
            "overspend", "MOPA Rasterizer monthly AWS allowance exceeded", message, period
        ) else None
    elif percent >= WARNING_PERCENT:
        message = common + (
            f"This is the {WARNING_PERCENT:.0f}% monthly-spend warning. There are {days_left} day(s) left "
            f"before the next billing cycle begins on {next_cycle:%B %d, %Y} (UTC).\n"
        )
        sent = "warning" if publish_once(
            "warning", "MOPA Rasterizer AWS spend reached warning threshold", message, period
        ) else None
    return {"statusCode": 200, "body": json.dumps({
        "period": period, "actual_spend": str(spend), "limit": str(limit),
        "notice_sent": sent, "environments_resumed": resumed,
    })}

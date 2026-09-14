"""One-time, non-destructive backfill of the staging seven-day admin job index."""

import argparse
import time

import boto3
from boto3.dynamodb.conditions import Attr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--user-pool", required=True)
    parser.add_argument("--profile", default="mopa-admin")
    parser.add_argument("--region", default="us-east-2")
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    table = session.resource("dynamodb").Table(args.table)
    cognito = session.client("cognito-idp")
    users, pagination = {}, None
    while True:
        options = {"UserPoolId": args.user_pool, "Limit": 60}
        if pagination:
            options["PaginationToken"] = pagination
        result = cognito.list_users(**options)
        for user in result.get("Users", []):
            attributes = {item["Name"]: item["Value"] for item in user.get("Attributes", [])}
            subject = attributes.get("sub")
            if subject:
                users[subject] = attributes.get("email", "")
        pagination = result.get("PaginationToken")
        if not pagination:
            break

    cutoff = int(time.time()) - 7 * 86400
    options = {
        "FilterExpression": Attr("sk").eq("OWNER") & Attr("created_at").gte(cutoff),
        "ProjectionExpression": "pk, sk, user_id, job_type, created_at, history_sk, #status",
        "ExpressionAttributeNames": {"#status": "status"},
    }
    owners = []
    while True:
        result = table.scan(**options)
        owners.extend(result.get("Items", []))
        if not result.get("LastEvaluatedKey"):
            break
        options["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    written = 0
    with table.batch_writer() as batch:
        for owner in owners:
            task_id = str(owner.get("pk") or "").removeprefix("JOB#")
            user_id = str(owner.get("user_id") or "")
            created_at = int(owner.get("created_at") or 0)
            history_sk = str(owner.get("history_sk") or "")
            if not task_id or not user_id or not created_at or not history_sk:
                continue
            history = table.get_item(
                Key={"pk": f"USER#{user_id}", "sk": history_sk}, ConsistentRead=True,
            ).get("Item") or {}
            batch.put_item(Item={
                "pk": "ADMIN#JOBS", "sk": f"JOB#{created_at:010d}#{task_id}",
                "task_id": task_id, "created_at": created_at,
                "user_id": user_id, "user_email": users.get(user_id, ""),
                "source_name": str(history.get("source_name") or "Artwork")[:255],
                "material_name": str(history.get("material_name") or "")[:160],
                "image_preset": str(history.get("image_preset") or "")[:100],
                "abstract_filter": str(history.get("abstract_filter") or "none")[:100],
                "job_type": str(history.get("job_type") or owner.get("job_type") or "rasterizer")[:80],
                "status": str(owner.get("status") or "pending"),
                "expires_at": created_at + 7 * 86400,
            })
            written += 1
    print(f"Backfilled {written} staging admin job index record(s).")


if __name__ == "__main__":
    main()

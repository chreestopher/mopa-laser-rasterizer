#!/usr/bin/env python3
"""Backfill seven-day TTL only onto DynamoDB job/runtime records."""

import argparse
import json
import subprocess
import time


RETENTION_SECONDS = 7 * 24 * 60 * 60


def is_job_record(item):
    pk = str(item.get("pk", ""))
    sk = str(item.get("sk", ""))
    return (
        (pk.startswith("JOB#") and (sk == "RUNTIME" or sk == "OWNER" or sk.startswith("LOG#")))
        or (pk.startswith("USER#") and sk.startswith("JOB#"))
        or (pk == "ADMIN#JOBS" and sk.startswith("JOB#"))
    )


def attribute(item, name):
    value = item.get(name, {})
    if "S" in value:
        return value["S"]
    if "N" in value:
        return int(value["N"])
    return None


def aws(*arguments):
    return subprocess.run(
        ["aws", *arguments], check=True, capture_output=True, text=True,
    ).stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", required=True)
    parser.add_argument("--region", default="us-east-2")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    page = json.loads(aws(
        "dynamodb", "scan", "--region", args.region, "--table-name", args.table,
        "--projection-expression", "#pk, #sk, created_at, updated_at, expires_at",
        "--expression-attribute-names", '{"#pk":"pk","#sk":"sk"}',
        "--output", "json",
    ))
    examined = len(page.get("Items", []))
    eligible = updated = 0
    now = int(time.time())
    for raw_item in page.get("Items", []):
        item = {name: attribute(raw_item, name) for name in raw_item}
        if not is_job_record(item) or item.get("expires_at") is not None:
            continue
        eligible += 1
        base = int(item.get("created_at") or item.get("updated_at") or now)
        expiry = base + RETENTION_SECONDS
        if args.apply:
            aws(
                "dynamodb", "update-item", "--region", args.region,
                "--table-name", args.table,
                "--key", json.dumps({"pk": {"S": item["pk"]}, "sk": {"S": item["sk"]}}),
                "--update-expression", "SET expires_at=:expiry",
                "--condition-expression", "attribute_not_exists(expires_at)",
                "--expression-attribute-values", json.dumps({":expiry": {"N": str(expiry)}}),
            )
            updated += 1

    mode = "applied" if args.apply else "dry run"
    print(f"{mode}: examined {examined} item(s); {eligible} job item(s) needed TTL; updated {updated}.")


if __name__ == "__main__":
    main()

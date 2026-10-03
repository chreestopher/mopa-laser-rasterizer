#!/usr/bin/env python3
"""Remove legacy TTL attributes from signed-in Color Discovery grid records."""

import argparse
import json
import subprocess


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
        "--projection-expression", "#pk, #sk, expires_at",
        "--filter-expression",
        "begins_with(#pk,:user) AND begins_with(#sk,:grid) AND attribute_exists(expires_at)",
        "--expression-attribute-names", '{"#pk":"pk","#sk":"sk"}',
        "--expression-attribute-values",
        '{":user":{"S":"USER#"},":grid":{"S":"COLORDISCOVERY#"}}',
        "--output", "json",
    ))
    records = page.get("Items", [])
    updated = 0
    if args.apply:
        for item in records:
            aws(
                "dynamodb", "update-item", "--region", args.region,
                "--table-name", args.table,
                "--key", json.dumps({"pk": item["pk"], "sk": item["sk"]}),
                "--update-expression", "REMOVE expires_at",
            )
            updated += 1
    mode = "applied" if args.apply else "dry run"
    print(f"{mode}: found {len(records)} signed-in Color Discovery grid record(s) with legacy TTL; updated {updated}.")


if __name__ == "__main__":
    main()

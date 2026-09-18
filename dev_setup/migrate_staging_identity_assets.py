"""Copy durable staging user assets to a new Cognito subject before pool cutover.

Dry-run by default. Use with a short-lived admin SSO profile; never run against
the production table or bucket. Old records and objects are left intact.
"""

import argparse
import copy
import os
import re

import boto3
from botocore.exceptions import ClientError


DURABLE_PREFIXES = ("MATERIAL#", "DEPTHPALETTE#", "HOLOCALIBRATION#", "HOLORECIPE#")


def stack_value(cf, stack_name, category, key):
    stack = cf.describe_stacks(StackName=stack_name)["Stacks"][0]
    return next(entry["OutputValue" if category == "Outputs" else "ParameterValue"]
                for entry in stack[category]
                if entry["OutputKey" if category == "Outputs" else "ParameterKey"] == key)


def rewrite(value, source_sub, target_sub, object_keys):
    if isinstance(value, dict):
        return {key: rewrite(part, source_sub, target_sub, object_keys)
                for key, part in value.items()}
    if isinstance(value, list):
        return [rewrite(part, source_sub, target_sub, object_keys) for part in value]
    if not isinstance(value, str):
        return value
    old_prefix = f"users/{source_sub}/"
    if value.startswith(old_prefix):
        object_keys.add((value, f"users/{target_sub}/{value[len(old_prefix):]}"))
        return f"users/{target_sub}/{value[len(old_prefix):]}"
    if value == source_sub:
        return target_sub
    if value == f"USER#{source_sub}":
        return f"USER#{target_sub}"
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-sub", required=True, help="Sub of the admin-invited user in the new staging pool")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", args.target_sub):
        raise ValueError("Target subject must be a Cognito UUID")

    region = os.environ.get("AWS_REGION", "us-east-2")
    session = boto3.Session(region_name=region)
    cf = session.client("cloudformation")
    cognito = session.client("cognito-idp")
    dynamo = session.resource("dynamodb")
    s3 = session.client("s3")
    staging_web = os.environ.get("SERVERLESS_STAGING_WEB_STACK", "mopa-rasterizer-serverless-staging-web")
    production_web = os.environ.get("SERVERLESS_PRODUCTION_WEB_STACK", "mopa-rasterizer-serverless-production-web")
    identity_stack = os.environ.get("SERVERLESS_STAGING_IDENTITY_STACK", "mopa-rasterizer-serverless-staging-identity")
    foundation = os.environ.get("SERVERLESS_STAGING_FOUNDATION_STACK", "mopa-rasterizer-serverless-staging")

    source_sub = stack_value(cf, staging_web, "Parameters", "AllowedUserSub")
    source_pool = stack_value(cf, staging_web, "Parameters", "CognitoUserPoolId")
    production_pool = stack_value(cf, production_web, "Parameters", "CognitoUserPoolId")
    target_pool = stack_value(cf, identity_stack, "Outputs", "UserPoolId")
    if not source_sub or source_pool != production_pool or target_pool == production_pool:
        raise RuntimeError("Expected the current staging pool to be shared with production and the target to be distinct")
    if source_sub == args.target_sub:
        raise RuntimeError("Target subject must differ from the existing staging subject")
    pool = cognito.describe_user_pool(UserPoolId=target_pool)["UserPool"]
    if not pool.get("AdminCreateUserConfig", {}).get("AllowAdminCreateUserOnly"):
        raise RuntimeError("Target pool must have self-signup disabled")
    source_users = cognito.list_users(UserPoolId=source_pool, Filter=f'sub = "{source_sub}"', Limit=2)["Users"]
    target_users = cognito.list_users(UserPoolId=target_pool, Filter=f'sub = "{args.target_sub}"', Limit=2)["Users"]
    if len(source_users) != 1 or len(target_users) != 1:
        raise RuntimeError("Both subjects must identify exactly one Cognito user")
    def email(user):
        return next((entry["Value"].casefold() for entry in user["Attributes"]
                     if entry["Name"] == "email"), "")
    if not email(source_users[0]) or email(source_users[0]) != email(target_users[0]):
        raise RuntimeError("New staging user email must match the existing staging user email")

    table_name = stack_value(cf, foundation, "Outputs", "RuntimeTableName")
    bucket = stack_value(cf, foundation, "Outputs", "ArtifactBucketName")
    if "staging" not in table_name or "staging" not in bucket:
        raise RuntimeError("Refusing to migrate outside staging storage")
    table = dynamo.Table(table_name)
    from boto3.dynamodb.conditions import Key
    items = []
    query_args = {"KeyConditionExpression": Key("pk").eq(f"USER#{source_sub}")}
    while True:
        result = table.query(**query_args)
        items.extend(item for item in result["Items"]
                     if item["sk"] == "PREFERENCES" or item["sk"].startswith(DURABLE_PREFIXES))
        if "LastEvaluatedKey" not in result:
            break
        query_args["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    object_keys = set()
    copies = []
    for item in items:
        transformed = rewrite(copy.deepcopy(item), source_sub, args.target_sub, object_keys)
        transformed["pk"] = f"USER#{args.target_sub}"
        copies.append(transformed)
    for item in copies:
        if "Item" in table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}, ConsistentRead=True):
            raise RuntimeError("Target staging user already has a durable record; refusing to overwrite")
    print(f"Durable records: {len(copies)}; referenced staging objects: {len(object_keys)}")
    if not args.apply:
        print("Dry run only. Add --apply after reviewing the counts.")
        return

    for old_key, new_key in sorted(object_keys):
        try:
            s3.head_object(Bucket=bucket, Key=new_key)
        except ClientError as error:
            if error.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
                raise
        else:
            raise RuntimeError("A destination staging object already exists; refusing to overwrite")
        s3.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": old_key})
    for item in copies:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)")
    print("Durable staging assets copied. Source records and objects were not modified.")


if __name__ == "__main__":
    main()

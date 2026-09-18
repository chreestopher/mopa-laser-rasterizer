#!/usr/bin/env python3
"""Fail a production release if its live Cognito contract has drifted."""

import json
import os
import subprocess
import sys
import time
from urllib.request import Request, urlopen


REGION = os.environ.get("AWS_REGION", "us-east-2")
STACK_NAME = os.environ.get(
    "SERVERLESS_PRODUCTION_WEB_STACK", "mopa-rasterizer-serverless-production-web"
)
POOL_ID = os.environ.get("COGNITO_POOL_ID", "")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "")
ORIGINS = (
    "https://mopa-laser-rasterizer.com/",
    "https://www.mopa-laser-rasterizer.com/",
)


def aws_json(*args):
    options = [*args, "--region", REGION, "--output", "json"]
    try:
        result = subprocess.run(
            ["aws", *options], check=True, capture_output=True, text=True,
        )
    except FileNotFoundError:
        # Also support a local Python environment with awscli but no aws shim.
        result = subprocess.run(
            [sys.executable, "-m", "awscli", *options],
            check=True, capture_output=True, text=True,
        )
    return json.loads(result.stdout)


def verify_stack_and_client(stack, client):
    parameters = {item["ParameterKey"]: item.get("ParameterValue", "") for item in stack["Parameters"]}
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    errors = []
    if parameters.get("StagingHostname") != "mopa-laser-rasterizer.com":
        errors.append("web stack primary hostname is not the production apex")
    if parameters.get("AlternateHostname") != "www.mopa-laser-rasterizer.com":
        errors.append("web stack alternate hostname is not production www")
    if not parameters.get("CloudFrontCertificateArn"):
        errors.append("web stack has no custom-domain certificate")
    if parameters.get("CognitoUserPoolId") != POOL_ID:
        errors.append("web stack uses a different Cognito user pool")
    if outputs.get("PublicUrl") != ORIGINS[0]:
        errors.append("web stack public URL is not the production apex")
    if client.get("ClientId") != outputs.get("CognitoClientId"):
        errors.append("Cognito client ID differs from the web stack output")
    if client.get("ClientSecret"):
        errors.append("Cognito browser client must not require a client secret")
    if client.get("AllowedOAuthFlowsUserPoolClient") is not True:
        errors.append("Cognito client OAuth flow is disabled")
    if sorted(client.get("AllowedOAuthFlows", [])) != ["code"]:
        errors.append("Cognito client must use the authorization-code flow")
    if "COGNITO" not in client.get("SupportedIdentityProviders", []):
        errors.append("Cognito username/password provider is unavailable")
    for field in ("CallbackURLs", "LogoutURLs"):
        if not set(ORIGINS).issubset(set(client.get(field, []))):
            errors.append(f"Cognito client {field} omit a production origin")
    return outputs, errors


def verify_public_config(config, outputs):
    errors = []
    if config.get("client_id") != outputs.get("CognitoClientId"):
        errors.append("published client ID differs from the web stack")
    if config.get("callback_url") != ORIGINS[0]:
        errors.append("published callback URL is not the production apex")
    if config.get("cognito_domain") != COGNITO_DOMAIN:
        errors.append("published Cognito domain differs from release configuration")
    if config.get("api_url") != outputs.get("ApiUrl"):
        errors.append("published API URL differs from the web stack")
    return errors


def main():
    if not POOL_ID or not COGNITO_DOMAIN:
        raise SystemExit("COGNITO_POOL_ID and COGNITO_DOMAIN are required")
    stack = aws_json("cloudformation", "describe-stacks", "--stack-name", STACK_NAME)["Stacks"][0]
    outputs = {item["OutputKey"]: item["OutputValue"] for item in stack["Outputs"]}
    client_id = outputs.get("CognitoClientId")
    if not client_id:
        raise SystemExit("Production web stack has no CognitoClientId output")
    client = aws_json(
        "cognito-idp", "describe-user-pool-client", "--user-pool-id", POOL_ID,
        "--client-id", client_id,
    )["UserPoolClient"]
    outputs, errors = verify_stack_and_client(stack, client)
    for attempt in range(6):
        try:
            request = Request(ORIGINS[0] + "config.json", headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=15) as response:
                config = json.load(response)
            public_errors = verify_public_config(config, outputs)
            if not public_errors:
                break
        except (OSError, ValueError) as exc:
            public_errors = [f"could not read published config: {exc}"]
        if attempt < 5:
            time.sleep(5)
    errors.extend(public_errors)
    if errors:
        for error in errors:
            print(f"Production authentication contract failed: {error}", file=sys.stderr)
        return 1
    print("Production Cognito client, callback origins, and published config match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# Invite the existing staging owner into the isolated pool. Does not cut over the app.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
configure_aws_deployment_credentials
if [ "${1:-}" != "--apply" ]; then
  echo "No user invited. Pass --apply to send the isolated staging invitation." >&2
  exit 2
fi

REGION="${AWS_REGION:-us-east-2}"
STAGING_WEB="${SERVERLESS_STAGING_WEB_STACK:-mopa-rasterizer-serverless-staging-web}"
IDENTITY_STACK="${SERVERLESS_STAGING_IDENTITY_STACK:-mopa-rasterizer-serverless-staging-identity}"
output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue | [0]" --output text
}
parameter() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Parameters[?ParameterKey=='$2'].ParameterValue | [0]" --output text
}

old_pool="$(parameter "$STAGING_WEB" CognitoUserPoolId)"
old_sub="$(parameter "$STAGING_WEB" AllowedUserSub)"
new_pool="$(output "$IDENTITY_STACK" UserPoolId)"
if [ -z "$old_sub" ] || [ "$old_pool" = "$new_pool" ]; then
  echo "Staging identity is already isolated or no allowed user is configured." >&2
  exit 2
fi
signup_policy="$(aws cognito-idp describe-user-pool --region "$REGION" --user-pool-id "$new_pool" \
  --query 'UserPool.AdminCreateUserConfig.AllowAdminCreateUserOnly' --output text)"
if [ "$signup_policy" != "True" ]; then
  echo "New staging pool is not invite-only." >&2
  exit 2
fi
email="$(aws cognito-idp list-users --region "$REGION" --user-pool-id "$old_pool" \
  --filter "sub = \"$old_sub\"" --query "Users[0].Attributes[?Name=='email'].Value | [0]" --output text)"
if [ -z "$email" ] || [ "$email" = "None" ]; then
  echo "Existing staging user email could not be resolved." >&2
  exit 2
fi
existing="$(aws cognito-idp list-users --region "$REGION" --user-pool-id "$new_pool" \
  --filter "email = \"$email\"" --query "Users[0].Attributes[?Name=='sub'].Value | [0]" --output text)"
if [ -n "$existing" ] && [ "$existing" != "None" ]; then
  echo "Staging admin already invited. New subject: $existing"
  exit 0
fi
new_sub="$(aws cognito-idp admin-create-user --region "$REGION" --user-pool-id "$new_pool" \
  --username "$email" --user-attributes "Name=email,Value=$email" "Name=email_verified,Value=true" \
  --desired-delivery-mediums EMAIL \
  --query "User.Attributes[?Name=='sub'].Value | [0]" --output text)"
if [ -z "$new_sub" ] || [ "$new_sub" = "None" ]; then
  echo "Invitation was sent, but new subject could not be resolved; inspect Cognito before retrying." >&2
  exit 1
fi
echo "Staging-only invitation sent. New subject: $new_sub. Complete the temporary-password sign-in after web cutover."

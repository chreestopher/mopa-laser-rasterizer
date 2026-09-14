#!/usr/bin/env bash
# Reconcile the management-account administrator in an existing organization
# instance of IAM Identity Center. Organization-instance activation is a
# console-only AWS operation and must be completed before running this script.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_IDENTITY_CENTER_REGION:-us-east-2}"
ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ADMIN_EMAIL="${1:-${IDENTITY_CENTER_ADMIN_EMAIL:-}}"
ADMIN_USERNAME="${2:-${IDENTITY_CENTER_ADMIN_USERNAME:-}}"
ADMIN_GIVEN_NAME="${IDENTITY_CENTER_ADMIN_GIVEN_NAME:-AWS}"
ADMIN_FAMILY_NAME="${IDENTITY_CENTER_ADMIN_FAMILY_NAME:-Admin}"
ADMIN_GROUP_NAME="${IDENTITY_CENTER_ADMIN_GROUP:-Admin team}"
PERMISSION_SET_NAME="${IDENTITY_CENTER_PERMISSION_SET:-AdministratorAccess}"
ADMIN_POLICY_ARN="arn:aws:iam::aws:policy/AdministratorAccess"

if [ -z "$ADMIN_EMAIL" ] || [ -z "$ADMIN_USERNAME" ]; then
  echo "Usage: $0 ADMIN_EMAIL [ADMIN_USERNAME]" >&2
  exit 2
fi

if ! aws organizations describe-organization >/dev/null 2>&1; then
  echo "This account must first be the management account of an AWS Organization." >&2
  exit 2
fi
aws organizations enable-aws-service-access --service-principal sso.amazonaws.com

INSTANCE_ARN="$(aws sso-admin list-instances --region "$REGION" \
  --query 'Instances[0].InstanceArn' --output text)"
IDENTITY_STORE_ID="$(aws sso-admin list-instances --region "$REGION" \
  --query 'Instances[0].IdentityStoreId' --output text)"
if [ -z "$INSTANCE_ARN" ] || [ "$INSTANCE_ARN" = "None" ]; then
  echo "No IAM Identity Center organization instance exists in $REGION." >&2
  echo "Enable it in the AWS console with permission sets enabled, then rerun." >&2
  exit 2
fi

USER_ID="$(aws identitystore list-users --region "$REGION" \
  --identity-store-id "$IDENTITY_STORE_ID" \
  --filters "AttributePath=UserName,AttributeValue=${ADMIN_USERNAME}" \
  --query 'Users[0].UserId' --output text)"
if [ -z "$USER_ID" ] || [ "$USER_ID" = "None" ]; then
  echo "Creating Identity Center user: $ADMIN_USERNAME"
  USER_ID="$(aws identitystore create-user --region "$REGION" \
    --identity-store-id "$IDENTITY_STORE_ID" \
    --user-name "$ADMIN_USERNAME" --display-name "$ADMIN_USERNAME" \
    --name "Formatted=${ADMIN_GIVEN_NAME} ${ADMIN_FAMILY_NAME},GivenName=${ADMIN_GIVEN_NAME},FamilyName=${ADMIN_FAMILY_NAME}" \
    --emails "Value=${ADMIN_EMAIL},Type=work,Primary=true" \
    --query UserId --output text)"
fi

GROUP_ID="$(aws identitystore list-groups --region "$REGION" \
  --identity-store-id "$IDENTITY_STORE_ID" \
  --filters "AttributePath=DisplayName,AttributeValue=${ADMIN_GROUP_NAME}" \
  --query 'Groups[0].GroupId' --output text)"
if [ -z "$GROUP_ID" ] || [ "$GROUP_ID" = "None" ]; then
  echo "Creating Identity Center group: $ADMIN_GROUP_NAME"
  GROUP_ID="$(aws identitystore create-group --region "$REGION" \
    --identity-store-id "$IDENTITY_STORE_ID" --display-name "$ADMIN_GROUP_NAME" \
    --description "Administrators for the MOPA Laser Rasterizer AWS account" \
    --query GroupId --output text)"
fi

MEMBERSHIP_ID="$(aws identitystore list-group-memberships --region "$REGION" \
  --identity-store-id "$IDENTITY_STORE_ID" --group-id "$GROUP_ID" \
  --query "GroupMemberships[?MemberId.UserId=='${USER_ID}'].MembershipId | [0]" \
  --output text)"
if [ -z "$MEMBERSHIP_ID" ] || [ "$MEMBERSHIP_ID" = "None" ]; then
  echo "Adding $ADMIN_USERNAME to $ADMIN_GROUP_NAME"
  aws identitystore create-group-membership --region "$REGION" \
    --identity-store-id "$IDENTITY_STORE_ID" --group-id "$GROUP_ID" \
    --member-id "UserId=${USER_ID}" >/dev/null
fi

PERMISSION_SET_ARN=""
for candidate_arn in $(aws sso-admin list-permission-sets --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --query 'PermissionSets[]' --output text); do
  candidate_name="$(aws sso-admin describe-permission-set --region "$REGION" \
    --instance-arn "$INSTANCE_ARN" --permission-set-arn "$candidate_arn" \
    --query 'PermissionSet.Name' --output text)"
  if [ "$candidate_name" = "$PERMISSION_SET_NAME" ]; then
    PERMISSION_SET_ARN="$candidate_arn"
    break
  fi
done
if [ -z "$PERMISSION_SET_ARN" ]; then
  echo "Creating permission set: $PERMISSION_SET_NAME"
  PERMISSION_SET_ARN="$(aws sso-admin create-permission-set --region "$REGION" \
    --instance-arn "$INSTANCE_ARN" --name "$PERMISSION_SET_NAME" \
    --description "Administrative access for account management; do not use root for daily work" \
    --session-duration PT4H --query 'PermissionSet.PermissionSetArn' --output text)"
fi
POLICY_ATTACHED="$(aws sso-admin list-managed-policies-in-permission-set \
  --region "$REGION" --instance-arn "$INSTANCE_ARN" \
  --permission-set-arn "$PERMISSION_SET_ARN" \
  --query "AttachedManagedPolicies[?Arn=='${ADMIN_POLICY_ARN}'].Arn | [0]" \
  --output text)"
if [ -z "$POLICY_ATTACHED" ] || [ "$POLICY_ATTACHED" = "None" ]; then
  aws sso-admin attach-managed-policy-to-permission-set --region "$REGION" \
    --instance-arn "$INSTANCE_ARN" --permission-set-arn "$PERMISSION_SET_ARN" \
    --managed-policy-arn "$ADMIN_POLICY_ARN"
fi

ASSIGNMENT_EXISTS="$(aws sso-admin list-account-assignments --region "$REGION" \
  --instance-arn "$INSTANCE_ARN" --account-id "$ACCOUNT_ID" \
  --permission-set-arn "$PERMISSION_SET_ARN" \
  --query "AccountAssignments[?PrincipalType=='GROUP' && PrincipalId=='${GROUP_ID}'].PrincipalId | [0]" \
  --output text)"
if [ -z "$ASSIGNMENT_EXISTS" ] || [ "$ASSIGNMENT_EXISTS" = "None" ]; then
  echo "Assigning $PERMISSION_SET_NAME to $ADMIN_GROUP_NAME in $ACCOUNT_ID"
  REQUEST_ID="$(aws sso-admin create-account-assignment --region "$REGION" \
    --instance-arn "$INSTANCE_ARN" --target-id "$ACCOUNT_ID" \
    --target-type AWS_ACCOUNT --permission-set-arn "$PERMISSION_SET_ARN" \
    --principal-type GROUP --principal-id "$GROUP_ID" \
    --query 'AccountAssignmentCreationStatus.RequestId' --output text)"
  while true; do
    STATUS="$(aws sso-admin describe-account-assignment-creation-status \
      --region "$REGION" --instance-arn "$INSTANCE_ARN" \
      --account-assignment-creation-request-id "$REQUEST_ID" \
      --query 'AccountAssignmentCreationStatus.Status' --output text)"
    case "$STATUS" in
      SUCCEEDED) break ;;
      FAILED)
        aws sso-admin describe-account-assignment-creation-status \
          --region "$REGION" --instance-arn "$INSTANCE_ARN" \
          --account-assignment-creation-request-id "$REQUEST_ID"
        exit 1
        ;;
      *) sleep 2 ;;
    esac
  done
fi

printf 'Identity Center administrator ready.\nREGION=%s\nACCOUNT_ID=%s\nINSTANCE_ARN=%s\nIDENTITY_STORE_ID=%s\nUSER_ID=%s\nGROUP_ID=%s\nPERMISSION_SET_ARN=%s\n' \
  "$REGION" "$ACCOUNT_ID" "$INSTANCE_ARN" "$IDENTITY_STORE_ID" \
  "$USER_ID" "$GROUP_ID" "$PERMISSION_SET_ARN"

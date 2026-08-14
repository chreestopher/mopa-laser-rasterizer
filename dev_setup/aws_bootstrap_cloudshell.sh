#!/usr/bin/env bash
# Run from AWS CloudShell. Creates repeatable account-level app resources.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET_NAME="${S3_BUCKET_NAME:-mopa-laser-rasterizer-artifacts-${ACCOUNT_ID}}"
TABLE_NAME="${DYNAMODB_TABLE_NAME:-mopa-laser-rasterizer-users}"
ROLE_NAME="${EC2_ROLE_NAME:-mopa-laser-rasterizer-ec2}"
PROFILE_NAME="${EC2_PROFILE_NAME:-mopa-laser-rasterizer-ec2}"

echo "Configuring bucket: $BUCKET_NAME"
if ! aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
  aws s3api create-bucket --bucket "$BUCKET_NAME" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=${REGION}"
fi
aws s3api put-public-access-block --bucket "$BUCKET_NAME" --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
aws s3api put-bucket-encryption --bucket "$BUCKET_NAME" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET_NAME" --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-guest-job-artifacts-after-7-days","Status":"Enabled","Filter":{"Prefix":"jobs/"},"Expiration":{"Days":7},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}},{"ID":"expire-account-job-artifacts-after-7-days","Status":"Enabled","Filter":{"Tag":{"Key":"mopa-retention","Value":"job"}},"Expiration":{"Days":7},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

echo "Configuring DynamoDB table: $TABLE_NAME"
if ! aws dynamodb describe-table --table-name "$TABLE_NAME" --region "$REGION" >/dev/null 2>&1; then
  aws dynamodb create-table --table-name "$TABLE_NAME" --region "$REGION" \
    --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST >/dev/null
  aws dynamodb wait table-exists --table-name "$TABLE_NAME" --region "$REGION"
fi

TRUST_FILE="$(mktemp)"; POLICY_FILE="$(mktemp)"
trap 'rm -f "$TRUST_FILE" "$POLICY_FILE"' EXIT
printf '%s' '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' > "$TRUST_FILE"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "file://${TRUST_FILE}" >/dev/null
fi
cat > "$POLICY_FILE" <<JSON
{"Version":"2012-10-17","Statement":[
{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::${BUCKET_NAME}"},
{"Effect":"Allow","Action":["s3:GetObject","s3:PutObject","s3:DeleteObject"],"Resource":"arn:aws:s3:::${BUCKET_NAME}/*"},
{"Effect":"Allow","Action":["dynamodb:BatchGetItem","dynamodb:BatchWriteItem","dynamodb:DeleteItem","dynamodb:DescribeTable","dynamodb:GetItem","dynamodb:PutItem","dynamodb:Query","dynamodb:UpdateItem"],"Resource":"arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${TABLE_NAME}"}]}
JSON
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name MopaRasterizerAccountData --policy-document "file://${POLICY_FILE}"
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
fi
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" --query "InstanceProfile.Roles[?RoleName=='${ROLE_NAME}'].RoleName" --output text | grep -q "$ROLE_NAME"; then
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME"
fi

echo
echo "Bootstrap complete. Attach instance profile '$PROFILE_NAME' to the replacement EC2 instance."
printf 'AWS_REGION=%s\nS3_BUCKET_NAME=%s\nDYNAMODB_TABLE_NAME=%s\n' "$REGION" "$BUCKET_NAME" "$TABLE_NAME"

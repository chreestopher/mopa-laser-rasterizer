#!/usr/bin/env bash
# Read-only AWS inventory for the parallel serverless production deployment.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
export AWS_PAGER=""
PRIMARY_HOSTNAME="${SERVERLESS_PRODUCTION_HOSTNAME:-mopa-laser-rasterizer.com}"
ALTERNATE_HOSTNAME="${SERVERLESS_PRODUCTION_ALTERNATE_HOSTNAME:-www.mopa-laser-rasterizer.com}"
STAGING_WORKER_STACK="${SERVERLESS_STAGING_WORKER_STACK:-mopa-rasterizer-serverless-staging-worker}"

for name in S3_BUCKET_NAME DYNAMODB_TABLE_NAME COGNITO_POOL_ID COGNITO_DOMAIN; do
  [ -n "${!name:-}" ] || { echo "$name is required in .env.aws." >&2; exit 2; }
done

echo "AWS identity"
aws sts get-caller-identity --region "$REGION" --query '{Account:Account,Arn:Arn}' --output json

echo "CloudFormation template validation"
aws cloudformation validate-template --region "$REGION" \
  --template-body "file://$REPO_ROOT/ecs/serverless-production-foundation.yaml" \
  --query Description --output text
aws cloudformation validate-template --region "$REGION" \
  --template-body "file://$REPO_ROOT/ecs/serverless-staging-web.yaml" \
  --query Description --output text

echo "Existing production-serverless stacks"
aws cloudformation list-stacks --region "$REGION" \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE \
  --query "StackSummaries[?contains(StackName, 'serverless-production')].{Name:StackName,Status:StackStatus}" \
  --output table

echo "Validated staging worker image"
TASK_DEFINITION="$(aws cloudformation describe-stacks --region "$REGION" \
  --stack-name "$STAGING_WORKER_STACK" \
  --query "Stacks[0].Outputs[?OutputKey=='TaskDefinitionArn'].OutputValue" --output text)"
aws ecs describe-task-definition --region "$REGION" --task-definition "$TASK_DEFINITION" \
  --query 'taskDefinition.{Revision:revision,Image:containerDefinitions[0].image,Cpu:cpu,Memory:memory}' \
  --output json

echo "Production durable stores"
aws s3api head-bucket --region "$REGION" --bucket "$S3_BUCKET_NAME"
aws dynamodb describe-table --region "$REGION" --table-name "$DYNAMODB_TABLE_NAME" \
  --query 'Table.{Status:TableStatus,ItemCount:ItemCount,KeySchema:KeySchema,PointInTimeRecovery:PITRDescription}' \
  --output json

echo "Issued CloudFront-region certificates"
aws acm list-certificates --region us-east-1 --certificate-statuses ISSUED \
  --query "CertificateSummaryList[?DomainName=='$PRIMARY_HOSTNAME' || DomainName=='$ALTERNATE_HOSTNAME' || DomainName=='*.$PRIMARY_HOSTNAME'].{Domain:DomainName,Arn:CertificateArn}" \
  --output table

echo "CloudFront aliases using either production hostname"
aws cloudfront list-distributions \
  --query "DistributionList.Items[?contains(Aliases.Items || [''], '$PRIMARY_HOSTNAME') || contains(Aliases.Items || [''], '$ALTERNATE_HOSTNAME')].{Id:Id,Domain:DomainName,Aliases:Aliases.Items,Enabled:Enabled}" \
  --output json

ROOT_DOMAIN="${PRIMARY_HOSTNAME#www.}"
ZONE_ID="$(aws route53 list-hosted-zones-by-name --dns-name "$ROOT_DOMAIN." \
  --query "HostedZones[?Name=='$ROOT_DOMAIN.'] | [0].Id" --output text)"
echo "Current production Route 53 web records (rollback source)"
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --query "ResourceRecordSets[?Name=='$PRIMARY_HOSTNAME.' || Name=='$ALTERNATE_HOSTNAME.'].{Name:Name,Type:Type,Alias:AliasTarget.DNSName,TTL:TTL,Values:ResourceRecords[].Value}" \
  --output json

echo "Read-only production readiness inventory complete."

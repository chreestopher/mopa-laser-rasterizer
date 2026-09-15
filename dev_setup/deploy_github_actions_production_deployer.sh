#!/usr/bin/env bash
# Administrator bootstrap for the narrowly scoped production GitHub OIDC role.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

if [ "${1:-}" != "--apply" ]; then
  echo "No IAM changes made. Pass --apply after reviewing ecs/github-actions-production-deployer.yaml." >&2
  exit 2
fi

configure_aws_deployment_credentials
REGION="${AWS_REGION:-us-east-2}"
FOUNDATION_STACK="${SERVERLESS_PRODUCTION_FOUNDATION_STACK:-mopa-rasterizer-serverless-production}"
WORKER_STACK="${SERVERLESS_PRODUCTION_WORKER_STACK:-mopa-rasterizer-serverless-production-worker}"
ORCHESTRATION_STACK="${SERVERLESS_PRODUCTION_ORCHESTRATION_STACK:-mopa-rasterizer-serverless-production-orchestration}"
WEB_STACK="${SERVERLESS_PRODUCTION_WEB_STACK:-mopa-rasterizer-serverless-production-web}"
ROLE_STACK="${GITHUB_PRODUCTION_DEPLOYER_STACK:-mopa-rasterizer-github-production-deployer}"

account_id="$(aws sts get-caller-identity --query Account --output text)"
output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}
resource() {
  aws cloudformation describe-stack-resource --region "$REGION" --stack-name "$1" \
    --logical-resource-id "$2" --query StackResourceDetail.PhysicalResourceId --output text
}
role_name() {
  local arn="$1"
  printf '%s' "${arn##*/}"
}

artifact_bucket="$(output "$FOUNDATION_STACK" ArtifactBucketName)"
static_bucket="$(output "$FOUNDATION_STACK" StaticBucketName)"
runtime_table="$(output "$FOUNDATION_STACK" RuntimeTableName)"
distribution_id="$(output "$WEB_STACK" DistributionId)"
oac_id="$(resource "$WEB_STACK" DistributionOac)"
headers_id="$(resource "$WEB_STACK" StaticSecurityHeadersPolicy)"
api_id="$(resource "$WEB_STACK" HttpApi)"
execution_role="$(role_name "$(output "$WORKER_STACK" TaskExecutionRoleArn)")"
task_role="$(role_name "$(output "$WORKER_STACK" TaskRoleArn)")"
workflow_role="$(resource "$ORCHESTRATION_STACK" WorkflowRole)"
pipe_role="$(resource "$ORCHESTRATION_STACK" PipeRole)"
api_role="$(resource "$WEB_STACK" ApiRole)"
oidc_arn="arn:aws:iam::${account_id}:oidc-provider/token.actions.githubusercontent.com"

aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$oidc_arn" >/dev/null

aws cloudformation deploy --region "$REGION" --stack-name "$ROLE_STACK" \
  --template-file "$REPO_ROOT/ecs/github-actions-production-deployer.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    "GitHubOidcProviderArn=$oidc_arn" \
    "ArtifactBucketName=$artifact_bucket" \
    "StaticBucketName=$static_bucket" \
    "RuntimeTableName=$runtime_table" \
    "DistributionId=$distribution_id" \
    "OriginAccessControlId=$oac_id" \
    "ResponseHeadersPolicyId=$headers_id" \
    "ApiGatewayId=$api_id" \
    "WorkerExecutionRoleName=$execution_role" \
    "WorkerTaskRoleName=$task_role" \
    "PipeRoleName=$pipe_role" \
    "WorkflowRoleName=$workflow_role" \
    "ApiRoleName=$api_role" \
    "CognitoUserPoolId=$COGNITO_POOL_ID" \
  --no-fail-on-empty-changeset

role_arn="$(output "$ROLE_STACK" RoleArn)"
echo "Production GitHub deployer role is ready."
echo "Set serverless-production environment variable AWS_PRODUCTION_DEPLOY_ROLE_ARN to: $role_arn"

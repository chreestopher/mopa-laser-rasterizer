#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
NAMESPACE="${K8S_NAMESPACE:-default}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
ECR_PASSWORD="$(aws ecr get-login-password --region "$REGION")"

kubectl create secret docker-registry ecr-registry \
  --namespace "$NAMESPACE" \
  --docker-server="$REGISTRY" \
  --docker-username=AWS \
  --docker-password="$ECR_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

unset ECR_PASSWORD
echo "Refreshed ECR pull secret in namespace $NAMESPACE."

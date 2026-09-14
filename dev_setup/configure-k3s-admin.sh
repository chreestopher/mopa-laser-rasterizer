#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
ADMIN_EMAIL_VALUE="${1:-${IDENTITY_CENTER_ADMIN_EMAIL:-}}"
REGION="${AWS_REGION:-us-east-2}"
POOL_ID="${COGNITO_POOL_ID:-}"
ROLE_NAME="${ADMIN_IAM_ROLE_NAME:-mopa-laser-rasterizer-ec2}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"

if [ -z "$ADMIN_EMAIL_VALUE" ] || [[ "$ADMIN_EMAIL_VALUE" != *@*.* ]] || [ -z "$POOL_ID" ]; then
  echo "Usage: bash dev_setup/configure-k3s-admin.sh you@example.com" >&2
  exit 2
fi

export KUBECONFIG="$KUBECONFIG_PATH"
kubectl create secret generic mopa-rasterizer-admin \
  --from-literal="ADMIN_EMAIL=$ADMIN_EMAIL_VALUE" \
  --dry-run=client -o yaml | kubectl apply -f -

POLICY_DOCUMENT="$(printf '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"cognito-idp:ListUsers","Resource":"arn:aws:cognito-idp:%s:*:userpool/%s"}]}' "$REGION" "$POOL_ID")"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name MopaRasterizerAdminDirectory \
  --policy-document "$POLICY_DOCUMENT"

kubectl set env deployment/mopa-laser-rasterizer \
  --from=secret/mopa-rasterizer-admin
kubectl set env deployment/mopa-laser-rasterizer \
  "COGNITO_POOL_ID=$POOL_ID"
kubectl rollout status deployment/mopa-laser-rasterizer --timeout=10m
echo "Admin access configured for $ADMIN_EMAIL_VALUE."

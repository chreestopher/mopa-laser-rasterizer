#!/usr/bin/env bash
# Render production identifiers and one immutable image into the AWS manifests.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

IMAGE_URI="${1:-}"
WEB_OUTPUT="${2:-}"
WORKER_OUTPUT="${3:-}"
REGION="${AWS_REGION:-us-east-2}"

if [ -z "$IMAGE_URI" ] || [ -z "$WEB_OUTPUT" ] || [ -z "$WORKER_OUTPUT" ]; then
  echo "Usage: $0 IMAGE_URI WEB_OUTPUT WORKER_OUTPUT" >&2
  exit 2
fi

required=(S3_BUCKET_NAME DYNAMODB_TABLE_NAME COGNITO_POOL_ID COGNITO_CLIENT_ID COGNITO_DOMAIN)
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "$name is required in .env.aws or the shell environment." >&2
    exit 2
  fi
done

render_manifest() {
  sed \
    -e "s|image: mopa-laser-rasterizer:com|image: ${IMAGE_URI}|" \
    -e "s|__AWS_REGION__|${REGION}|g" \
    -e "s|__S3_BUCKET_NAME__|${S3_BUCKET_NAME}|g" \
    -e "s|__DYNAMODB_TABLE_NAME__|${DYNAMODB_TABLE_NAME}|g" \
    -e "s|__COGNITO_POOL_ID__|${COGNITO_POOL_ID}|g" \
    -e "s|__COGNITO_CLIENT_ID__|${COGNITO_CLIENT_ID}|g" \
    -e "s|__COGNITO_DOMAIN__|${COGNITO_DOMAIN}|g" \
    "$1" > "$2"
  if grep -Eq '__[A-Z0-9_]+__' "$2"; then
    echo "Unresolved placeholder in rendered manifest: $2" >&2
    exit 2
  fi
}

render_manifest "$REPO_ROOT/k8s/deployment.aws.yaml" "$WEB_OUTPUT"
render_manifest "$REPO_ROOT/k8s/worker.aws.yaml" "$WORKER_OUTPUT"

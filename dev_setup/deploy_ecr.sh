#!/usr/bin/env bash
# Build an immutable image, push it to private ECR, and deploy that exact image
# to both the web and dedicated raster-worker workloads.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
REPOSITORY="${ECR_REPOSITORY:-mopa-laser-rasterizer}"
NAMESPACE="${K8S_NAMESPACE:-default}"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
CONTEXT="${BUILD_CONTEXT:-.}"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
WEB_MANIFEST="$REPO_ROOT/k8s/deployment.aws.yaml"
WORKER_MANIFEST="$REPO_ROOT/k8s/worker.aws.yaml"
LIFECYCLE_POLICY="$SCRIPT_DIR/ecr-lifecycle-policy.json"
WORKSTATION_KUBECONFIG="$HOME/.kube/mopa-rasterizer-production.yaml"
# Space-separated EC2 instance IDs for k3s workers without outbound access.
PRIVATE_WORKER_INSTANCE_IDS="${K3S_PRIVATE_WORKER_INSTANCE_IDS:-}"

required=(S3_BUCKET_NAME DYNAMODB_TABLE_NAME COGNITO_POOL_ID COGNITO_CLIENT_ID COGNITO_DOMAIN)
for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "$name is required in .env.aws or the shell environment." >&2
    exit 2
  fi
done

if ! aws configure list-profiles | grep -Fxq "$AWS_PROFILE"; then
  echo "AWS profile '$AWS_PROFILE' has not been configured." >&2
  echo "Run: aws configure sso --profile $AWS_PROFILE --use-device-code" >&2
  exit 1
fi

if [ -z "${KUBECONFIG:-}" ] && [ -f "$WORKSTATION_KUBECONFIG" ]; then
  export KUBECONFIG="$WORKSTATION_KUBECONFIG"
fi

if ! ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"; then
  echo "AWS profile '$AWS_PROFILE' is not authenticated." >&2
  echo "Run: aws sso login --profile $AWS_PROFILE --use-device-code" >&2
  exit 1
fi
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
if [ "$#" -ge 1 ]; then
  IMAGE_TAG="$1"
else
  GIT_REV="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"
  IMAGE_TAG="${GIT_REV}-$(date -u +%Y%m%d%H%M%S)"
fi
IMAGE_URI="${REGISTRY}/${REPOSITORY}:${IMAGE_TAG}"

run_kubectl() {
  if [ -n "${KUBECONFIG:-}" ] || [ "$(id -u)" -eq 0 ]; then
    kubectl "$@"
  else
    sudo kubectl "$@"
  fi
}

if ! run_kubectl cluster-info >/dev/null 2>&1; then
  echo "kubectl cannot reach the deployment cluster." >&2
  echo "From WSL, run dev_setup/start-k3s-tunnel.sh first." >&2
  exit 1
fi

echo "Ensuring private ECR repository ${REPOSITORY} exists in ${REGION}"
if ! aws ecr describe-repositories --region "$REGION" \
  --repository-names "$REPOSITORY" >/dev/null 2>&1; then
  aws ecr create-repository --region "$REGION" \
    --repository-name "$REPOSITORY" \
    --image-tag-mutability IMMUTABLE \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256 >/dev/null
fi
aws ecr put-lifecycle-policy --region "$REGION" \
  --repository-name "$REPOSITORY" \
  --lifecycle-policy-text "file://${LIFECYCLE_POLICY}" >/dev/null

echo "Authenticating Docker to ${REGISTRY}"
aws ecr get-login-password --region "$REGION" | \
  docker login --username AWS --password-stdin "$REGISTRY"

echo "Building ${IMAGE_URI}"
docker build --pull -f "$DOCKERFILE" -t "$IMAGE_URI" "$CONTEXT"
docker push "$IMAGE_URI"

# Private workers cannot pull from ECR or Docker Hub without NAT or VPC
# endpoints. Preload the exact immutable image before updating the deployment.
for worker_instance_id in $PRIVATE_WORKER_INSTANCE_IDS; do
  bash "$SCRIPT_DIR/preload-k3s-worker-image.sh" "$worker_instance_id" "$IMAGE_URI"
done

# Refresh the cluster pull secret during each deployment. ECR tokens expire,
# so unattended node provisioning should additionally use the AWS ECR kubelet
# credential provider described in the disaster-recovery runbook.
ECR_PASSWORD="$(aws ecr get-login-password --region "$REGION")"
run_kubectl create secret docker-registry ecr-registry \
  --namespace "$NAMESPACE" \
  --docker-server="$REGISTRY" \
  --docker-username=AWS \
  --docker-password="$ECR_PASSWORD" \
  --dry-run=client -o yaml | run_kubectl apply -f -
unset ECR_PASSWORD

# Render the immutable image into both manifests before applying them. This
# avoids briefly rolling a live deployment back to the local fallback image.
WEB_RENDERED="$(mktemp)"
WORKER_RENDERED="$(mktemp)"
trap 'rm -f "$WEB_RENDERED" "$WORKER_RENDERED"' EXIT
bash "$SCRIPT_DIR/render-aws-k8s-manifests.sh" "$IMAGE_URI" "$WEB_RENDERED" "$WORKER_RENDERED"

echo "Deploying ${IMAGE_URI}"
run_kubectl apply -f "$WEB_RENDERED"
run_kubectl apply -f "$WORKER_RENDERED"
run_kubectl rollout status deployment/mopa-laser-rasterizer \
  --namespace "$NAMESPACE" --timeout=20m
run_kubectl rollout status deployment/mopa-laser-raster-worker \
  --namespace "$NAMESPACE" --timeout=120m

echo "Deployment complete: ${IMAGE_URI}"

#!/usr/bin/env bash
# Build once and deploy the same immutable image to Fargate and K3s web pods.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"

REGION="${AWS_REGION:-us-east-2}"
export AWS_PROFILE="${DEPLOY_AWS_PROFILE:-mopa-admin}"
NAMESPACE="${K8S_NAMESPACE:-default}"
REPOSITORY="${ECR_REPOSITORY:-mopa-laser-rasterizer}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"
export KUBECONFIG="$KUBECONFIG_PATH"

for command_name in aws docker kubectl git; do
  command -v "$command_name" >/dev/null || { echo "Missing command: $command_name" >&2; exit 2; }
done
if [ ! -f "$KUBECONFIG_PATH" ]; then
  echo "Production kubeconfig not found: $KUBECONFIG_PATH" >&2
  exit 2
fi
if ! kubectl cluster-info >/dev/null 2>&1; then
  echo "The production K3s tunnel is not reachable. Run dev_setup/start-k3s-tunnel.sh first." >&2
  exit 2
fi
if ! ACCOUNT_ID="$(aws sts get-caller-identity --region "$REGION" --query Account --output text)"; then
  echo "AWS profile '$AWS_PROFILE' is not authenticated." >&2
  echo "Run: aws sso login --profile $AWS_PROFILE --use-device-code" >&2
  exit 2
fi

if [ "$#" -ge 1 ]; then
  IMAGE_TAG="$1"
else
  GIT_REV="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"
  IMAGE_TAG="deploy-${GIT_REV}-$(date -u +%Y%m%d%H%M%S)"
fi
IMAGE_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPOSITORY}:${IMAGE_TAG}"

echo "Deploying one production image to Fargate and K3s: $IMAGE_URI"
if aws ecr describe-images --region "$REGION" --repository-name "$REPOSITORY" \
  --image-ids "imageTag=$IMAGE_TAG" >/dev/null 2>&1; then
  echo "Reusing existing immutable ECR image: $IMAGE_URI"
  FARGATE_IMAGE_URI="$IMAGE_URI" bash "$SCRIPT_DIR/deploy_fargate_worker_production.sh" "$IMAGE_TAG"
else
  bash "$SCRIPT_DIR/deploy_fargate_worker_production.sh" "$IMAGE_TAG"
fi

if ! docker image inspect "$IMAGE_URI" >/dev/null 2>&1; then
  aws ecr get-login-password --region "$REGION" | \
    docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
  docker pull "$IMAGE_URI"
fi

for worker_instance_id in ${K3S_PRIVATE_WORKER_INSTANCE_IDS:-}; do
  bash "$SCRIPT_DIR/preload-k3s-worker-image.sh" "$worker_instance_id" "$IMAGE_URI"
done
bash "$SCRIPT_DIR/refresh-ecr-pull-secret.sh"

WEB_RENDERED="$(mktemp)"
WORKER_RENDERED="$(mktemp)"
trap 'rm -f "$WEB_RENDERED" "$WORKER_RENDERED"' EXIT
bash "$SCRIPT_DIR/render-aws-k8s-manifests.sh" "$IMAGE_URI" "$WEB_RENDERED" "$WORKER_RENDERED"

kubectl apply --namespace "$NAMESPACE" -f "$WEB_RENDERED"
kubectl apply --namespace "$NAMESPACE" -f "$WORKER_RENDERED"
kubectl rollout status deployment/mopa-laser-rasterizer --namespace "$NAMESPACE" --timeout=20m
kubectl rollout status deployment/mopa-laser-raster-worker --namespace "$NAMESPACE" --timeout=120m

LIVE_IMAGE="$(kubectl get deployment mopa-laser-rasterizer --namespace "$NAMESPACE" \
  -o jsonpath='{.spec.template.spec.containers[0].image}')"
WORKER_REPLICAS="$(kubectl get deployment mopa-laser-raster-worker --namespace "$NAMESPACE" \
  -o jsonpath='{.spec.replicas}')"
if [ "$LIVE_IMAGE" != "$IMAGE_URI" ] || [ "$WORKER_REPLICAS" != "0" ]; then
  echo "Post-deployment verification failed." >&2
  exit 1
fi

echo "Production rollout complete: $IMAGE_URI"
echo "K3s web image verified; legacy K3s worker replicas: $WORKER_REPLICAS"

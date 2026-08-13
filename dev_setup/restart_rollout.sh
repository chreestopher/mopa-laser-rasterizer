#!/usr/bin/env sh
# Apply the canonical AWS deployment, restart it, and wait for the new pods.
# Applying first keeps the live volume mounts in sync with the repository.
set -eu

DEPLOYMENT_NAME=${1:-mopa-laser-rasterizer}
NAMESPACE=${2:-default}
IMAGE_REFERENCE=${3:-}
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AWS_DEPLOYMENT_MANIFEST="$SCRIPT_DIR/../k8s/deployment.aws.yaml"

if [ ! -f "$AWS_DEPLOYMENT_MANIFEST" ]; then
    echo "AWS deployment manifest not found: $AWS_DEPLOYMENT_MANIFEST" >&2
    exit 1
fi

run_kubectl() {
    if [ "$(id -u)" -eq 0 ]; then
        kubectl "$@"
    else
        sudo kubectl "$@"
    fi
}

echo "Applying $AWS_DEPLOYMENT_MANIFEST"
run_kubectl apply -f "$AWS_DEPLOYMENT_MANIFEST"
if [ -n "$IMAGE_REFERENCE" ]; then
    run_kubectl set image "deployment/$DEPLOYMENT_NAME" \
        "mopa-laser-rasterizer=$IMAGE_REFERENCE" -n "$NAMESPACE"
fi
run_kubectl rollout restart "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE"
run_kubectl rollout status "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE"

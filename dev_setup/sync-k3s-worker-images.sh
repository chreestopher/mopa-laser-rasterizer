#!/usr/bin/env bash
# Copy the system, init, and current Rasterizer worker images from the k3s
# server to a private worker node that has no outbound internet route.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
SERVER_INSTANCE_ID="${K3S_INSTANCE_ID:-}"
WORKER_INSTANCE_ID="${1:-${K3S_WORKER_INSTANCE_ID:-}}"
SSH_USER="${K3S_SSH_USER:-ubuntu}"
SSH_KEY="${K3S_SSH_KEY:-}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"

if [ -z "$WORKER_INSTANCE_ID" ] || [ -z "$SERVER_INSTANCE_ID" ] || [ -z "$SSH_KEY" ]; then
  echo "Usage: $0 <worker-instance-id>" >&2
  exit 2
fi

instance_value() {
  aws ec2 describe-instances --region "$REGION" --instance-ids "$1" \
    --query "Reservations[0].Instances[0].$2" --output text
}

SERVER_PUBLIC_IP="$(instance_value "$SERVER_INSTANCE_ID" PublicIpAddress)"
WORKER_PRIVATE_IP="$(instance_value "$WORKER_INSTANCE_ID" PrivateIpAddress)"
APP_IMAGE="$(kubectl --kubeconfig "$KUBECONFIG_PATH" get deployment mopa-laser-raster-worker \
  -o jsonpath='{.spec.template.spec.containers[?(@.name=="raster-worker")].image}')"
PAUSE_IMAGE="$(ssh -i "$SSH_KEY" "${SSH_USER}@${SERVER_PUBLIC_IP}" \
  "sudo k3s ctr -n k8s.io images list -q | grep '^docker.io/rancher/mirrored-pause:' | head -n 1")"

if [ -z "$APP_IMAGE" ] || [ -z "$PAUSE_IMAGE" ]; then
  echo "Could not determine the application or k3s pause image." >&2
  exit 1
fi

TRANSFER_DIR="$(mktemp -d)"
ARCHIVE="$TRANSFER_DIR/k3s-worker-images.tar"
REMOTE_ARCHIVE="/tmp/k3s-worker-images.tar"
cleanup() {
  rm -f "$ARCHIVE"
  rmdir "$TRANSFER_DIR" 2>/dev/null || true
}
trap cleanup EXIT

SERVER_OPTIONS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY")
WORKER_OPTIONS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY"
  -o "ProxyCommand=ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i $SSH_KEY -W %h:%p ${SSH_USER}@${SERVER_PUBLIC_IP}")

echo "Exporting cached images from the k3s server:"
printf '  %s\n' "$PAUSE_IMAGE" docker.io/library/alpine:latest "$APP_IMAGE"
ssh "${SERVER_OPTIONS[@]}" "${SSH_USER}@${SERVER_PUBLIC_IP}" \
  "sudo k3s ctr -n k8s.io content fetch --platform linux/amd64 '$PAUSE_IMAGE' >/dev/null && sudo k3s ctr -n k8s.io images export --platform linux/amd64 $REMOTE_ARCHIVE '$PAUSE_IMAGE' docker.io/library/alpine:latest '$APP_IMAGE' && sudo chown ${SSH_USER}:${SSH_USER} $REMOTE_ARCHIVE"
scp "${SERVER_OPTIONS[@]}" "${SSH_USER}@${SERVER_PUBLIC_IP}:${REMOTE_ARCHIVE}" "$ARCHIVE"
ssh "${SERVER_OPTIONS[@]}" "${SSH_USER}@${SERVER_PUBLIC_IP}" "rm -f $REMOTE_ARCHIVE"

echo "Copying cached images to $WORKER_INSTANCE_ID"
scp "${WORKER_OPTIONS[@]}" "$ARCHIVE" "${SSH_USER}@${WORKER_PRIVATE_IP}:${REMOTE_ARCHIVE}"
ssh "${WORKER_OPTIONS[@]}" "${SSH_USER}@${WORKER_PRIVATE_IP}" \
  "sudo k3s ctr -n k8s.io images import $REMOTE_ARCHIVE && rm -f $REMOTE_ARCHIVE"

echo "Images imported. Deleting the pending pod so Kubernetes retries immediately."
kubectl --kubeconfig "$KUBECONFIG_PATH" patch deployment mopa-laser-raster-worker \
  --type strategic \
  -p '{"spec":{"template":{"spec":{"initContainers":[{"name":"wait-for-redis","imagePullPolicy":"IfNotPresent"}]}}}}'
kubectl --kubeconfig "$KUBECONFIG_PATH" delete pod \
  -l app=mopa-laser-raster-worker --field-selector spec.nodeName="$WORKER_INSTANCE_ID" \
  --ignore-not-found
kubectl --kubeconfig "$KUBECONFIG_PATH" rollout status deployment/mopa-laser-raster-worker --timeout=120m
kubectl --kubeconfig "$KUBECONFIG_PATH" get pods -l app=mopa-laser-raster-worker -o wide

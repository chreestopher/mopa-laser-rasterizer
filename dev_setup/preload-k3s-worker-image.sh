#!/usr/bin/env bash
# Copy a locally built image into a private k3s worker through the server jump
# host. This lets a node without NAT run the exact immutable ECR-tagged image.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
SERVER_INSTANCE_ID="${K3S_INSTANCE_ID:-}"
WORKER_INSTANCE_ID="${1:-}"
IMAGE_URI="${2:-}"
SSH_USER="${K3S_SSH_USER:-ubuntu}"
SSH_KEY="${K3S_SSH_KEY:-}"

if [ -z "$WORKER_INSTANCE_ID" ] || [ -z "$IMAGE_URI" ] || [ -z "$SERVER_INSTANCE_ID" ] || [ -z "$SSH_KEY" ]; then
  echo "Usage: $0 <worker-instance-id> <image-uri>" >&2
  exit 2
fi
docker image inspect "$IMAGE_URI" >/dev/null

instance_value() {
  aws ec2 describe-instances --region "$REGION" --instance-ids "$1" \
    --query "Reservations[0].Instances[0].$2" --output text
}

SERVER_PUBLIC_IP="$(instance_value "$SERVER_INSTANCE_ID" PublicIpAddress)"
WORKER_PRIVATE_IP="$(instance_value "$WORKER_INSTANCE_ID" PrivateIpAddress)"
TRANSFER_DIR="$(mktemp -d)"
ARCHIVE="$TRANSFER_DIR/rasterizer-image.tar"
REMOTE_ARCHIVE="/tmp/rasterizer-image.tar"

cleanup() {
  rm -f "$ARCHIVE"
  rmdir "$TRANSFER_DIR" 2>/dev/null || true
}
trap cleanup EXIT

WORKER_OPTIONS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY"
  -o "ProxyCommand=ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i $SSH_KEY -W %h:%p ${SSH_USER}@${SERVER_PUBLIC_IP}")

echo "Saving $IMAGE_URI for private worker $WORKER_INSTANCE_ID"
docker save --output "$ARCHIVE" "$IMAGE_URI"
echo "Transferring image archive to $WORKER_PRIVATE_IP through the k3s server"
scp "${WORKER_OPTIONS[@]}" "$ARCHIVE" "${SSH_USER}@${WORKER_PRIVATE_IP}:${REMOTE_ARCHIVE}"
echo "Importing image into the worker's k3s containerd"
ssh "${WORKER_OPTIONS[@]}" "${SSH_USER}@${WORKER_PRIVATE_IP}" \
  "sudo k3s ctr -n k8s.io images import '$REMOTE_ARCHIVE' && rm -f '$REMOTE_ARCHIVE'"
echo "Private worker image preload complete: $IMAGE_URI"

#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
INSTANCE_ID="${K3S_INSTANCE_ID:-i-04cf2c7d175cba101}"
SSH_USER="${K3S_SSH_USER:-ubuntu}"
SSH_KEY="${K3S_SSH_KEY:-$HOME/.ssh/actual-key.pem}"
LOCAL_PORT="${K3S_LOCAL_PORT:-16443}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"

if [ ! -f "$SSH_KEY" ]; then
  echo "SSH key not found: $SSH_KEY" >&2
  exit 1
fi
if [ ! -f "$KUBECONFIG_PATH" ]; then
  echo "Production kubeconfig not found: $KUBECONFIG_PATH" >&2
  exit 1
fi

PUBLIC_IP="$(aws ec2 describe-instances \
  --region "$REGION" \
  --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text)"

if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "The EC2 instance does not have a public IP address." >&2
  exit 1
fi

if ! kubectl --kubeconfig "$KUBECONFIG_PATH" cluster-info >/dev/null 2>&1; then
  ssh -f -N \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -i "$SSH_KEY" \
    -L "${LOCAL_PORT}:127.0.0.1:6443" \
    "${SSH_USER}@${PUBLIC_IP}"
fi

export KUBECONFIG="$KUBECONFIG_PATH"
kubectl cluster-info
kubectl get nodes -o wide
echo
echo "Tunnel ready. In this shell run:"
echo "export KUBECONFIG=$KUBECONFIG_PATH"

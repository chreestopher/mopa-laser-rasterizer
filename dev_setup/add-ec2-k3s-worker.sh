#!/usr/bin/env bash
# Join an EC2 instance to the existing k3s cluster and prepare it to run a
# dedicated Rasterizer worker pod. Run this from WSL with AWS CLI access.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
source "$SCRIPT_DIR/load-aws-env.sh"
REGION="${AWS_REGION:-us-east-2}"
SERVER_INSTANCE_ID="${K3S_INSTANCE_ID:-}"
WORKER_INSTANCE_ID="${1:-${K3S_WORKER_INSTANCE_ID:-}}"
SSH_USER="${K3S_SSH_USER:-ubuntu}"
SSH_KEY="${K3S_SSH_KEY:-}"
INSTANCE_PROFILE_NAME="${EC2_PROFILE_NAME:-mopa-laser-rasterizer-ec2-profile}"
REMOTE_BOOTSTRAP="$SCRIPT_DIR/join-k3s-worker-remote.sh"
AWS_ENDPOINT_SETUP="$SCRIPT_DIR/ensure-ec2-aws-gateway-endpoints.sh"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"

if [ -z "$WORKER_INSTANCE_ID" ] || [ -z "$SERVER_INSTANCE_ID" ] || [ -z "$SSH_KEY" ]; then
  echo "Usage: $0 <worker-instance-id>" >&2
  exit 2
fi
for command_name in aws curl ssh scp kubectl; do
  command -v "$command_name" >/dev/null || { echo "Missing command: $command_name" >&2; exit 2; }
done
if [ ! -f "$SSH_KEY" ]; then
  echo "SSH key not found: $SSH_KEY" >&2
  exit 2
fi
chmod 600 "$SSH_KEY" 2>/dev/null || true

instance_value() {
  aws ec2 describe-instances --region "$REGION" --instance-ids "$1" \
    --query "Reservations[0].Instances[0].$2" --output text
}

SERVER_PRIVATE_IP="$(instance_value "$SERVER_INSTANCE_ID" PrivateIpAddress)"
SERVER_PUBLIC_IP="$(instance_value "$SERVER_INSTANCE_ID" PublicIpAddress)"
SERVER_VPC="$(instance_value "$SERVER_INSTANCE_ID" VpcId)"
WORKER_PUBLIC_IP="$(instance_value "$WORKER_INSTANCE_ID" PublicIpAddress)"
WORKER_PRIVATE_IP="$(instance_value "$WORKER_INSTANCE_ID" PrivateIpAddress)"
WORKER_VPC="$(instance_value "$WORKER_INSTANCE_ID" VpcId)"
WORKER_STATE="$(instance_value "$WORKER_INSTANCE_ID" State.Name)"
WORKER_PROFILE_ARN="$(instance_value "$WORKER_INSTANCE_ID" IamInstanceProfile.Arn)"
NODE_NAME="${K3S_WORKER_NODE_NAME:-$WORKER_INSTANCE_ID}"
SERVER_SECURITY_GROUPS="$(instance_value "$SERVER_INSTANCE_ID" 'SecurityGroups[].GroupId')"
WORKER_SECURITY_GROUPS="$(instance_value "$WORKER_INSTANCE_ID" 'SecurityGroups[].GroupId')"

if [ "$WORKER_STATE" != "running" ]; then
  echo "Worker instance $WORKER_INSTANCE_ID is '$WORKER_STATE', not running." >&2
  exit 1
fi
if [ "$SERVER_VPC" != "$WORKER_VPC" ]; then
  echo "The server and worker are in different VPCs ($SERVER_VPC and $WORKER_VPC)." >&2
  exit 1
fi

# Raster workers use S3 for artifacts and DynamoDB for durable job/account
# state. Private nodes need both regional Gateway endpoints.
bash "$AWS_ENDPOINT_SETUP" "$WORKER_INSTANCE_ID"
EXPECTED_PROFILE_SUFFIX="instance-profile/${INSTANCE_PROFILE_NAME}"
if [ "$WORKER_PROFILE_ARN" = "None" ] || [ -z "$WORKER_PROFILE_ARN" ]; then
  echo "Associating IAM instance profile $INSTANCE_PROFILE_NAME"
  aws ec2 associate-iam-instance-profile --region "$REGION" \
    --instance-id "$WORKER_INSTANCE_ID" \
    --iam-instance-profile "Name=$INSTANCE_PROFILE_NAME" >/dev/null
elif [[ "$WORKER_PROFILE_ARN" != *"$EXPECTED_PROFILE_SUFFIX" ]]; then
  echo "Worker already uses a different IAM instance profile: $WORKER_PROFILE_ARN" >&2
  echo "Expected: $INSTANCE_PROFILE_NAME" >&2
  exit 1
fi

SHARED_SECURITY_GROUP=""
for server_group in $SERVER_SECURITY_GROUPS; do
  for worker_group in $WORKER_SECURITY_GROUPS; do
    if [ "$server_group" = "$worker_group" ]; then
      SHARED_SECURITY_GROUP="$server_group"
      break 2
    fi
  done
done
if [ -z "$SHARED_SECURITY_GROUP" ]; then
  echo "The server and worker do not share a security group." >&2
  echo "Allow TCP 6443 and 10250 plus UDP 8472 between their private addresses, then retry." >&2
  exit 1
fi

ensure_self_ingress() {
  local protocol="$1" from_port="$2" to_port="$3" description="$4" output
  if output="$(aws ec2 authorize-security-group-ingress --region "$REGION" \
      --group-id "$SHARED_SECURITY_GROUP" --protocol "$protocol" \
      --port "${from_port}-${to_port}" --source-group "$SHARED_SECURITY_GROUP" \
      --tag-specifications "ResourceType=security-group-rule,Tags=[{Key=Name,Value=${description}}]" 2>&1)"; then
    echo "Added $protocol $from_port-$to_port within $SHARED_SECURITY_GROUP"
  elif [[ "$output" != *"InvalidPermission.Duplicate"* ]]; then
    printf '%s\n' "$output" >&2
    exit 1
  fi
}

ensure_self_ingress tcp 6443 6443 k3s-api-private
ensure_self_ingress tcp 10250 10250 k3s-kubelet-private
ensure_self_ingress udp 8472 8472 k3s-flannel-private

SERVER_SSH_OPTIONS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY")
WORKER_SSH_OPTIONS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i "$SSH_KEY")
if [ "$WORKER_PUBLIC_IP" = "None" ] || [ -z "$WORKER_PUBLIC_IP" ]; then
  WORKER_SSH_HOST="$WORKER_PRIVATE_IP"
  # An explicit ProxyCommand ensures the identity file is also used for the
  # jump-host connection. Some OpenSSH builds do not propagate -i through -J.
  WORKER_SSH_OPTIONS+=(-o "ProxyCommand=ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -i $SSH_KEY -W %h:%p ${SSH_USER}@${SERVER_PUBLIC_IP}")
  echo "The worker has no public IP; SSH will use $SERVER_INSTANCE_ID as a jump host."
else
  WORKER_SSH_HOST="$WORKER_PUBLIC_IP"
fi

echo "Verifying HTTPS connectivity from the worker to regional S3 and DynamoDB"
ssh "${WORKER_SSH_OPTIONS[@]}" "${SSH_USER}@${WORKER_SSH_HOST}" \
  "python3 -c \"import socket; [socket.create_connection((host, 443), 10).close() for host in ('s3.${REGION}.amazonaws.com', 'dynamodb.${REGION}.amazonaws.com')]\""

echo "Reading the k3s join token from $SERVER_INSTANCE_ID"
K3S_TOKEN="$(ssh "${SERVER_SSH_OPTIONS[@]}" "${SSH_USER}@${SERVER_PUBLIC_IP}" 'sudo cat /var/lib/rancher/k3s/server/node-token')"

TRANSFER_DIR="$(mktemp -d)"
cleanup_transfer_dir() {
  rm -f "$TRANSFER_DIR/install-k3s.sh" "$TRANSFER_DIR/k3s"
  rmdir "$TRANSFER_DIR" 2>/dev/null || true
}
trap cleanup_transfer_dir EXIT
echo "Preparing an offline k3s installation matching the current server"
curl -sfL --retry 3 --connect-timeout 15 https://get.k3s.io -o "$TRANSFER_DIR/install-k3s.sh"
scp "${SERVER_SSH_OPTIONS[@]}" \
  "${SSH_USER}@${SERVER_PUBLIC_IP}:/usr/local/bin/k3s" "$TRANSFER_DIR/k3s"

echo "Installing the k3s agent on $WORKER_INSTANCE_ID ($WORKER_PRIVATE_IP)"
scp "${WORKER_SSH_OPTIONS[@]}" \
  "$REMOTE_BOOTSTRAP" "$TRANSFER_DIR/install-k3s.sh" "$TRANSFER_DIR/k3s" \
  "${SSH_USER}@${WORKER_SSH_HOST}:/tmp/"
echo "Bootstrap copied; starting remote installation"
printf '%s\n' "$K3S_TOKEN" | ssh "${WORKER_SSH_OPTIONS[@]}" "${SSH_USER}@${WORKER_SSH_HOST}" \
  "sudo bash /tmp/join-k3s-worker-remote.sh https://${SERVER_PRIVATE_IP}:6443 ${NODE_NAME}"
unset K3S_TOKEN
ssh "${WORKER_SSH_OPTIONS[@]}" "${SSH_USER}@${WORKER_SSH_HOST}" 'rm -f /tmp/join-k3s-worker-remote.sh'

echo "Waiting for Kubernetes node $NODE_NAME"
for _ in $(seq 1 60); do
  if kubectl --kubeconfig "$KUBECONFIG_PATH" get node "$NODE_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
kubectl --kubeconfig "$KUBECONFIG_PATH" wait --for=condition=Ready "node/$NODE_NAME" --timeout=10m
kubectl --kubeconfig "$KUBECONFIG_PATH" label node "$NODE_NAME" \
  rasterizer.mopa/workload=worker \
  rasterizer.mopa/ec2-instance-id="$WORKER_INSTANCE_ID" --overwrite

SERVER_NODE_NAME="$(kubectl --kubeconfig "$KUBECONFIG_PATH" get nodes \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}' | \
  awk -v server_ip="$SERVER_PRIVATE_IP" '$2 == server_ip {print $1; exit}')"
if [ -z "$SERVER_NODE_NAME" ]; then
  echo "Could not identify the existing server node by private IP $SERVER_PRIVATE_IP." >&2
  exit 1
fi
kubectl --kubeconfig "$KUBECONFIG_PATH" label node "$SERVER_NODE_NAME" \
  rasterizer.mopa/workload=worker \
  rasterizer.mopa/ec2-instance-id="$SERVER_INSTANCE_ID" --overwrite

echo
echo "Both cluster nodes are labeled. Spread two worker replicas with:"
echo "  dev_setup/deploy-worker-to-node.sh $NODE_NAME"
echo
echo "Required private-node traffic: TCP 6443 and 10250, and UDP 8472."
echo "Private S3 and DynamoDB HTTPS connectivity was verified from the worker."

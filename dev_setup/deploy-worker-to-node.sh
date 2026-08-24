#!/usr/bin/env bash
# Spread two Rasterizer worker replicas across the prepared cluster nodes.
set -euo pipefail

NODE_NAME="${1:-}"
NAMESPACE="${K8S_NAMESPACE:-default}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"

if [ -z "$NODE_NAME" ]; then
  echo "Usage: $0 <kubernetes-node-name>" >&2
  exit 2
fi

kubectl --kubeconfig "$KUBECONFIG_PATH" get node "$NODE_NAME" >/dev/null
kubectl --kubeconfig "$KUBECONFIG_PATH" label node "$NODE_NAME" \
  rasterizer.mopa/workload=worker --overwrite

kubectl --kubeconfig "$KUBECONFIG_PATH" patch deployment mopa-laser-raster-worker \
  --namespace "$NAMESPACE" --type merge \
  -p '{"spec":{"replicas":2,"template":{"spec":{"nodeSelector":{"rasterizer.mopa/workload":"worker"},"affinity":{"podAntiAffinity":{"requiredDuringSchedulingIgnoredDuringExecution":[{"labelSelector":{"matchLabels":{"app":"mopa-laser-raster-worker"}},"topologyKey":"kubernetes.io/hostname"}]}}}}}}'

kubectl --kubeconfig "$KUBECONFIG_PATH" rollout status deployment/mopa-laser-raster-worker \
  --namespace "$NAMESPACE" --timeout=120m
kubectl --kubeconfig "$KUBECONFIG_PATH" get pods --namespace "$NAMESPACE" \
  -l app=mopa-laser-raster-worker -o wide

#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${K3S_NAMESPACE:-default}"
DEPLOYMENT_NAME="${K3S_WEB_DEPLOYMENT:-mopa-laser-rasterizer}"
KUBECONFIG_PATH="${KUBECONFIG:-$HOME/.kube/mopa-rasterizer-production.yaml}"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
HPA_MANIFEST="$SCRIPT_DIR/../k8s/hpa.yaml"

if [ ! -f "$KUBECONFIG_PATH" ]; then
  echo "Production kubeconfig not found: $KUBECONFIG_PATH" >&2
  exit 1
fi

if [ ! -f "$HPA_MANIFEST" ]; then
  echo "HPA manifest not found: $HPA_MANIFEST" >&2
  exit 1
fi

if ! kubectl --kubeconfig "$KUBECONFIG_PATH" cluster-info >/dev/null 2>&1; then
  echo "The k3s API is not reachable through the local tunnel." >&2
  echo "Start it first with: bash ./dev_setup/start-k3s-tunnel.sh" >&2
  exit 1
fi

echo "Applying the web autoscaler configuration from $HPA_MANIFEST"
kubectl --kubeconfig "$KUBECONFIG_PATH" apply -f "$HPA_MANIFEST"

echo "Waiting for the web deployment to reconcile with the new four-pod maximum"
kubectl --kubeconfig "$KUBECONFIG_PATH" rollout status \
  "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE" --timeout=180s

echo
echo "Current autoscaler state:"
kubectl --kubeconfig "$KUBECONFIG_PATH" get hpa "$DEPLOYMENT_NAME" -n "$NAMESPACE"

echo
echo "Current web pods:"
kubectl --kubeconfig "$KUBECONFIG_PATH" get pods \
  -l "app=$DEPLOYMENT_NAME" -n "$NAMESPACE" -o wide

echo
echo "HPA applied. No application rollout restart was required."

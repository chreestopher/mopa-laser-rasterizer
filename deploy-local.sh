#!/usr/bin/env sh
# Deploy from WSL. This generates a hostPath manifest using this checkout's
# physical WSL path, so source changes only need a rollout restart.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
TEMPLATE="$SCRIPT_DIR/k8s/deployment.local.yaml.template"
MANIFEST="$SCRIPT_DIR/k8s/deployment.local.yaml"
PROJECT_ROOT=$SCRIPT_DIR

if ! command -v kubectl >/dev/null 2>&1; then
    echo "kubectl is required." >&2
    exit 1
fi

PROJECT_ROOT_ESCAPED=$(printf '%s' "$PROJECT_ROOT" | sed 's/[&|]/\\&/g')
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT_ESCAPED|g" "$TEMPLATE" > "$MANIFEST"

kubectl apply -f "$MANIFEST"
kubectl rollout restart deployment/mopa-laser-rasterizer -n default
kubectl rollout status deployment/mopa-laser-rasterizer -n default

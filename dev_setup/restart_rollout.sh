#!/usr/bin/env sh
# Restart the application deployment and wait until the new pods are ready.
set -eu

DEPLOYMENT_NAME=${1:-mopa-laser-rasterizer}
NAMESPACE=${2:-default}

if [ "$(id -u)" -eq 0 ]; then
    kubectl rollout restart "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE"
    kubectl rollout status "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE"
else
    sudo kubectl rollout restart "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE"
    sudo kubectl rollout status "deployment/$DEPLOYMENT_NAME" -n "$NAMESPACE"
fi

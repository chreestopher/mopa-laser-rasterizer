#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="mopa-laser-rasterizer"
IMAGE_TAG="com"
DOCKERFILE="Dockerfile"
CONTEXT="."

if [[ $# -ge 1 ]]; then
  IMAGE_NAME="$1"
fi
if [[ $# -ge 2 ]]; then
  IMAGE_TAG="$2"
fi
if [[ $# -ge 3 ]]; then
  DOCKERFILE="$3"
fi
if [[ $# -ge 4 ]]; then
  CONTEXT="$4"
fi

FULL_TAG="$IMAGE_NAME:$IMAGE_TAG"

echo "Building Docker image $FULL_TAG ..."
docker build -t "$FULL_TAG" -f "$DOCKERFILE" "$CONTEXT"

echo "Saving image to temporary tar file ..."
TEMP_TAR="/tmp/${IMAGE_NAME//\//_}-${IMAGE_TAG}-$(date +%Y%m%d%H%M%S).tar"
docker save "$FULL_TAG" -o "$TEMP_TAR"

IMPORT_SUCCESS=0
if command -v k3s >/dev/null 2>&1; then
  echo "Importing image into k3s containerd ..."
  k3s ctr -n k8s.io images import "$TEMP_TAR"
  IMPORT_SUCCESS=$?
elif command -v ctr >/dev/null 2>&1; then
  echo "Importing image into containerd ..."
  ctr -n k8s.io images import "$TEMP_TAR"
  IMPORT_SUCCESS=$?
elif command -v crictl >/dev/null 2>&1; then
  echo "Importing image using crictl ..."
  crictl load "$TEMP_TAR"
  IMPORT_SUCCESS=$?
else
  echo "No supported loader found. Install k3s, ctr, or crictl and retry." >&2
  IMPORT_SUCCESS=1
fi

rm -f "$TEMP_TAR"

if [[ "$IMPORT_SUCCESS" -ne 0 ]]; then
  echo "Image load failed." >&2
  exit 1
fi
echo "Success. Image $FULL_TAG is loaded into the runtime."
echo "Use this image tag in your Kubernetes resources, for example:"
echo "running kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=$FULL_TAG"
sudo kubectl set image deployment/mopa-laser-rasterizer mopa-laser-rasterizer=$FULL_TAG
echo "restarting the deployment with: kubectl rollout restart deployment/mopa-laser-rasterizer"
sudo kubectl rollout restart deployment/mopa-laser-rasterizer
sudo kubectl logs -l app=mopa-laser-rasterizer -f --max-log-requests 20
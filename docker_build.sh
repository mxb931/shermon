#!/usr/bin/env sh
set -eu

IMAGE_NAME="${IMAGE_NAME:-xstore-monitor}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REGISTRY_IMAGE="${REGISTRY_IMAGE:-}"

# Build linux/amd64 by default to match common Rancher node architectures.
docker build --platform "${DOCKER_PLATFORM:-linux/amd64}" -t "${IMAGE_NAME}:${IMAGE_TAG}" .

if [ -n "$REGISTRY_IMAGE" ]; then
  docker tag "${IMAGE_NAME}:${IMAGE_TAG}" "${REGISTRY_IMAGE}:${IMAGE_TAG}"
  docker push "${REGISTRY_IMAGE}:${IMAGE_TAG}"
fi

echo "Built image ${IMAGE_NAME}:${IMAGE_TAG}"
if [ -n "$REGISTRY_IMAGE" ]; then
  echo "Pushed image ${REGISTRY_IMAGE}:${IMAGE_TAG}"
fi

#!/bin/bash
set -e

REPO="${REPO:-quay.io/rh-ee-dayeo/marketing-assistant}"
PLATFORM="${PLATFORM:-linux/amd64}"
TAG_SUFFIX="${TAG_SUFFIX:-}"

echo "=========================================="
echo "Grand Lisboa Palace - Build & Push"
echo "=========================================="
echo "Repository: $REPO"
echo "Platform: $PLATFORM"
[ -n "$TAG_SUFFIX" ] && echo "Tag suffix: $TAG_SUFFIX"
echo ""

cd "$(dirname "$0")"

SERVICES=(
    "mongodb-mcp"
    "imagegen-mcp"
    "event-hub"
    "creative-producer"
    "customer-analyst"
    "delivery-manager"
    "campaign-director"
    "campaign-api"
    "campaign-landing"
)

for SERVICE in "${SERVICES[@]}"; do
    echo ""
    echo "----------------------------------------"
    echo "Building: $SERVICE"
    echo "----------------------------------------"
    
    FULL_IMAGE="${REPO}:${SERVICE}${TAG_SUFFIX}"
    
    podman build \
        --platform "$PLATFORM" \
        -f "services/${SERVICE}/Dockerfile" \
        -t "$FULL_IMAGE" \
        .
    
    echo "Pushing: $FULL_IMAGE"
    podman push "$FULL_IMAGE"
    
    echo "✓ $SERVICE complete"
done

echo ""
echo "----------------------------------------"
echo "Building: frontend"
echo "----------------------------------------"

npm run build --prefix frontend
FRONTEND_IMAGE="${REPO}:frontend${TAG_SUFFIX}"

podman build \
    --platform "$PLATFORM" \
    -f "frontend/Dockerfile.prebuilt" \
    -t "$FRONTEND_IMAGE" \
    frontend/

echo "Pushing: $FRONTEND_IMAGE"
podman push "$FRONTEND_IMAGE"

echo "✓ frontend complete"

echo ""
echo "=========================================="
echo "All images built and pushed!"
echo "=========================================="
echo ""
echo "Images:"
for SERVICE in "${SERVICES[@]}"; do
    echo "  - ${REPO}:${SERVICE}${TAG_SUFFIX}"
done
echo "  - ${REPO}:frontend${TAG_SUFFIX}"
echo ""
echo "Next: oc apply -k k8s/overlays/dev"

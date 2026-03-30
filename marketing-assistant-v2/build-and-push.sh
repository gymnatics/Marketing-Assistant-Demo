#!/bin/bash
set -e

# Configuration
REGISTRY="${REGISTRY:-quay.io/rh-ee-dayeo}"
TAG="${TAG:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

echo "=========================================="
echo "Marketing Assistant v2 - Build & Push"
echo "=========================================="
echo "Registry: $REGISTRY"
echo "Tag: $TAG"
echo "Platform: $PLATFORM"
echo ""

# Change to the marketing-assistant-v2 directory
cd "$(dirname "$0")"

# Services to build (order matters for dependencies)
SERVICES=(
    "mongodb-mcp"
    "event-hub"
    "creative-producer"
    "customer-analyst"
    "delivery-manager"
    "campaign-director"
    "campaign-api"
)

# Build and push each service
for SERVICE in "${SERVICES[@]}"; do
    echo ""
    echo "----------------------------------------"
    echo "Building: $SERVICE"
    echo "----------------------------------------"
    
    IMAGE_NAME="marketing-assistant-v2-${SERVICE}"
    FULL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${TAG}"
    
    # Build from root context using service-specific Dockerfile
    podman build \
        --platform "$PLATFORM" \
        -f "services/${SERVICE}/Dockerfile" \
        -t "$FULL_IMAGE" \
        .
    
    echo "Pushing: $FULL_IMAGE"
    podman push "$FULL_IMAGE"
    
    echo "✓ $SERVICE complete"
done

# Build frontend separately (different build process)
echo ""
echo "----------------------------------------"
echo "Building: frontend"
echo "----------------------------------------"

FRONTEND_IMAGE="${REGISTRY}/marketing-assistant-v2-frontend:${TAG}"

podman build \
    --platform "$PLATFORM" \
    -f "frontend/Dockerfile" \
    -t "$FRONTEND_IMAGE" \
    frontend/

echo "Pushing: $FRONTEND_IMAGE"
podman push "$FRONTEND_IMAGE"

echo "✓ frontend complete"

echo ""
echo "=========================================="
echo "All images built and pushed successfully!"
echo "=========================================="
echo ""
echo "Images pushed:"
for SERVICE in "${SERVICES[@]}"; do
    echo "  - ${REGISTRY}/marketing-assistant-v2-${SERVICE}:${TAG}"
done
echo "  - ${REGISTRY}/marketing-assistant-v2-frontend:${TAG}"
echo ""
echo "Next steps:"
echo "  1. Update k8s/secret.yaml with your model tokens"
echo "  2. Deploy with: ./deploy.sh"

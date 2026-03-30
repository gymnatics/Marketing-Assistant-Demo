#!/bin/bash
set -e

# Configuration - single repo, service name as tag
REPO="${REPO:-quay.io/rh-ee-dayeo/marketing-assistant}"
PLATFORM="${PLATFORM:-linux/amd64}"

echo "=========================================="
echo "Marketing Assistant v2 - Build & Push"
echo "=========================================="
echo "Repository: $REPO"
echo "Platform: $PLATFORM"
echo ""

# Change to the marketing-assistant-v2 directory
cd "$(dirname "$0")"

# Services to build
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
    
    FULL_IMAGE="${REPO}:${SERVICE}"
    
    podman build \
        --platform "$PLATFORM" \
        -f "services/${SERVICE}/Dockerfile" \
        -t "$FULL_IMAGE" \
        .
    
    echo "Pushing: $FULL_IMAGE"
    podman push "$FULL_IMAGE"
    
    echo "✓ $SERVICE complete"
done

# Build frontend separately
echo ""
echo "----------------------------------------"
echo "Building: frontend"
echo "----------------------------------------"

FRONTEND_IMAGE="${REPO}:frontend"

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
    echo "  - ${REPO}:${SERVICE}"
done
echo "  - ${REPO}:frontend"
echo ""
echo "Next steps:"
echo "  1. Update k8s/secret.yaml with your model tokens"
echo "  2. Deploy with: ./deploy.sh"

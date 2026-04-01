#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-marketing-assistant-v2}"
OVERLAY="${OVERLAY:-k8s/overlays/dev}"

echo "=========================================="
echo "Grand Lisboa Palace - Deploy to OpenShift"
echo "=========================================="
echo "Namespace: $NAMESPACE"
echo "Overlay: $OVERLAY"
echo ""

cd "$(dirname "$0")"

if ! oc whoami &> /dev/null; then
    echo "Error: Not logged in to OpenShift. Please run 'oc login' first."
    exit 1
fi

echo "Logged in as: $(oc whoami)"
echo ""

# Deploy everything via Kustomize
echo "Applying Kustomize overlay..."
oc apply -k "$OVERLAY"

echo ""
echo "Waiting for deployments..."
DEPLOYMENTS=(
    "mongodb"
    "mongodb-mcp"
    "imagegen-mcp"
    "event-hub"
    "creative-producer"
    "customer-analyst"
    "delivery-manager"
    "campaign-director"
    "campaign-api"
    "frontend"
)

for DEPLOY in "${DEPLOYMENTS[@]}"; do
    echo "  Waiting for $DEPLOY..."
    oc rollout status deployment/$DEPLOY -n $NAMESPACE --timeout=120s || true
done

# Seed MongoDB
echo ""
echo "Seeding MongoDB..."
sleep 5
oc exec deployment/mongodb-mcp -n $NAMESPACE -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py || echo "Seed failed (MongoDB may not be ready yet, try: oc exec deployment/mongodb-mcp -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py)"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Routes:"
oc get routes -n $NAMESPACE -o custom-columns=NAME:.metadata.name,HOST:.spec.host
echo ""
echo "Frontend:"
oc get route marketing-assistant-v2 -n $NAMESPACE -o jsonpath='https://{.spec.host}{"\n"}' 2>/dev/null || echo "Route not found"
echo ""
echo "Remember:"
echo "  - Apply your secret separately if not done: oc apply -f k8s/overlays/dev/secret.yaml -n $NAMESPACE"
echo "  - Import vLLM-Omni runtime: oc apply -f k8s/imagegen/serving-runtime.yaml"

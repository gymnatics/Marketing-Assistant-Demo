#!/bin/bash
set -e

# Configuration
NAMESPACE="${NAMESPACE:-marketing-assistant-v2}"

echo "=========================================="
echo "Marketing Assistant v2 - Deploy to OpenShift"
echo "=========================================="
echo "Namespace: $NAMESPACE"
echo ""

# Change to the marketing-assistant-v2 directory
cd "$(dirname "$0")"

# Check if logged in to OpenShift
if ! oc whoami &> /dev/null; then
    echo "Error: Not logged in to OpenShift. Please run 'oc login' first."
    exit 1
fi

echo "Logged in as: $(oc whoami)"
echo ""

# Create namespace if it doesn't exist
echo "Creating namespace..."
oc apply -f k8s/namespace.yaml

# Apply ConfigMap
echo "Applying ConfigMap..."
oc apply -f k8s/configmap.yaml

# Check if secret exists, warn if not configured
echo "Applying Secret..."
if grep -q 'CODE_MODEL_TOKEN: ""' k8s/secret.yaml; then
    echo "WARNING: k8s/secret.yaml has empty tokens. Please edit before deploying."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi
oc apply -f k8s/secret.yaml

# Deploy MCP server
echo ""
echo "Deploying MCP server..."
oc apply -f k8s/mcp/

# Deploy agents
echo ""
echo "Deploying agents..."
oc apply -f k8s/agents/

# Deploy API layer
echo ""
echo "Deploying API layer..."
oc apply -f k8s/api/

# Deploy frontend
echo ""
echo "Deploying frontend..."
oc apply -f k8s/frontend/

# Wait for deployments
echo ""
echo "Waiting for deployments to be ready..."
oc rollout status deployment/mongodb-mcp -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/event-hub -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/creative-producer -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/customer-analyst -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/delivery-manager -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/campaign-director -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/campaign-api -n $NAMESPACE --timeout=120s || true
oc rollout status deployment/frontend -n $NAMESPACE --timeout=120s || true

# Get routes
echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Routes:"
oc get routes -n $NAMESPACE -o custom-columns=NAME:.metadata.name,HOST:.spec.host
echo ""
echo "Frontend URL:"
oc get route marketing-assistant-v2 -n $NAMESPACE -o jsonpath='https://{.spec.host}{"\n"}' 2>/dev/null || echo "Route not found"

#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-0-marketing-assistant-demo}"

echo "=========================================="
echo "Simon Casino Resort - Update App"
echo "=========================================="
echo ""

if ! oc whoami &> /dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

echo "Namespace: $NAMESPACE"
echo ""

echo "--- Restarting all app deployments ---"
DEPLOYMENTS=(
    mongodb
    mongodb-mcp
    imagegen-mcp
    event-hub
    policy-guardian
    creative-producer
    customer-analyst
    delivery-manager
    campaign-director
    campaign-api
    frontend
)

for DEPLOY in "${DEPLOYMENTS[@]}"; do
    if oc get deployment "$DEPLOY" -n "$NAMESPACE" &>/dev/null; then
        oc rollout restart deployment/"$DEPLOY" -n "$NAMESPACE" 2>/dev/null
        echo "  Restarted $DEPLOY"
    fi
done

echo ""
echo "--- Waiting for rollouts ---"
for DEPLOY in "${DEPLOYMENTS[@]}"; do
    if oc get deployment "$DEPLOY" -n "$NAMESPACE" &>/dev/null; then
        echo "  Waiting for $DEPLOY..."
        oc rollout status deployment/"$DEPLOY" -n "$NAMESPACE" --timeout=120s 2>/dev/null || echo "    $DEPLOY not ready"
    fi
done

echo ""
echo "--- Re-seeding MongoDB ---"
sleep 5
oc exec deployment/mongodb-mcp -n "$NAMESPACE" -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py 2>/dev/null || echo "  Seed failed (try manually later)"

echo ""
echo "=========================================="
echo "Update complete!"
echo "=========================================="
echo "All pods restarted with latest images and config."
echo ""

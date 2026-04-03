#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-0-marketing-assistant-demo}"
DEV_NS="${DEV_NS:-0-marketing-assistant-demo-dev}"
PROD_NS="${PROD_NS:-0-marketing-assistant-demo-prod}"
KEEP="${KEEP:-campaign-basic-preview}"

echo "=========================================="
echo "Simon Casino Resort - Reset Demo"
echo "=========================================="
echo ""
echo "Namespace:  $NAMESPACE"
echo "Dev NS:     $DEV_NS"
echo "Prod NS:    $PROD_NS"
echo "Keeping:    $KEEP (nginx pre-generated)"
echo ""

if ! oc whoami &> /dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

echo "--- Cleaning dev namespace ($DEV_NS) ---"
for dep in $(oc get deployments -n "$DEV_NS" -o name 2>/dev/null); do
    NAME=$(echo "$dep" | sed 's|deployment.apps/||')
    if [ "$NAME" = "$KEEP" ]; then
        echo "  Keeping $NAME"
        continue
    fi
    echo "  Deleting $NAME..."
    oc delete deployment "$NAME" -n "$DEV_NS" --ignore-not-found 2>/dev/null
    oc delete service "$NAME" -n "$DEV_NS" --ignore-not-found 2>/dev/null
    oc delete route "$NAME" -n "$DEV_NS" --ignore-not-found 2>/dev/null
    oc delete configmap "${NAME}-html" "${NAME}-data" -n "$DEV_NS" --ignore-not-found 2>/dev/null
done

echo ""
echo "--- Cleaning prod namespace ($PROD_NS) ---"
for dep in $(oc get deployments -n "$PROD_NS" -o name 2>/dev/null); do
    NAME=$(echo "$dep" | sed 's|deployment.apps/||')
    echo "  Deleting $NAME..."
    oc delete deployment "$NAME" -n "$PROD_NS" --ignore-not-found 2>/dev/null
    oc delete service "$NAME" -n "$PROD_NS" --ignore-not-found 2>/dev/null
    oc delete route "$NAME" -n "$PROD_NS" --ignore-not-found 2>/dev/null
    oc delete configmap "${NAME}-html" "${NAME}-data" -n "$PROD_NS" --ignore-not-found 2>/dev/null
done

echo ""
echo "--- Restarting services (clears in-memory state) ---"
oc rollout restart deployment/campaign-director -n "$NAMESPACE" 2>/dev/null && echo "  Campaign Director restarted"
oc rollout restart deployment/campaign-api -n "$NAMESPACE" 2>/dev/null && echo "  Campaign API restarted (inbox cleared)"

echo ""
echo "--- Waiting for rollouts ---"
oc rollout status deployment/campaign-director -n "$NAMESPACE" --timeout=60s 2>/dev/null || true
oc rollout status deployment/campaign-api -n "$NAMESPACE" --timeout=60s 2>/dev/null || true

echo ""
echo "--- Remaining in dev namespace ---"
oc get deployments -n "$DEV_NS" 2>/dev/null || echo "  (empty)"

echo ""
echo "=========================================="
echo "Demo reset complete!"
echo "=========================================="
echo "Dashboard is clean. Only '$KEEP' remains."
echo ""

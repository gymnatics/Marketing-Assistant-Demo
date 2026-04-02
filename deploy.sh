#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-marketing-assistant-v2}"
OVERLAY="${OVERLAY:-k8s/overlays/dev}"

echo "=========================================="
echo "Simon Casino Resort - Deploy to OpenShift"
echo "=========================================="

cd "$(dirname "$0")"

if ! oc whoami &> /dev/null; then
    echo "Error: Not logged in to OpenShift. Please run 'oc login' first."
    exit 1
fi

echo "Logged in as: $(oc whoami)"
echo "Namespace: $NAMESPACE"
echo ""

# --- Gather cluster-specific values ---
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "")
if [ -z "$CLUSTER_DOMAIN" ]; then
    read -p "Cluster domain (e.g., apps.cluster-xxx.xxx.opentlc.com): " CLUSTER_DOMAIN
fi
echo "Cluster domain: $CLUSTER_DOMAIN"

echo ""
echo "--- Model Endpoints ---"
echo "Enter the model route hostnames (without https:// prefix)"
echo ""

read -p "Code Model route (Qwen Coder) [press Enter to auto-detect]: " CODE_ROUTE
if [ -z "$CODE_ROUTE" ]; then
    CODE_ROUTE=$(oc get route -n 0-marketing-assistant-demo -o name 2>/dev/null | grep qwen25-coder | head -1 | xargs -I{} oc get {} -n 0-marketing-assistant-demo -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    [ -n "$CODE_ROUTE" ] && echo "  Auto-detected: $CODE_ROUTE" || echo "  Not found. You can set CODE_MODEL_ENDPOINT env var later."
fi

read -p "Language Model route (Qwen3) [press Enter to auto-detect]: " LANG_ROUTE
if [ -z "$LANG_ROUTE" ]; then
    LANG_ROUTE=$(oc get route -n 0-marketing-assistant-demo -o name 2>/dev/null | grep qwen3 | head -1 | xargs -I{} oc get {} -n 0-marketing-assistant-demo -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    [ -n "$LANG_ROUTE" ] && echo "  Auto-detected: $LANG_ROUTE" || echo "  Not found."
fi

read -p "Image Model route (FLUX.2) [press Enter to auto-detect]: " IMG_ROUTE
if [ -z "$IMG_ROUTE" ]; then
    IMG_ROUTE=$(oc get route -n 0-marketing-assistant-demo -o name 2>/dev/null | grep flux | head -1 | xargs -I{} oc get {} -n 0-marketing-assistant-demo -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    [ -n "$IMG_ROUTE" ] && echo "  Auto-detected: $IMG_ROUTE" || echo "  Not found."
fi

echo ""
echo "--- Generating Config ---"

# Update configmap patch with cluster domain
cat > k8s/overlays/dev/configmap-patch.yaml << EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: marketing-assistant-config
data:
  CLUSTER_DOMAIN: "${CLUSTER_DOMAIN}"
  DEV_NAMESPACE: "${NAMESPACE/v2/dev}"
  PROD_NAMESPACE: "${NAMESPACE/v2/prod}"
  IMAGEGEN_MCP_SELF_URL: "https://imagegen-mcp-${NAMESPACE}.${CLUSTER_DOMAIN}"
EOF
echo "  ConfigMap patch generated"

# Generate secret with endpoints
cat > /tmp/marketing-assistant-secret.yaml << EOF
apiVersion: v1
kind: Secret
metadata:
  name: marketing-assistant-secrets
  namespace: ${NAMESPACE}
type: Opaque
stringData:
  CODE_MODEL_ENDPOINT: "https://${CODE_ROUTE}/v1"
  LANG_MODEL_ENDPOINT: "https://${LANG_ROUTE}/v1"
  IMAGEGEN_MODEL_ENDPOINT: "https://${IMG_ROUTE}/v1"
  MONGODB_URI: "mongodb://mongodb:27017"
EOF
echo "  Secret generated"

echo ""
echo "--- Deploying ---"

# Apply Kustomize (everything except secret)
echo "Applying Kustomize overlay..."
oc apply -k "$OVERLAY" 2>&1 | grep -E "created|configured|unchanged" | head -20

# Apply secret separately
echo "Applying secret..."
oc apply -f /tmp/marketing-assistant-secret.yaml
rm /tmp/marketing-assistant-secret.yaml

echo ""
echo "Waiting for deployments..."
DEPLOYMENTS=(
    "mongodb"
    "mongodb-mcp"
    "imagegen-mcp"
    "event-hub"
    "policy-guardian"
    "creative-producer"
    "customer-analyst"
    "delivery-manager"
    "campaign-director"
    "campaign-api"
    "frontend"
)

for DEPLOY in "${DEPLOYMENTS[@]}"; do
    echo "  Waiting for $DEPLOY..."
    oc rollout status deployment/$DEPLOY -n $NAMESPACE --timeout=120s 2>/dev/null || echo "  $DEPLOY not ready (may need image push first)"
done

# Seed MongoDB
echo ""
echo "Seeding MongoDB..."
sleep 5
oc exec deployment/mongodb-mcp -n $NAMESPACE -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py 2>/dev/null || echo "  Seed failed (try manually later)"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Routes:"
oc get routes -n $NAMESPACE -o custom-columns=NAME:.metadata.name,HOST:.spec.host 2>/dev/null
echo ""
echo "Frontend:"
oc get route marketing-assistant-v2 -n $NAMESPACE -o jsonpath='https://{.spec.host}{"\n"}' 2>/dev/null || echo "Route not found"
echo ""
echo "Next steps:"
echo "  - Import vLLM-Omni runtime: oc apply -f k8s/imagegen/serving-runtime.yaml"
echo "  - Deploy guardrails: see k8s/guardrails/README.md"
echo "  - Deploy guardrails MinIO secret: oc apply -f k8s/guardrails/minio-secret-example.yaml"

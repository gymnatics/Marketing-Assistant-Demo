#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-marketing-assistant-v2}"
MODEL_NS="${MODEL_NS:-0-marketing-assistant-demo}"
OVERLAY="${OVERLAY:-k8s/overlays/dev}"

echo "=========================================="
echo "Simon Casino Resort - Deploy to OpenShift"
echo "=========================================="

cd "$(dirname "$0")"

if ! oc whoami &> /dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

echo "Logged in as: $(oc whoami)"
echo "App namespace: $NAMESPACE"
echo "Model namespace: $MODEL_NS"
echo ""

# --- Cluster domain ---
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "")
if [ -z "$CLUSTER_DOMAIN" ]; then
    read -p "Cluster domain (e.g., apps.cluster-xxx.opentlc.com): " CLUSTER_DOMAIN
fi
echo "Cluster domain: $CLUSTER_DOMAIN"
echo ""

################################################################################
# Step 1: Models (optional)
################################################################################
echo "--- Step 1: Model Setup ---"
echo ""

# Check if models are already served
ISVC_COUNT=$(oc get inferenceservice -n "$MODEL_NS" --no-headers 2>/dev/null | wc -l | tr -d ' ')

if [ "$ISVC_COUNT" -ge 3 ]; then
    echo "Found $ISVC_COUNT InferenceServices in $MODEL_NS — skipping model deploy."
    echo ""
else
    echo "Found $ISVC_COUNT InferenceServices in $MODEL_NS."
    read -p "Deploy model manifests from k8s/models/? (y/N): " DEPLOY_MODELS
    if [ "$DEPLOY_MODELS" = "y" ] || [ "$DEPLOY_MODELS" = "Y" ]; then
        echo "Applying model manifests to $MODEL_NS..."
        oc apply -k k8s/models/ -n "$MODEL_NS" 2>&1 | grep -E "created|configured|unchanged"
        echo ""
        echo "NOTE: Models need S3/PVC data connections configured in RHOAI."
        echo "      See k8s/models/README.md for storage setup instructions."
        echo ""
    fi
fi

################################################################################
# Step 1b: Guardrails (optional)
################################################################################
echo "--- Step 1b: Guardrails ---"
echo ""

GUARDRAILS_COUNT=$(oc get deployment -n "$NAMESPACE" --no-headers 2>/dev/null | grep -cE "guardrails|hap|prompt-injection|chunker|lingua" || echo "0")

if [ "$GUARDRAILS_COUNT" -ge 3 ]; then
    echo "Found $GUARDRAILS_COUNT guardrails components — skipping."
    echo ""
else
    read -p "Deploy TrustyAI guardrails? (y/N): " DEPLOY_GUARDRAILS
    if [ "$DEPLOY_GUARDRAILS" = "y" ] || [ "$DEPLOY_GUARDRAILS" = "Y" ]; then
        if [ -f k8s/guardrails/minio-secret-example.yaml ]; then
            echo "Applying MinIO secret for guardrails..."
            oc apply -f k8s/guardrails/minio-secret-example.yaml -n "$NAMESPACE" 2>&1 | grep -E "created|configured|unchanged"
        fi
        echo "Applying guardrails manifests..."
        oc apply -k k8s/guardrails/ -n "$NAMESPACE" 2>&1 | grep -E "created|configured|unchanged"
        echo ""
    fi
fi

################################################################################
# Step 2: Detect model endpoints
################################################################################
echo "--- Step 2: Model Endpoints ---"
echo ""

# List available InferenceServices
ISVC_LIST=$(oc get inferenceservice -n "$MODEL_NS" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{end}' 2>/dev/null || echo "")

if [ -z "$ISVC_LIST" ]; then
    echo "No InferenceServices found in $MODEL_NS."
    echo "Enter model route hostnames manually (without https://):"
    echo ""
    read -p "  Code Model route (for HTML generation): " CODE_ROUTE
    read -p "  Language Model route (for email + tool calling): " LANG_ROUTE
    read -p "  Image Model route (for image generation): " IMG_ROUTE
else
    echo "Available models in $MODEL_NS:"
    IDX=0
    declare -a ISVC_NAMES=()
    declare -a ISVC_ROUTES=()
    for isvc in $ISVC_LIST; do
        ROUTE=$(oc get route "${isvc}" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || \
                oc get route "${isvc}-predictor" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "no-route")
        ISVC_NAMES+=("$isvc")
        ISVC_ROUTES+=("$ROUTE")
        echo "  [$IDX] $isvc → $ROUTE"
        IDX=$((IDX + 1))
    done
    echo ""

    # Auto-detect by name pattern, fallback to user selection
    auto_detect_route() {
        local pattern="$1"
        local label="$2"
        local default_idx="$3"
        local found=""
        for i in "${!ISVC_NAMES[@]}"; do
            if echo "${ISVC_NAMES[$i]}" | grep -qi "$pattern"; then
                found="${ISVC_ROUTES[$i]}"
                echo "  Auto-detected $label: ${ISVC_NAMES[$i]} → $found"
                echo "$found"
                return
            fi
        done
        if [ -n "$default_idx" ] && [ -n "${ISVC_ROUTES[$default_idx]}" ]; then
            echo "${ISVC_ROUTES[$default_idx]}"
            return
        fi
        echo ""
    }

    CODE_ROUTE=$(auto_detect_route "coder\|code" "Code Model" "0")
    LANG_ROUTE=$(auto_detect_route "qwen3\|lang\|chat" "Language Model" "1")
    IMG_ROUTE=$(auto_detect_route "flux\|image\|omni" "Image Model" "2")

    # Let user override if auto-detection is wrong
    echo ""
    read -p "  Code Model [$CODE_ROUTE] (Enter to keep, or type index/hostname): " CODE_OVERRIDE
    if [ -n "$CODE_OVERRIDE" ]; then
        if [[ "$CODE_OVERRIDE" =~ ^[0-9]+$ ]]; then
            CODE_ROUTE="${ISVC_ROUTES[$CODE_OVERRIDE]}"
        else
            CODE_ROUTE="$CODE_OVERRIDE"
        fi
    fi

    read -p "  Language Model [$LANG_ROUTE] (Enter to keep): " LANG_OVERRIDE
    if [ -n "$LANG_OVERRIDE" ]; then
        if [[ "$LANG_OVERRIDE" =~ ^[0-9]+$ ]]; then
            LANG_ROUTE="${ISVC_ROUTES[$LANG_OVERRIDE]}"
        else
            LANG_ROUTE="$LANG_OVERRIDE"
        fi
    fi

    read -p "  Image Model [$IMG_ROUTE] (Enter to keep): " IMG_OVERRIDE
    if [ -n "$IMG_OVERRIDE" ]; then
        if [[ "$IMG_OVERRIDE" =~ ^[0-9]+$ ]]; then
            IMG_ROUTE="${ISVC_ROUTES[$IMG_OVERRIDE]}"
        else
            IMG_ROUTE="$IMG_OVERRIDE"
        fi
    fi
fi

echo ""

################################################################################
# Step 3: Generate config
################################################################################
echo "--- Step 3: Generating Config ---"

# ConfigMap patch
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

# Secret
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

################################################################################
# Step 4: Deploy app
################################################################################
echo "--- Step 4: Deploying App ---"

echo "Applying Kustomize overlay..."
oc apply -k "$OVERLAY" 2>&1 | grep -E "created|configured|unchanged" | head -20

echo "Applying secret..."
oc apply -f /tmp/marketing-assistant-secret.yaml
rm /tmp/marketing-assistant-secret.yaml

echo "Applying RBAC (cross-namespace permissions)..."
oc apply -f k8s/rbac.yaml 2>&1 | grep -E "created|configured|unchanged" || true

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
    oc rollout status deployment/$DEPLOY -n $NAMESPACE --timeout=120s 2>/dev/null || echo "    $DEPLOY not ready (may need image push first)"
done

################################################################################
# Step 5: Seed data
################################################################################
echo ""
echo "--- Step 5: Seeding MongoDB ---"
sleep 5
oc exec deployment/mongodb-mcp -n $NAMESPACE -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py 2>/dev/null || echo "  Seed failed (try manually later)"

################################################################################
# Summary
################################################################################
echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Model Endpoints:"
echo "  Code:     https://${CODE_ROUTE}/v1"
echo "  Language:  https://${LANG_ROUTE}/v1"
echo "  Image:    https://${IMG_ROUTE}/v1"
echo ""
echo "Routes:"
oc get routes -n $NAMESPACE -o custom-columns=NAME:.metadata.name,HOST:.spec.host 2>/dev/null
echo ""
echo "Frontend:"
FRONTEND_URL=$(oc get route -n $NAMESPACE -o jsonpath='{.items[0].spec.host}' 2>/dev/null || echo "not found")
echo "  https://${FRONTEND_URL}"
echo ""
echo "Useful commands:"
echo "  ./reset-demo.sh          # Clean slate (remove generated campaigns)"
echo "  ./build-and-push.sh      # Rebuild container images after code changes"
echo ""

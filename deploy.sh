#!/bin/bash
set -e

NAMESPACE="${NAMESPACE:-0-marketing-assistant-demo}"
MODEL_NS="${MODEL_NS:-0-marketing-assistant-demo}"
DEV_NS="${DEV_NS:-}"
PROD_NS="${PROD_NS:-}"
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

# Determine dev/prod namespaces
if [ -z "$DEV_NS" ]; then
    DEFAULT_DEV="${NAMESPACE}-dev"
    read -p "Dev namespace for campaign previews [$DEFAULT_DEV]: " DEV_NS_INPUT
    DEV_NS="${DEV_NS_INPUT:-$DEFAULT_DEV}"
fi
if [ -z "$PROD_NS" ]; then
    DEFAULT_PROD="${NAMESPACE}-prod"
    read -p "Prod namespace for live campaigns [$DEFAULT_PROD]: " PROD_NS_INPUT
    PROD_NS="${PROD_NS_INPUT:-$DEFAULT_PROD}"
fi

echo "Dev namespace: $DEV_NS"
echo "Prod namespace: $PROD_NS"
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
ISVC_COUNT=$(oc get inferenceservice -n "$MODEL_NS" --no-headers 2>/dev/null | wc -l | tr -dc '0-9')
ISVC_COUNT=${ISVC_COUNT:-0}

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

GUARDRAILS_COUNT=$(oc get deployment -n "$NAMESPACE" --no-headers 2>/dev/null | grep -cE "guardrails|hap|prompt-injection|chunker|lingua" 2>/dev/null || true)
GUARDRAILS_COUNT=${GUARDRAILS_COUNT:-0}
GUARDRAILS_COUNT=$(echo "$GUARDRAILS_COUNT" | tr -dc '0-9')
GUARDRAILS_COUNT=${GUARDRAILS_COUNT:-0}

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
# Step 1c: MLflow (optional)
################################################################################
echo "--- Step 1c: MLflow Tracking ---"
echo ""
MLFLOW_ROUTE=""
MLFLOW_COUNT=$(oc get deployment -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "mlflow-deployment" 2>/dev/null || true)
MLFLOW_COUNT=$(echo "$MLFLOW_COUNT" | tr -dc '0-9')
MLFLOW_COUNT=${MLFLOW_COUNT:-0}

if [ "$MLFLOW_COUNT" -ge 1 ]; then
    echo "MLflow already deployed — ensuring CLUSTER_DOMAIN is current."
    oc set env deployment/mlflow-deployment -n "$NAMESPACE" "CLUSTER_DOMAIN=${CLUSTER_DOMAIN}" 2>/dev/null || true
    MLFLOW_ROUTE=$(oc get route mlflow-route -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
else
    read -p "Deploy MLflow tracking server? (y/N): " DEPLOY_MLFLOW
    if [ "$DEPLOY_MLFLOW" = "y" ] || [ "$DEPLOY_MLFLOW" = "Y" ]; then
        echo "Applying MLflow manifests..."
        for f in k8s/mlflow/01-mlflow-postgres.yml k8s/mlflow/02-mlflow-minio.yml k8s/mlflow/03-mlflow-server.yml; do
            echo "  Applying $f..."
            oc apply -f "$f" -n "$NAMESPACE" 2>&1 | grep -E "created|configured|unchanged"
        done
        echo "  Patching MLflow CLUSTER_DOMAIN → ${CLUSTER_DOMAIN}"
        oc set env deployment/mlflow-deployment -n "$NAMESPACE" "CLUSTER_DOMAIN=${CLUSTER_DOMAIN}"
        echo ""
        echo "Waiting for MLflow stack to be ready..."
        oc rollout status deployment/mlflow-postgresql-deployment -n "$NAMESPACE" --timeout=120s 2>/dev/null || echo "  PostgreSQL not ready yet"
        oc rollout status deployment/mlflow-minio-deployment -n "$NAMESPACE" --timeout=120s 2>/dev/null || echo "  MinIO not ready yet"
        oc rollout status deployment/mlflow-deployment -n "$NAMESPACE" --timeout=180s 2>/dev/null || echo "  MLflow not ready yet"
        MLFLOW_ROUTE=$(oc get route mlflow-route -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    fi
fi

if [ -n "$MLFLOW_ROUTE" ]; then
    echo "MLflow UI: https://${MLFLOW_ROUTE}"
fi
echo ""

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
                echo "  Auto-detected $label: ${ISVC_NAMES[$i]} → $found" >&2
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
  DEV_NAMESPACE: "${DEV_NS}"
  PROD_NAMESPACE: "${PROD_NS}"
  APP_NAMESPACE: "${NAMESPACE}"
  IMAGEGEN_MCP_SELF_URL: "https://imagegen-mcp-${NAMESPACE}.${CLUSTER_DOMAIN}"
EOF

if [ -n "$MLFLOW_ROUTE" ]; then
    echo '  MLFLOW_TRACKING_URI: "https://'"${MLFLOW_ROUTE}"'"' >> k8s/overlays/dev/configmap-patch.yaml
    echo "  MLflow tracking URI added to configmap"
fi
echo "  ConfigMap patch generated"

# Update Kustomize namespace to match
sed -i.bak "s/^namespace: .*/namespace: ${NAMESPACE}/" k8s/base/kustomization.yaml k8s/overlays/dev/kustomization.yaml 2>/dev/null
rm -f k8s/base/kustomization.yaml.bak k8s/overlays/dev/kustomization.yaml.bak 2>/dev/null
# Update namespace.yaml (only the metadata.name, not labels)
sed -i.bak "4s/name: .*/name: ${NAMESPACE}/" k8s/base/namespace.yaml 2>/dev/null
rm -f k8s/base/namespace.yaml.bak 2>/dev/null
echo "  Kustomize namespace set to ${NAMESPACE}"

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

#echo "Applying Kagenti CRB for namespace: ${NAMESPACE}"
#sed "s/NAMESPACE_PLACEHOLDER/${NAMESPACE}/" k8s/kagenti/crb.yaml | oc apply -f -

echo "Applying secret..."
oc apply -f /tmp/marketing-assistant-secret.yaml
rm /tmp/marketing-assistant-secret.yaml

echo "Applying RBAC (cross-namespace permissions)..."
oc create namespace "$DEV_NS" --dry-run=client -o yaml | oc apply -f - 2>/dev/null || true
oc create namespace "$PROD_NS" --dry-run=client -o yaml | oc apply -f - 2>/dev/null || true
cat <<EOF | oc apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: marketing-assistant-deploy-dev
  namespace: ${DEV_NS}
subjects:
  - kind: ServiceAccount
    name: default
    namespace: ${NAMESPACE}
roleRef:
  kind: ClusterRole
  name: edit
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: marketing-assistant-deploy-prod
  namespace: ${PROD_NS}
subjects:
  - kind: ServiceAccount
    name: default
    namespace: ${NAMESPACE}
roleRef:
  kind: ClusterRole
  name: edit
  apiGroup: rbac.authorization.k8s.io
EOF
echo "  RBAC applied for ${NAMESPACE} → ${DEV_NS}, ${PROD_NS}"

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
if [ -n "$MLFLOW_ROUTE" ]; then
    echo "MLflow:"
    echo "  https://${MLFLOW_ROUTE}"
    echo ""
fi
echo "Useful commands:"
echo "  ./reset-demo.sh          # Clean slate (remove generated campaigns)"
echo "  ./build-and-push.sh      # Rebuild container images after code changes"
echo ""

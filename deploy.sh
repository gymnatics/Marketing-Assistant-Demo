#!/bin/bash
set -e

DEFAULT_NS="0-marketing-assistant-demo"
NAMESPACE="${NAMESPACE:-}"
MODEL_NS="${MODEL_NS:-}"
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
echo ""

# Determine app namespace
if [ -z "$NAMESPACE" ]; then
    read -p "App namespace [$DEFAULT_NS]: " NS_INPUT
    NAMESPACE="${NS_INPUT:-$DEFAULT_NS}"
fi
echo "App namespace: $NAMESPACE"

# Model namespace defaults to same as app namespace
if [ -z "$MODEL_NS" ]; then
    read -p "Model namespace [$NAMESPACE]: " MODEL_NS_INPUT
    MODEL_NS="${MODEL_NS_INPUT:-$NAMESPACE}"
fi
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

# --- Ensure all namespaces exist before applying any resources ---
echo "Ensuring namespaces exist..."
UNIQUE_NS=$(echo "$NAMESPACE $MODEL_NS $DEV_NS $PROD_NS" | tr ' ' '\n' | sort -u)
for NS_TO_CREATE in $UNIQUE_NS; do
    if [ -n "$NS_TO_CREATE" ]; then
        oc create namespace "$NS_TO_CREATE" --dry-run=client -o yaml | oc apply -f - 2>/dev/null || true
    fi
done
echo ""

################################################################################
# Step 1: Models (optional)
################################################################################
echo "--- Step 1: Model Setup ---"
echo ""

# Detect existing InferenceServices by pattern (names may vary slightly)
ISVC_LIST=$(oc get inferenceservice -n "$MODEL_NS" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null || echo "")
HAS_CODER=$(echo "$ISVC_LIST" | grep -ci "coder" || true)
HAS_QWEN3=$(echo "$ISVC_LIST" | grep -ci "qwen3" || true)
HAS_FLUX=$(echo "$ISVC_LIST" | grep -ci "flux" || true)
MODELS_FOUND=$((HAS_CODER + HAS_QWEN3 + HAS_FLUX))

if [ "$MODELS_FOUND" -ge 3 ]; then
    echo "All 3 models already deployed in $MODEL_NS — skipping."
    echo "  $(echo "$ISVC_LIST" | grep -i "coder" | head -1) (code model)"
    echo "  $(echo "$ISVC_LIST" | grep -i "qwen3" | head -1) (language model)"
    echo "  $(echo "$ISVC_LIST" | grep -i "flux" | head -1) (image model)"
    echo ""
else
    echo "Found $MODELS_FOUND of 3 required models in $MODEL_NS."
    [ "$HAS_CODER" -ge 1 ] && echo "  ✓ Code model (Qwen2.5-Coder) found" || echo "  ✗ Code model (Qwen2.5-Coder) missing"
    [ "$HAS_QWEN3" -ge 1 ] && echo "  ✓ Language model (Qwen3) found" || echo "  ✗ Language model (Qwen3) missing"
    [ "$HAS_FLUX" -ge 1 ] && echo "  ✓ Image model (FLUX.2) found" || echo "  ✗ Image model (FLUX.2) missing"
    echo ""
    echo "Deploy models via:"
    echo "  (1) RHOAI Dashboard UI (recommended — creates data connections automatically)"
    echo "  (2) RHOAI-Toolkit scripts (automated S3 setup + serving)"
    echo "  (3) Kustomize manifests (requires pre-configured S3 data connections)"
    echo "  (s) Skip for now"
    read -p "Choose [1/2/3/s]: " MODEL_CHOICE

    if [ "$MODEL_CHOICE" = "3" ]; then
        echo "Applying model manifests to $MODEL_NS..."
        if oc apply -k k8s/models/ -n "$MODEL_NS" 2>&1 | tee /tmp/model-apply.log | grep -E "created|configured|unchanged"; then
            echo ""
        else
            echo ""
            echo "WARNING: Model manifest apply had errors:"
            grep -i "error\|failed\|not found" /tmp/model-apply.log 2>/dev/null || cat /tmp/model-apply.log
            echo ""
        fi
        rm -f /tmp/model-apply.log

        # Ensure storage-config has keys for all 3 models
        echo "Checking storage-config for model data connections..."
        STORAGE_KEYS=$(oc get secret storage-config -n "$MODEL_NS" -o jsonpath='{.data}' 2>/dev/null | python3 -c "import sys,json; print(' '.join(json.load(sys.stdin).keys()))" 2>/dev/null || echo "")

        # Try to find a working S3 endpoint from existing data connections
        S3_ENDPOINT=""
        S3_BUCKET=""
        S3_ACCESS=""
        S3_SECRET=""
        S3_REGION=""
        for DC_SECRET in $(oc get secret -n "$MODEL_NS" -o name 2>/dev/null | grep -E "aws-connection|data-connection" | head -5); do
            DC_NAME=$(echo "$DC_SECRET" | sed 's|secret/||')
            CANDIDATE_ENDPOINT=$(oc get secret "$DC_NAME" -n "$MODEL_NS" -o jsonpath='{.data.AWS_S3_ENDPOINT}' 2>/dev/null | base64 -d 2>/dev/null)
            if [ -n "$CANDIDATE_ENDPOINT" ]; then
                S3_ENDPOINT="$CANDIDATE_ENDPOINT"
                S3_BUCKET=$(oc get secret "$DC_NAME" -n "$MODEL_NS" -o jsonpath='{.data.AWS_S3_BUCKET}' 2>/dev/null | base64 -d 2>/dev/null)
                S3_ACCESS=$(oc get secret "$DC_NAME" -n "$MODEL_NS" -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' 2>/dev/null | base64 -d 2>/dev/null)
                S3_SECRET=$(oc get secret "$DC_NAME" -n "$MODEL_NS" -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
                S3_REGION=$(oc get secret "$DC_NAME" -n "$MODEL_NS" -o jsonpath='{.data.AWS_DEFAULT_REGION}' 2>/dev/null | base64 -d 2>/dev/null)
                echo "  Found S3 config from $DC_NAME → $S3_ENDPOINT/$S3_BUCKET"
                break
            fi
        done

        # Also check model-storage namespace if no local data connection found
        if [ -z "$S3_ENDPOINT" ]; then
            S3_ENDPOINT=$(oc get secret aws-connection-minio -n model-storage -o jsonpath='{.data.AWS_S3_ENDPOINT}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
            if [ -n "$S3_ENDPOINT" ]; then
                S3_BUCKET=$(oc get secret aws-connection-minio -n model-storage -o jsonpath='{.data.AWS_S3_BUCKET}' 2>/dev/null | base64 -d 2>/dev/null)
                S3_ACCESS=$(oc get secret aws-connection-minio -n model-storage -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' 2>/dev/null | base64 -d 2>/dev/null)
                S3_SECRET=$(oc get secret aws-connection-minio -n model-storage -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' 2>/dev/null | base64 -d 2>/dev/null)
                S3_REGION=$(oc get secret aws-connection-minio -n model-storage -o jsonpath='{.data.AWS_DEFAULT_REGION}' 2>/dev/null | base64 -d 2>/dev/null)
                echo "  Found S3 config from model-storage namespace → $S3_ENDPOINT/$S3_BUCKET"
            fi
        fi

        if [ -n "$S3_ENDPOINT" ]; then
            S3_JSON="{\"type\":\"s3\",\"access_key_id\":\"${S3_ACCESS}\",\"secret_access_key\":\"${S3_SECRET}\",\"endpoint_url\":\"${S3_ENDPOINT}\",\"bucket\":\"${S3_BUCKET}\",\"region\":\"${S3_REGION:-us-east-1}\"}"

            # Get ISVC storage key names (may differ from defaults)
            for ISVC_NAME in $(oc get inferenceservice -n "$MODEL_NS" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
                STORAGE_KEY=$(oc get inferenceservice "$ISVC_NAME" -n "$MODEL_NS" -o jsonpath='{.spec.predictor.model.storage.key}' 2>/dev/null)
                if [ -n "$STORAGE_KEY" ] && ! echo "$STORAGE_KEYS" | grep -q "$STORAGE_KEY"; then
                    echo "  Adding storage key '$STORAGE_KEY' to storage-config..."
                fi
            done

            # Rebuild storage-config with all needed keys
            python3 -c "
import json, base64, subprocess, sys

ns = '${MODEL_NS}'
s3_json = '${S3_JSON}'

# Get existing storage-config
result = subprocess.run(['oc', 'get', 'secret', 'storage-config', '-n', ns, '-o', 'json'],
    capture_output=True, text=True)

if result.returncode == 0:
    existing = json.loads(result.stdout).get('data', {})
else:
    existing = {}

# Get all ISVC storage keys
result2 = subprocess.run(['oc', 'get', 'inferenceservice', '-n', ns, '-o', 'json'],
    capture_output=True, text=True)
if result2.returncode == 0:
    isvcs = json.loads(result2.stdout).get('items', [])
    for isvc in isvcs:
        key = isvc.get('spec', {}).get('predictor', {}).get('model', {}).get('storage', {}).get('key', '')
        if key and key not in existing:
            existing[key] = base64.b64encode(s3_json.encode()).decode()

# Write updated secret
secret = {
    'apiVersion': 'v1', 'kind': 'Secret',
    'metadata': {'name': 'storage-config', 'namespace': ns},
    'type': 'Opaque', 'data': existing,
}
with open('/tmp/storage-config-update.json', 'w') as f:
    json.dump(secret, f)
" 2>/dev/null
            if [ -f /tmp/storage-config-update.json ]; then
                oc apply -f /tmp/storage-config-update.json 2>/dev/null || \
                    oc create -f /tmp/storage-config-update.json 2>/dev/null || true
                rm -f /tmp/storage-config-update.json
                echo "  storage-config updated"
            fi
        else
            echo "  WARNING: No S3 data connection found. Models may fail to start."
            echo "  Configure data connections in RHOAI Dashboard or run RHOAI-Toolkit first."
        fi
        echo ""

    elif [ "$MODEL_CHOICE" = "2" ]; then
        echo ""
        echo "Run RHOAI-Toolkit to set up model storage and serving:"
        echo "  git clone https://github.com/gymnatics/RHOAI-Toolkit.git && cd RHOAI-Toolkit"
        echo "  export NAMESPACE=$MODEL_NS"
        echo "  ./scripts/setup-model-storage.sh -n \$NAMESPACE"
        echo "  ./scripts/download-model.sh s3 RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic"
        echo "  ./scripts/download-model.sh s3 RedHatAI/Qwen3-32B-FP8-dynamic"
        echo "  ./scripts/download-model.sh s3 black-forest-labs/FLUX.2-klein-4B"
        echo ""
        echo "Then serve them (see README for full commands). Re-run deploy.sh after."
        echo ""

    elif [ "$MODEL_CHOICE" = "1" ]; then
        echo ""
        echo "Deploy the following models via RHOAI Dashboard UI:"
        echo "  1. Qwen2.5-Coder-32B: path=RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic"
        echo "     Args: --max-model-len=16384 --gpu-memory-utilization=0.95 --enable-auto-tool-choice --tool-call-parser=hermes"
        echo "  2. Qwen3-32B: path=RedHatAI/Qwen3-32B-FP8-dynamic"
        echo "     Args: --dtype=auto --max-model-len=16000 --gpu-memory-utilization=0.90 --enable-auto-tool-choice --tool-call-parser=hermes"
        echo "  3. FLUX.2-klein-4B: path=black-forest-labs/FLUX.2-klein-4B (use vLLM-Omni runtime)"
        echo "     Args: --omni --gpu-memory-utilization=0.90 --trust-remote-code"
        echo ""
        echo "Re-run deploy.sh after all 3 models show READY: True."
        echo ""
    else
        echo "Skipping model deployment."
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
            oc apply -f k8s/guardrails/minio-secret-example.yaml -n "$NAMESPACE" 2>&1 | grep -E "created|configured|unchanged" || true
        fi
        echo "Applying guardrails manifests..."
        oc apply -k k8s/guardrails/ -n "$NAMESPACE" 2>&1 | grep -E "created|configured|unchanged" || echo "  WARNING: Guardrails apply failed (TrustyAI may not be installed). Continuing..."
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

# Auto-detect model routes by name pattern (skip guardrails models)
_find_model_route() {
    local pattern="$1"
    for isvc in $(oc get inferenceservice -n "$MODEL_NS" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
        if echo "$isvc" | grep -qi "$pattern" && ! echo "$isvc" | grep -qi "guardrail\|detector"; then
            local route=$(oc get route "$isvc" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || \
                          oc get route "${isvc}-predictor" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
            if [ -n "$route" ]; then
                echo "$route"
                return
            fi
        fi
    done
    echo ""
}

CODE_ROUTE=$(_find_model_route "coder\|code")
LANG_ROUTE=$(_find_model_route "qwen3\|lang")
IMG_ROUTE=$(_find_model_route "flux\|omni")

# Show what was detected
echo "Detected model endpoints:"
[ -n "$CODE_ROUTE" ] && echo "  Code Model (HTML gen):      $CODE_ROUTE" || echo "  Code Model (HTML gen):      NOT FOUND"
[ -n "$LANG_ROUTE" ] && echo "  Language Model (email/tools): $LANG_ROUTE" || echo "  Language Model (email/tools): NOT FOUND"
[ -n "$IMG_ROUTE" ] && echo "  Image Model (hero images):   $IMG_ROUTE" || echo "  Image Model (hero images):   NOT FOUND"
echo ""

# Only prompt if something is missing or user wants to override
if [ -z "$CODE_ROUTE" ] || [ -z "$LANG_ROUTE" ] || [ -z "$IMG_ROUTE" ]; then
    echo "Some models not detected. Enter hostnames manually (without https://):"
    [ -z "$CODE_ROUTE" ] && read -p "  Code Model route: " CODE_ROUTE
    [ -z "$LANG_ROUTE" ] && read -p "  Language Model route: " LANG_ROUTE
    [ -z "$IMG_ROUTE" ] && read -p "  Image Model route: " IMG_ROUTE
    echo ""
else
    read -p "Press Enter to confirm, or type 'edit' to change: " EDIT_MODELS
    if [ "$EDIT_MODELS" = "edit" ]; then
        read -p "  Code Model [$CODE_ROUTE]: " CODE_OVERRIDE
        [ -n "$CODE_OVERRIDE" ] && CODE_ROUTE="$CODE_OVERRIDE"
        read -p "  Language Model [$LANG_ROUTE]: " LANG_OVERRIDE
        [ -n "$LANG_OVERRIDE" ] && LANG_ROUTE="$LANG_OVERRIDE"
        read -p "  Image Model [$IMG_ROUTE]: " IMG_OVERRIDE
        [ -n "$IMG_OVERRIDE" ] && IMG_ROUTE="$IMG_OVERRIDE"
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
if ! oc apply -k "$OVERLAY" 2>&1 | tee /tmp/kustomize-apply.log | grep -E "created|configured|unchanged" | head -20; then
    echo ""
    echo "WARNING: Kustomize apply had issues:"
    grep -i "error\|failed\|invalid\|not found" /tmp/kustomize-apply.log 2>/dev/null || cat /tmp/kustomize-apply.log
    echo ""
fi
rm -f /tmp/kustomize-apply.log

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
# Step 6: KAgenti Platform (optional)
################################################################################
echo ""
echo "--- Step 6: KAgenti Platform ---"
echo ""
KAGENTI_ROUTE=""
KAGENTI_INSTALLED=$(helm list -n kagenti-system --short 2>/dev/null | grep -c "kagenti" || true)
KAGENTI_INSTALLED=$(echo "$KAGENTI_INSTALLED" | tr -dc '0-9')
KAGENTI_INSTALLED=${KAGENTI_INSTALLED:-0}

if [ "$KAGENTI_INSTALLED" -ge 1 ]; then
    echo "KAgenti already installed — skipping."
    KAGENTI_ROUTE=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
else
    read -p "Deploy KAgenti platform (agent discovery + zero-trust auth)? (y/N): " DEPLOY_KAGENTI
    if [ "$DEPLOY_KAGENTI" = "y" ] || [ "$DEPLOY_KAGENTI" = "Y" ]; then

        echo ""
        echo "--- Step 6a: Pre-flight checks ---"

        KAGENTI_EXTRA_SETS=""

        # Check for existing cert-manager -- if present, tell KAgenti to skip its own
        CERTMGR_COUNT=$(oc get deployment -n cert-manager --no-headers 2>/dev/null | wc -l | tr -dc '0-9')
        CERTMGR_COUNT=${CERTMGR_COUNT:-0}
        if [ "$CERTMGR_COUNT" -ge 1 ]; then
            echo "  Existing cert-manager detected — will reuse it."
            KAGENTI_EXTRA_SETS="$KAGENTI_EXTRA_SETS --set components.certManager.enabled=false"
        fi

        # Check for existing Istio -- if present, skip KAgenti's and adopt the namespaces
        ISTIO_COUNT=$(oc get deployment -n istio-system --no-headers 2>/dev/null | wc -l | tr -dc '0-9')
        ISTIO_COUNT=${ISTIO_COUNT:-0}
        if [ "$ISTIO_COUNT" -ge 1 ]; then
            echo "  Existing Istio detected — will reuse it."
            KAGENTI_EXTRA_SETS="$KAGENTI_EXTRA_SETS --set components.istio.enabled=false"
            # Label existing namespaces so Helm can adopt them
            for NS_ADOPT in istio-system istio-cni istio-ztunnel keycloak zero-trust-workload-identity-manager; do
                if oc get ns "$NS_ADOPT" &>/dev/null 2>&1; then
                    oc label namespace "$NS_ADOPT" app.kubernetes.io/managed-by=Helm --overwrite 2>/dev/null || true
                    oc annotate namespace "$NS_ADOPT" meta.helm.sh/release-name=kagenti-deps meta.helm.sh/release-namespace=kagenti-system --overwrite 2>/dev/null || true
                fi
            done
            echo "  Labeled existing namespaces for Helm adoption."
        fi

        if [ "$DEPLOY_KAGENTI" = "y" ] || [ "$DEPLOY_KAGENTI" = "Y" ]; then

            # Enable OVN local gateway mode for Istio Ambient
            NETWORK_TYPE=$(oc get network.config/cluster -o jsonpath='{.spec.networkType}' 2>/dev/null || echo "")
            if [ "$NETWORK_TYPE" = "OVNKubernetes" ]; then
                echo "Enabling OVN local gateway mode for Istio Ambient..."
                oc patch network.operator.openshift.io cluster --type=merge \
                    -p '{"spec":{"defaultNetwork":{"ovnKubernetesConfig":{"gatewayConfig":{"routingViaHost":true}}}}}' 2>/dev/null || echo "  OVN patch failed (may already be set)"
            fi

            # Trust domain from cluster DNS
            DOMAIN="${CLUSTER_DOMAIN}"
            echo "Trust domain: ${DOMAIN}"

            echo ""
            echo "--- Step 6b: Installing KAgenti Helm charts ---"

            # Get latest KAgenti release tag
            KAGENTI_TAG=$(git ls-remote --tags --sort="v:refname" https://github.com/kagenti/kagenti.git 2>/dev/null | tail -n1 | sed 's|.*refs/tags/v||; s/\^{}//' || echo "0.5.0")
            KAGENTI_TAG=${KAGENTI_TAG:-0.5.0}
            echo "KAgenti version: v${KAGENTI_TAG}"

            # Install kagenti-deps (SPIRE, Keycloak, Istio; cert-manager only if not already present)
            echo "  Installing kagenti-deps..."
            helm upgrade --install --create-namespace -n kagenti-system kagenti-deps \
                oci://ghcr.io/kagenti/kagenti/kagenti-deps \
                --version "${KAGENTI_TAG}" \
                --set spire.trustDomain="${DOMAIN}" \
                --set openshift=true \
                $KAGENTI_EXTRA_SETS \
                --wait --timeout 10m 2>&1 | tail -5

            # Install MCP Gateway
            echo "  Installing MCP Gateway..."
            GATEWAY_TAG=$(skopeo list-tags docker://ghcr.io/kagenti/charts/mcp-gateway 2>/dev/null | python3 -c "import sys,json; tags=json.load(sys.stdin)['Tags']; print(tags[-1])" 2>/dev/null || echo "0.4.0")
            helm upgrade --install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway \
                --create-namespace --namespace mcp-system \
                --version "${GATEWAY_TAG}" \
                --wait --timeout 5m 2>&1 | tail -3

            # Install KAgenti (UI, operator)
            echo "  Installing kagenti..."
            helm upgrade --install --create-namespace -n kagenti-system \
                kagenti oci://ghcr.io/kagenti/kagenti/kagenti \
                --version "${KAGENTI_TAG}" \
                --set agentOAuthSecret.spiffePrefix="spiffe://${DOMAIN}/sa" \
                --set uiOAuthSecret.useServiceAccountCA=false \
                --set agentOAuthSecret.useServiceAccountCA=false \
                --wait --timeout 10m 2>&1 | tail -3

            echo ""
            echo "--- Step 6c: Post-install configuration ---"

            # Fix SPIRE daemonset SCC if needed
            SPIRE_READY=$(oc get daemonset spire-agent -n zero-trust-workload-identity-manager -o jsonpath='{.status.numberReady}' 2>/dev/null || echo "0")
            if [ "$SPIRE_READY" = "0" ]; then
                echo "  Fixing SPIRE daemonset SCC..."
                oc adm policy add-scc-to-user privileged -z spire-agent -n zero-trust-workload-identity-manager 2>/dev/null || true
                oc rollout restart daemonsets -n zero-trust-workload-identity-manager spire-agent 2>/dev/null || true
                oc adm policy add-scc-to-user privileged -z spire-spiffe-csi-driver -n zero-trust-workload-identity-manager 2>/dev/null || true
                oc rollout restart daemonsets -n zero-trust-workload-identity-manager spire-spiffe-csi-driver 2>/dev/null || true
            fi

            # Copy keycloak-admin-secret into app namespace (read from Helm-created secret)
            echo "  Creating keycloak-admin-secret in ${NAMESPACE}..."
            KC_ADMIN_U=$(oc get secret keycloak-initial-admin -n keycloak -o go-template='{{.data.username | base64decode}}' 2>/dev/null || echo "admin")
            KC_ADMIN_P=$(oc get secret keycloak-initial-admin -n keycloak -o go-template='{{.data.password | base64decode}}' 2>/dev/null || echo "admin")
            oc create secret generic keycloak-admin-secret -n "${NAMESPACE}" \
                --from-literal=KEYCLOAK_ADMIN_USERNAME="${KC_ADMIN_U}" \
                --from-literal=KEYCLOAK_ADMIN_PASSWORD="${KC_ADMIN_P}" \
                --dry-run=client -o yaml | oc apply -f - 2>/dev/null

            # Label app namespace for KAgenti discovery
            echo "  Labeling namespace for KAgenti discovery..."
            oc label namespace "${NAMESPACE}" kagenti-enabled=true shared-gateway-access=true --overwrite 2>/dev/null || true

            # Apply KAgenti-specific manifests
            echo "  Applying KAgenti manifests..."
            sed "s/NAMESPACE_PLACEHOLDER/${NAMESPACE}/" k8s/kagenti/crb.yaml | oc apply -f - 2>/dev/null || true
            oc apply -k k8s/kagenti/ -n "${NAMESPACE}" 2>&1 | grep -E "created|configured|unchanged" | head -10

            # Patch authbridge-config with actual Keycloak URLs
            KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
            if [ -n "$KEYCLOAK_ROUTE" ]; then
                echo "  Patching AuthBridge config with Keycloak URLs..."
                oc patch configmap authbridge-config -n "${NAMESPACE}" --type=merge \
                    -p "{\"data\":{\"ISSUER\":\"https://${KEYCLOAK_ROUTE}/realms/kagenti\",\"KEYCLOAK_URL\":\"http://keycloak.keycloak.svc.cluster.local:8080\",\"TOKEN_URL\":\"http://keycloak.keycloak.svc.cluster.local:8080/realms/kagenti/protocol/openid-connect/token\"}}" 2>/dev/null
            fi

            # Wire Keycloak URL into the app ConfigMap for frontend SSO
            if [ -n "$KEYCLOAK_ROUTE" ]; then
                echo "  Patching app ConfigMap with Keycloak URL for SSO..."
                oc patch configmap marketing-assistant-config -n "${NAMESPACE}" --type=merge \
                    -p "{\"data\":{\"KEYCLOAK_URL\":\"https://${KEYCLOAK_ROUTE}\"}}" 2>/dev/null
            fi

            echo ""
            echo "--- Step 6d: Keycloak realm configuration ---"
            echo ""
            KEYCLOAK_INTERNAL="http://keycloak.keycloak.svc.cluster.local:8080"
            KC_REALM="kagenti"

            # Read actual Keycloak admin credentials from the secret created by the Helm chart
            KEYCLOAK_ADMIN_USER=$(oc get secret keycloak-initial-admin -n keycloak -o go-template='{{.data.username | base64decode}}' 2>/dev/null || echo "admin")
            KEYCLOAK_ADMIN_PASS=$(oc get secret keycloak-initial-admin -n keycloak -o go-template='{{.data.password | base64decode}}' 2>/dev/null || echo "admin")
            echo "  Keycloak admin user: ${KEYCLOAK_ADMIN_USER}"

            # Get admin token from Keycloak
            echo "  Obtaining Keycloak admin token..."

            # Try internal URL first (from a pod), fall back to external route
            KC_TOKEN=""
            if [ -n "$KEYCLOAK_ROUTE" ]; then
                KC_TOKEN=$(curl -sk -X POST "https://${KEYCLOAK_ROUTE}/realms/master/protocol/openid-connect/token" \
                    -d "client_id=admin-cli" \
                    -d "username=${KEYCLOAK_ADMIN_USER}" \
                    -d "password=${KEYCLOAK_ADMIN_PASS}" \
                    -d "grant_type=password" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
            fi

            if [ -z "$KC_TOKEN" ]; then
                echo "  WARNING: Could not obtain Keycloak admin token."
                echo "  Keycloak realm configuration skipped. Configure manually via Keycloak admin console."
            else
                KC_API="https://${KEYCLOAK_ROUTE}/admin/realms"

                # --- Create 'kagenti' realm if it doesn't exist ---
                REALM_EXISTS=$(curl -sk -o /dev/null -w "%{http_code}" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    "${KC_API}/${KC_REALM}" 2>/dev/null)
                if [ "$REALM_EXISTS" != "200" ]; then
                    echo "  Creating '${KC_REALM}' realm..."
                    curl -sk -X POST "${KC_API}" \
                        -H "Authorization: Bearer ${KC_TOKEN}" \
                        -H "Content-Type: application/json" \
                        -d "{\"realm\":\"${KC_REALM}\",\"enabled\":true,\"registrationAllowed\":false}" 2>/dev/null
                else
                    echo "  Realm '${KC_REALM}' already exists."
                fi

                # Refresh token (realm creation may take a moment)
                KC_TOKEN=$(curl -sk -X POST "https://${KEYCLOAK_ROUTE}/realms/master/protocol/openid-connect/token" \
                    -d "client_id=admin-cli" \
                    -d "username=${KEYCLOAK_ADMIN_USER}" \
                    -d "password=${KEYCLOAK_ADMIN_PASS}" \
                    -d "grant_type=password" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

                KC_REALM_API="${KC_API}/${KC_REALM}"
                FRONTEND_HOST=$(oc get route frontend -n "${NAMESPACE}" -o jsonpath='{.spec.host}' 2>/dev/null || echo "frontend-${NAMESPACE}.${CLUSTER_DOMAIN}")

                # --- Create simon-casino-ui client (public, for React Dashboard SSO) ---
                echo "  Creating 'simon-casino-ui' client (public, for dashboard SSO)..."
                curl -sk -X POST "${KC_REALM_API}/clients" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"clientId\": \"simon-casino-ui\",
                        \"name\": \"Simon Casino Resort Dashboard\",
                        \"enabled\": true,
                        \"publicClient\": true,
                        \"standardFlowEnabled\": true,
                        \"directAccessGrantsEnabled\": false,
                        \"rootUrl\": \"https://${FRONTEND_HOST}\",
                        \"redirectUris\": [\"https://${FRONTEND_HOST}/*\"],
                        \"webOrigins\": [\"https://${FRONTEND_HOST}\"],
                        \"attributes\": {
                            \"pkce.code.challenge.method\": \"S256\"
                        }
                    }" 2>/dev/null > /dev/null
                echo "    done"

                # --- Create mongodb-tool client (confidential, token exchange target) ---
                echo "  Creating 'mongodb-tool' client (confidential, for token exchange)..."
                curl -sk -X POST "${KC_REALM_API}/clients" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"clientId\": \"mongodb-tool\",
                        \"name\": \"MongoDB MCP Tool\",
                        \"enabled\": true,
                        \"publicClient\": false,
                        \"serviceAccountsEnabled\": true,
                        \"standardFlowEnabled\": false,
                        \"directAccessGrantsEnabled\": false,
                        \"attributes\": {
                            \"oauth2.device.authorization.grant.enabled\": \"false\"
                        }
                    }" 2>/dev/null > /dev/null
                echo "    done"

                # --- Create demo users ---
                # alice: Senior Marketing Exec (sees all data incl. platinum)
                # bob:   Junior Marketing Associate (platinum filtered out)
                # admin: Platform admin
                # demo-user: Dashboard SSO user
                echo "  Creating demo users..."
                for KC_USER_DATA in "alice:alice:Alice:Chen:Senior Marketing Executive" "bob:bob:Bob:Santos:Junior Marketing Associate" "admin:admin:Admin:User:Platform Administrator" "demo-user:password:Demo:User:Dashboard User"; do
                    KC_UNAME=$(echo "$KC_USER_DATA" | cut -d: -f1)
                    KC_UPASS=$(echo "$KC_USER_DATA" | cut -d: -f2)
                    KC_FIRST=$(echo "$KC_USER_DATA" | cut -d: -f3)
                    KC_LAST=$(echo "$KC_USER_DATA" | cut -d: -f4)

                    curl -sk -X POST "${KC_REALM_API}/users" \
                        -H "Authorization: Bearer ${KC_TOKEN}" \
                        -H "Content-Type: application/json" \
                        -d "{
                            \"username\": \"${KC_UNAME}\",
                            \"enabled\": true,
                            \"firstName\": \"${KC_FIRST}\",
                            \"lastName\": \"${KC_LAST}\",
                            \"email\": \"${KC_UNAME}@simon-casino.example.com\",
                            \"emailVerified\": true,
                            \"credentials\": [{
                                \"type\": \"password\",
                                \"value\": \"${KC_UPASS}\",
                                \"temporary\": false
                            }]
                        }" 2>/dev/null > /dev/null

                    # Always reset password (handles case where user already existed from Helm)
                    KC_UID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                        "${KC_REALM_API}/users?username=${KC_UNAME}&exact=true" 2>/dev/null | \
                        python3 -c "import sys,json; u=json.load(sys.stdin); print(u[0]['id'] if u else '')" 2>/dev/null || echo "")
                    if [ -n "$KC_UID" ]; then
                        curl -sk -X PUT "${KC_REALM_API}/users/${KC_UID}/reset-password" \
                            -H "Authorization: Bearer ${KC_TOKEN}" \
                            -H "Content-Type: application/json" \
                            -d "{\"type\":\"password\",\"value\":\"${KC_UPASS}\",\"temporary\":false}" 2>/dev/null > /dev/null
                    fi
                    echo "    ${KC_UNAME} / ${KC_UPASS}"
                done

                # --- Create audience and permission scopes ---
                echo "  Creating scopes..."

                # mongodb-tool-aud: audience mapper so exchanged tokens include mongodb-tool audience
                curl -sk -X POST "${KC_REALM_API}/client-scopes" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"name\": \"mongodb-tool-aud\",
                        \"description\": \"Adds mongodb-tool to token audience\",
                        \"protocol\": \"openid-connect\",
                        \"attributes\": {
                            \"include.in.token.scope\": \"true\",
                            \"display.on.consent.screen\": \"false\"
                        },
                        \"protocolMappers\": [{
                            \"name\": \"mongodb-tool-audience\",
                            \"protocol\": \"openid-connect\",
                            \"protocolMapper\": \"oidc-audience-mapper\",
                            \"consentRequired\": false,
                            \"config\": {
                                \"included.client.audience\": \"mongodb-tool\",
                                \"id.token.claim\": \"false\",
                                \"access.token.claim\": \"true\"
                            }
                        }]
                    }" 2>/dev/null > /dev/null
                echo "    mongodb-tool-aud"

                # mongodb-full-access: permission scope requested during token exchange
                curl -sk -X POST "${KC_REALM_API}/client-scopes" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"name\": \"mongodb-full-access\",
                        \"description\": \"Full access permission for MongoDB MCP\",
                        \"protocol\": \"openid-connect\",
                        \"attributes\": {
                            \"include.in.token.scope\": \"true\",
                            \"display.on.consent.screen\": \"false\"
                        }
                    }" 2>/dev/null > /dev/null
                echo "    mongodb-full-access"

                # --- Enable token exchange on mongodb-tool client ---
                # Get mongodb-tool internal client ID
                MONGO_CLIENT_ID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                    "${KC_REALM_API}/clients?clientId=mongodb-tool" 2>/dev/null | \
                    python3 -c "import sys,json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')" 2>/dev/null || echo "")
                if [ -n "$MONGO_CLIENT_ID" ]; then
                    echo "  Enabling token exchange permission on mongodb-tool..."
                    # Add the audience scope as optional to simon-casino-ui
                    SCOPE_ID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                        "${KC_REALM_API}/client-scopes" 2>/dev/null | \
                        python3 -c "import sys,json; scopes=json.load(sys.stdin); print(next((s['id'] for s in scopes if s['name']=='mongodb-tool-aud'), ''))" 2>/dev/null || echo "")

                    SIMON_CLIENT_ID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                        "${KC_REALM_API}/clients?clientId=simon-casino-ui" 2>/dev/null | \
                        python3 -c "import sys,json; clients=json.load(sys.stdin); print(clients[0]['id'] if clients else '')" 2>/dev/null || echo "")

                    if [ -n "$SCOPE_ID" ] && [ -n "$SIMON_CLIENT_ID" ]; then
                        curl -sk -X PUT "${KC_REALM_API}/clients/${SIMON_CLIENT_ID}/optional-client-scopes/${SCOPE_ID}" \
                            -H "Authorization: Bearer ${KC_TOKEN}" 2>/dev/null
                        echo "    mongodb-tool-aud added as optional scope to simon-casino-ui"
                    fi
                fi

                # --- Create realm roles ---
                echo "  Creating realm roles..."
                for ROLE_DEF in "kagenti-viewer:View agents and tools in KAgenti UI" "platinum-access:Access to platinum-tier customer data"; do
                    ROLE_NAME=${ROLE_DEF%%:*}; ROLE_DESC=${ROLE_DEF#*:}
                    curl -sk -X POST "${KC_REALM_API}/roles" \
                        -H "Authorization: Bearer ${KC_TOKEN}" \
                        -H "Content-Type: application/json" \
                        -d "{\"name\":\"${ROLE_NAME}\",\"description\":\"${ROLE_DESC}\"}" 2>/dev/null > /dev/null
                    echo "    ${ROLE_NAME}"
                done

                # --- Assign roles to users ---
                echo "  Assigning roles..."
                ADMIN_ROLE=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" "${KC_REALM_API}/roles/admin" 2>/dev/null)
                VIEWER_ROLE=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" "${KC_REALM_API}/roles/kagenti-viewer" 2>/dev/null)
                PLAT_ROLE=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" "${KC_REALM_API}/roles/platinum-access" 2>/dev/null)

                # All users get admin + kagenti-viewer (required to use KAgenti UI)
                for KC_ROLE_USER in alice bob admin demo-user; do
                    KC_ROLE_UID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                        "${KC_REALM_API}/users?username=${KC_ROLE_USER}&exact=true" 2>/dev/null | \
                        python3 -c "import sys,json; u=json.load(sys.stdin); print(u[0]['id'] if u else '')" 2>/dev/null || echo "")
                    if [ -n "$KC_ROLE_UID" ]; then
                        curl -sk -X POST "${KC_REALM_API}/users/${KC_ROLE_UID}/role-mappings/realm" \
                            -H "Authorization: Bearer ${KC_TOKEN}" \
                            -H "Content-Type: application/json" \
                            -d "[${ADMIN_ROLE},${VIEWER_ROLE}]" 2>/dev/null > /dev/null
                        echo "    ${KC_ROLE_USER}: admin, kagenti-viewer"
                    fi
                done

                # Only alice gets platinum-access
                ALICE_ID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                    "${KC_REALM_API}/users?username=alice&exact=true" 2>/dev/null | \
                    python3 -c "import sys,json; u=json.load(sys.stdin); print(u[0]['id'] if u else '')" 2>/dev/null || echo "")
                if [ -n "$ALICE_ID" ]; then
                    curl -sk -X POST "${KC_REALM_API}/users/${ALICE_ID}/role-mappings/realm" \
                        -H "Authorization: Bearer ${KC_TOKEN}" \
                        -H "Content-Type: application/json" \
                        -d "[${PLAT_ROLE}]" 2>/dev/null > /dev/null
                    echo "    alice: + platinum-access"
                fi
                echo "    (bob does NOT have platinum-access — data will be filtered)"

                echo ""
                echo "  Keycloak realm '${KC_REALM}' configured:"
                echo "    Clients: simon-casino-ui (public), mongodb-tool (confidential)"
                echo "    Users: alice/alice (platinum), bob/bob (no platinum), admin/admin, demo-user/password"
                echo "    Roles: admin, kagenti-viewer (all users), platinum-access (alice only)"
                echo "    Scopes: mongodb-tool-aud, mongodb-full-access"
            fi

            KAGENTI_ROUTE=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")

            echo ""
            echo "KAgenti deployed successfully!"
            [ -n "$KAGENTI_ROUTE" ] && echo "  KAgenti UI: https://${KAGENTI_ROUTE}"
            [ -n "$KEYCLOAK_ROUTE" ] && echo "  Keycloak:   https://${KEYCLOAK_ROUTE}/admin/${KC_REALM}/console/"
            echo "  Default credentials: admin / admin"
        fi
    fi
fi

echo ""

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
if [ -n "$KAGENTI_ROUTE" ]; then
    echo "KAgenti:"
    echo "  UI:       https://${KAGENTI_ROUTE}"
    echo "  Keycloak: https://${KEYCLOAK_ROUTE}"
    echo ""
fi
echo "Useful commands:"
echo "  ./reset-demo.sh          # Clean slate (remove generated campaigns)"
echo "  ./build-and-push.sh      # Rebuild container images after code changes"
echo ""

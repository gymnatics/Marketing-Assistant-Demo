#!/bin/bash
set -e

DEFAULT_NS="0-marketing-assistant-demo"
NAMESPACE="${NAMESPACE:-}"
MODEL_NS="${MODEL_NS:-}"
DEV_NS="${DEV_NS:-}"
PROD_NS="${PROD_NS:-}"
OVERLAY="${OVERLAY:-k8s/overlays/dev}"

echo "=========================================="
echo "AI Campaign Manager - Deploy to OpenShift"
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

# --- Vertical selection ---
echo "Available verticals:"
VERTICAL_DIR="config/verticals"
IDX=1
declare -a VERTICAL_FILES=()
for VFILE in "$VERTICAL_DIR"/*.json; do
    VNAME=$(python3 -c "import json; print(json.load(open('$VFILE')).get('brand',{}).get('company_name', '$(basename $VFILE .json)'))" 2>/dev/null || basename "$VFILE" .json)
    VID=$(basename "$VFILE" .json)
    VERTICAL_FILES+=("$VFILE")
    echo "  [$IDX] $VNAME ($VID)"
    IDX=$((IDX + 1))
done
VERTICAL_CONFIG="${VERTICAL_CONFIG:-}"
if [ -z "$VERTICAL_CONFIG" ]; then
    read -p "Select vertical [1]: " VERT_CHOICE
    VERT_CHOICE=${VERT_CHOICE:-1}
    VERT_IDX=$((VERT_CHOICE - 1))
    VERTICAL_CONFIG="${VERTICAL_FILES[$VERT_IDX]}"
fi
echo "Vertical: $VERTICAL_CONFIG"
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
    echo "  (1) RHOAI Dashboard UI (manual — creates data connections automatically)"
    echo "  (2) setup-models.sh (one command — sets up MinIO, downloads, and serves all 3 models)"
    echo "  (3) RHOAI-Toolkit scripts (manual — step by step)"
    echo "  (4) Kustomize manifests (requires pre-configured S3 data connections)"
    echo "  (s) Skip for now"
    read -p "Choose [1/2/3/4/s]: " MODEL_CHOICE

    if [ "$MODEL_CHOICE" = "2" ]; then
        echo ""
        echo "Running setup-models.sh (MinIO + download + serve)..."
        if [ -f "./setup-models.sh" ]; then
            MODEL_NS="$MODEL_NS" ./setup-models.sh
        else
            echo "  setup-models.sh not found in current directory."
            echo "  Run it manually: MODEL_NS=$MODEL_NS ./setup-models.sh"
        fi
        echo ""

    elif [ "$MODEL_CHOICE" = "4" ]; then
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

    elif [ "$MODEL_CHOICE" = "3" ]; then
        echo ""
        echo "Run RHOAI-Toolkit manually:"
        echo "  cd /path/to/Openshift-installation"
        echo "  export NAMESPACE=model-storage"
        echo "  export MINIO_NAMESPACE=model-storage"
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

# Auto-detect model routes and names by pattern (skip guardrails models)
_find_model_info() {
    local pattern="$1"
    for isvc in $(oc get inferenceservice -n "$MODEL_NS" --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null); do
        if echo "$isvc" | grep -qi "$pattern" && ! echo "$isvc" | grep -qi "guardrail\|detector"; then
            local route=$(oc get route "$isvc" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || \
                          oc get route "${isvc}-predictor" -n "$MODEL_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
            if [ -n "$route" ]; then
                echo "$isvc $route"
                return
            fi
        fi
    done
    echo ""
}

CODE_INFO=$(_find_model_info "coder\|code")
LANG_INFO=$(_find_model_info "qwen3\|lang")
IMG_INFO=$(_find_model_info "flux\|omni")

CODE_NAME=$(echo "$CODE_INFO" | awk '{print $1}')
CODE_ROUTE=$(echo "$CODE_INFO" | awk '{print $2}')
LANG_NAME=$(echo "$LANG_INFO" | awk '{print $1}')
LANG_ROUTE=$(echo "$LANG_INFO" | awk '{print $2}')
IMG_NAME=$(echo "$IMG_INFO" | awk '{print $1}')
IMG_ROUTE=$(echo "$IMG_INFO" | awk '{print $2}')

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

# Add model names (match served model names, not hardcoded defaults)
[ -n "$CODE_NAME" ] && echo "  CODE_MODEL_NAME: \"${CODE_NAME}\"" >> k8s/overlays/dev/configmap-patch.yaml
[ -n "$LANG_NAME" ] && echo "  LANG_MODEL_NAME: \"${LANG_NAME}\"" >> k8s/overlays/dev/configmap-patch.yaml
[ -n "$IMG_NAME" ] && echo "  IMAGEGEN_MODEL_NAME: \"${IMG_NAME}\"" >> k8s/overlays/dev/configmap-patch.yaml

# Add vertical config identifier
VERTICAL_ID=$(basename "$VERTICAL_CONFIG" .json)
echo "  VERTICAL_CONFIG: \"${VERTICAL_ID}\"" >> k8s/overlays/dev/configmap-patch.yaml
echo "  Vertical: ${VERTICAL_ID}"

echo "  ConfigMap patch generated"

# Copy config patch to internal-build overlay too (used when building in-cluster)
cp k8s/overlays/dev/configmap-patch.yaml k8s/overlays/internal-build/configmap-patch.yaml 2>/dev/null || true

# Update Kustomize namespace to match
sed -i.bak "s/^namespace: .*/namespace: ${NAMESPACE}/" k8s/base/kustomization.yaml k8s/overlays/dev/kustomization.yaml k8s/overlays/internal-build/kustomization.yaml 2>/dev/null
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
# Step 3b: Build images (optional)
################################################################################
echo "--- Step 3b: Image Build ---"
echo ""
echo "Where should container images come from?"
echo "  (1) Use pre-built images from quay.io (default)"
echo "  (2) Build from GitHub in OpenShift → internal registry (keeps quay untouched)"
echo "  (3) Build from GitHub in OpenShift → push to quay.io (updates quay images)"
echo "  (4) Use existing internal registry images (already built on this cluster, skip build)"
read -p "Choose [1/2/3/4]: " BUILD_CHOICE
BUILD_CHOICE=${BUILD_CHOICE:-1}

if [ "$BUILD_CHOICE" = "4" ]; then
    OVERLAY="k8s/overlays/internal-build"
    sed -i.bak "s/^namespace: .*/namespace: ${NAMESPACE}/" k8s/overlays/internal-build/kustomization.yaml 2>/dev/null
    rm -f k8s/overlays/internal-build/kustomization.yaml.bak 2>/dev/null
    echo "  Using existing internal registry images (no build)"
fi

if [ "$BUILD_CHOICE" = "2" ] || [ "$BUILD_CHOICE" = "3" ]; then

    # Branch selection (shared by options 2 and 3)
    GIT_REPO="https://github.com/gymnatics/Marketing-Assistant-Demo.git"
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
    echo ""
    echo "  Available branches:"
    git ls-remote --heads "$GIT_REPO" 2>/dev/null | sed 's|.*refs/heads/||' | while read -r b; do
        if [ "$b" = "$CURRENT_BRANCH" ]; then
            echo "    * $b (current)"
        else
            echo "      $b"
        fi
    done
    echo ""
    read -p "  Build from branch [$CURRENT_BRANCH]: " BUILD_BRANCH
    BUILD_BRANCH="${BUILD_BRANCH:-$CURRENT_BRANCH}"
    echo "  Building from branch: $BUILD_BRANCH"

    if [ "$BUILD_CHOICE" = "2" ]; then
        # Option 2: Build → internal registry
        OVERLAY="k8s/overlays/internal-build"
        echo "  Target: internal OpenShift registry (ImageStream)"

        echo "  Applying ImageStream and BuildConfigs..."
        oc apply -f k8s/openshift/imagestream.yaml -n "$NAMESPACE" 2>/dev/null
        sed "s|ref: main|ref: ${BUILD_BRANCH}|g" k8s/openshift/buildconfigs-internal.yaml | \
            oc apply -n "$NAMESPACE" -f - 2>&1 | grep -E "created|configured|unchanged"
    else
        # Option 3: Build → quay.io
        echo "  Target: quay.io (requires quay-push-secret in namespace)"

        # Check for push secret
        if ! oc get secret quay-push-secret -n "$NAMESPACE" &>/dev/null; then
            echo ""
            echo "  WARNING: quay-push-secret not found in $NAMESPACE."
            echo "  Create it with: oc create secret docker-registry quay-push-secret \\"
            echo "    --docker-server=quay.io --docker-username=<user> --docker-password=<token> -n $NAMESPACE"
            echo ""
            read -p "  Continue anyway? (y/N): " CONTINUE_QUAY
            if [ "$CONTINUE_QUAY" != "y" ] && [ "$CONTINUE_QUAY" != "Y" ]; then
                echo "  Skipping build."
                BUILD_CHOICE="1"
            fi
        fi

        if [ "$BUILD_CHOICE" = "3" ]; then
            echo "  Applying BuildConfigs (quay.io output)..."
            sed "s|ref: main|ref: ${BUILD_BRANCH}|g" k8s/openshift/buildconfigs.yaml | \
                oc apply -n "$NAMESPACE" -f - 2>&1 | grep -E "created|configured|unchanged"
        fi
    fi

    if [ "$BUILD_CHOICE" = "2" ] || [ "$BUILD_CHOICE" = "3" ]; then
        echo ""
        echo "  Starting builds (this takes 5-15 minutes)..."
        BUILDS=(mongodb-mcp imagegen-mcp event-hub creative-producer customer-analyst delivery-manager campaign-director policy-guardian campaign-api campaign-landing frontend)
        for BC in "${BUILDS[@]}"; do
            oc start-build "$BC" -n "$NAMESPACE" 2>/dev/null && echo "    Started $BC"
        done

        echo ""
        echo "  Waiting for builds to complete..."
        ALL_DONE=false
        TIMEOUT=900
        ELAPSED=0
        while [ "$ALL_DONE" = "false" ] && [ "$ELAPSED" -lt "$TIMEOUT" ]; do
            sleep 15
            ELAPSED=$((ELAPSED + 15))
            RUNNING=$(oc get builds -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "Running\|Pending\|New" || true)
            FAILED=$(oc get builds -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "Failed\|Error" || true)
            COMPLETE=$(oc get builds -n "$NAMESPACE" --no-headers 2>/dev/null | grep -c "Complete" || true)
            echo "    [${ELAPSED}s] Running: $RUNNING  Complete: $COMPLETE  Failed: $FAILED"
            if [ "$RUNNING" = "0" ]; then
                ALL_DONE=true
            fi
        done

        if [ "$FAILED" != "0" ] && [ "$FAILED" != "" ]; then
            echo ""
            echo "  WARNING: Some builds failed:"
            oc get builds -n "$NAMESPACE" --no-headers 2>/dev/null | grep -E "Failed|Error"
            echo ""
        fi
        echo "  Builds complete."

        if [ "$BUILD_CHOICE" = "2" ]; then
            # Update internal-build overlay with correct namespace
            sed -i.bak "s/^namespace: .*/namespace: ${NAMESPACE}/" k8s/overlays/internal-build/kustomization.yaml 2>/dev/null
            rm -f k8s/overlays/internal-build/kustomization.yaml.bak 2>/dev/null
        fi
    fi
else
    echo "  Using pre-built quay.io images"
fi
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
    echo "KAgenti Helm releases found — skipping platform install (Steps 6a/6b)."
    echo "  Running post-install config (Steps 6c/6d)..."
    KAGENTI_ROUTE=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
else
    read -p "Deploy KAgenti platform (agent discovery + zero-trust auth)? (y/N): " DEPLOY_KAGENTI
    if [ "$DEPLOY_KAGENTI" = "y" ] || [ "$DEPLOY_KAGENTI" = "Y" ]; then

        DOMAIN="${CLUSTER_DOMAIN}"

        echo ""
        echo "--- Step 6a: Clone and patch upstream KAgenti ---"

        KAGENTI_CACHE="${HOME}/.cache/kagenti"
        KAGENTI_GITHUB_URL="https://github.com/kagenti/kagenti.git"
        KAGENTI_TAG="${KAGENTI_TAG:-}"

        if [ -d "$KAGENTI_CACHE/.git" ]; then
            echo "  Updating cached KAgenti repo..."
            git -C "$KAGENTI_CACHE" fetch --tags 2>/dev/null || true
        else
            echo "  Cloning KAgenti repo..."
            rm -rf "$KAGENTI_CACHE" 2>/dev/null
            git clone "$KAGENTI_GITHUB_URL" "$KAGENTI_CACHE" 2>/dev/null
        fi

        if [ -z "$KAGENTI_TAG" ]; then
            KAGENTI_TAG=$(git -C "$KAGENTI_CACHE" tag --sort=-v:refname | head -1 | sed 's/^v//')
        fi
        echo "  KAgenti version: v${KAGENTI_TAG}"
        git -C "$KAGENTI_CACHE" checkout "v${KAGENTI_TAG}" 2>/dev/null || git -C "$KAGENTI_CACHE" checkout main 2>/dev/null

        # Patch 1: Set agentNamespaces to our app namespace (default is team1/team2)
        echo "  Patching agentNamespaces → ${NAMESPACE}"
        python3 -c "
import pathlib, re
f = pathlib.Path('${KAGENTI_CACHE}/charts/kagenti/values.yaml')
text = f.read_text()
text = re.sub(r'agentNamespaces:\n- team1\n- team2', 'agentNamespaces:\n- ${NAMESPACE}', text)
f.write_text(text)
"

        # Patch 2: Change transparentPort from 8082 to 15006 (avoids collision with our agent containers)
        echo "  Patching transparentPort → 15006"
        python3 -c "
import pathlib, re
for p in pathlib.Path('${KAGENTI_CACHE}/charts').rglob('values.yaml'):
    text = p.read_text()
    if 'transparentPort' in text:
        text = re.sub(r'transparentPort:\s*8082', 'transparentPort: 15006', text)
        p.write_text(text)
"

        # Patch 3: Add keycloak service alias for OpenShift
        # The RHBK operator creates 'keycloak-service' but the kagenti-operator constructs
        # 'keycloak.{namespace}.svc.cluster.local' for admin token requests. This ExternalName
        # service bridges the gap.
        echo "  Adding Keycloak service alias (keycloak → keycloak-service)"
        cat > "${KAGENTI_CACHE}/charts/kagenti-deps/templates/keycloak-alias-svc.yaml" << 'KCALIAS'
{{- if .Values.openshift }}
apiVersion: v1
kind: Service
metadata:
  name: keycloak
  namespace: {{ .Values.keycloak.namespace }}
  labels:
    {{- include "kagenti.labels" . | nindent 4 }}
spec:
  type: ExternalName
  externalName: keycloak-service.{{ .Values.keycloak.namespace }}.svc.cluster.local
{{- end }}
KCALIAS

        # Patch 4: Grant operator SA the kagenti-authbridge SCC (needed to create SCC RoleBindings in agent namespaces)
        echo "  Adding operator SCC ClusterRoleBinding"
        cat > "${KAGENTI_CACHE}/charts/kagenti/templates/operator-scc-crb.yaml" << 'SCCCRB'
{{- if .Values.openshift }}
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kagenti-operator-authbridge-scc
  labels:
    {{- include "kagenti.labels" . | nindent 4 }}
subjects:
- kind: ServiceAccount
  name: controller-manager
  namespace: {{ .Release.Namespace }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:kagenti-authbridge
{{- end }}
SCCCRB

        echo "  ✓ All patches applied"

        echo ""
        echo "--- Step 6b: Running upstream KAgenti installer ---"
        echo ""

        bash "${KAGENTI_CACHE}/scripts/ocp/setup-kagenti.sh" \
            --kagenti-repo "${KAGENTI_CACHE}" \
            --with-mcp-gateway \
            --skip-mlflow \
            --skip-ovn-patch

        KAGENTI_ROUTE=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
        KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")
    fi
fi

# Steps 6c/6d run for both fresh installs and re-runs
if [ -n "$KAGENTI_ROUTE" ] || [ "$KAGENTI_INSTALLED" -ge 1 ]; then
    KEYCLOAK_ROUTE=${KEYCLOAK_ROUTE:-$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}' 2>/dev/null || echo "")}
    KAGENTI_ROUTE=${KAGENTI_ROUTE:-$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}' 2>/dev/null || echo "")}

    echo ""
    echo "--- Step 6c: App-specific KAgenti configuration ---"

    echo "  Labeling namespace for KAgenti discovery..."
    oc label namespace "${NAMESPACE}" kagenti-enabled=true shared-gateway-access=true --overwrite 2>/dev/null || true

    echo "  Applying KAgenti manifests..."
    sed "s/NAMESPACE_PLACEHOLDER/${NAMESPACE}/" k8s/kagenti/crb.yaml | oc apply -f - 2>/dev/null || true
    oc apply -k k8s/kagenti/ -n "${NAMESPACE}" 2>&1 | grep -E "created|configured|unchanged" | head -10

    if oc api-resources --api-group=agent.kagenti.dev 2>/dev/null | grep -q agentruntime; then
        echo "  Applying AgentRuntime CRDs..."
        oc apply -f k8s/kagenti/agentruntime.yaml -n "${NAMESPACE}" 2>&1 | grep -E "created|configured|unchanged" | head -5
    fi

    if [ -n "$KEYCLOAK_ROUTE" ]; then
        echo "  Patching AuthBridge config with Keycloak URLs..."
        oc patch configmap authbridge-config -n "${NAMESPACE}" --type=merge \
            -p "{\"data\":{\"ISSUER\":\"https://${KEYCLOAK_ROUTE}/realms/kagenti\",\"KEYCLOAK_URL\":\"http://keycloak-service.keycloak.svc:8080\",\"TOKEN_URL\":\"http://keycloak-service.keycloak.svc:8080/realms/kagenti/protocol/openid-connect/token\"}}" 2>/dev/null || true

        echo "  Patching app ConfigMap with Keycloak URL for SSO..."
        oc patch configmap marketing-assistant-config -n "${NAMESPACE}" --type=merge \
            -p "{\"data\":{\"KEYCLOAK_URL\":\"https://${KEYCLOAK_ROUTE}\"}}" 2>/dev/null || true

        echo "  Creating frontend-keycloak-config ConfigMap..."
        oc create configmap frontend-keycloak-config -n "${NAMESPACE}" \
            --from-literal="keycloak-config.js=window.__KEYCLOAK_URL__ = \"https://${KEYCLOAK_ROUTE}\";
window.__KEYCLOAK_REALM__ = \"kagenti\";
window.__KEYCLOAK_CLIENT_ID__ = \"demo-ui\";" \
            --dry-run=client -o yaml | oc apply -f - 2>/dev/null || true

        echo "  Restarting frontend to pick up Keycloak config..."
        oc rollout restart deployment/frontend -n "${NAMESPACE}" 2>/dev/null || true
    fi

            echo ""
            echo "--- Step 6d: App-specific Keycloak configuration ---"
            echo ""
            KC_REALM="kagenti"

            KEYCLOAK_ADMIN_USER=$(oc get secret keycloak-initial-admin -n keycloak -o go-template='{{.data.username | base64decode}}' 2>/dev/null || echo "admin")
            KEYCLOAK_ADMIN_PASS=$(oc get secret keycloak-initial-admin -n keycloak -o go-template='{{.data.password | base64decode}}' 2>/dev/null || echo "admin")

            KC_TOKEN=""
            if [ -n "$KEYCLOAK_ROUTE" ]; then
                KC_TOKEN=$(curl -sk -X POST "https://${KEYCLOAK_ROUTE}/realms/master/protocol/openid-connect/token" \
                    -d "client_id=admin-cli&username=${KEYCLOAK_ADMIN_USER}&password=${KEYCLOAK_ADMIN_PASS}&grant_type=password" 2>/dev/null | \
                    python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
            fi

            if [ -z "$KC_TOKEN" ]; then
                echo "  WARNING: Could not obtain Keycloak admin token. Skipping app-specific config."
            else
                KC_REALM_API="https://${KEYCLOAK_ROUTE}/admin/realms/${KC_REALM}"
                FRONTEND_HOST=$(oc get routes -n "${NAMESPACE}" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.to.name}{" "}{.spec.host}{"\n"}{end}' 2>/dev/null | grep "frontend" | head -1 | awk '{print $3}')
                FRONTEND_HOST=${FRONTEND_HOST:-"frontend-${NAMESPACE}.${CLUSTER_DOMAIN}"}

                # demo-ui client (public, for React Dashboard SSO — separate from KAgenti UI)
                echo "  Creating 'demo-ui' client..."
                curl -sk -X POST "${KC_REALM_API}/clients" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"clientId\": \"demo-ui\",
                        \"name\": \"Marketing Assistant Dashboard\",
                        \"enabled\": true,
                        \"publicClient\": true,
                        \"standardFlowEnabled\": true,
                        \"directAccessGrantsEnabled\": false,
                        \"rootUrl\": \"https://${FRONTEND_HOST}\",
                        \"redirectUris\": [\"https://${FRONTEND_HOST}/*\"],
                        \"webOrigins\": [\"https://${FRONTEND_HOST}\"],
                        \"attributes\": {\"pkce.code.challenge.method\": \"S256\"}
                    }" 2>/dev/null > /dev/null
                echo "    done"

                # Reset demo user passwords (upstream installer may use different defaults)
                echo "  Resetting demo user passwords..."
                for KC_USER_DATA in "alice:alice:Alice:Chen" "bob:bob:Bob:Santos" "demo-user:password:Demo:User"; do
                    KC_UNAME=$(echo "$KC_USER_DATA" | cut -d: -f1)
                    KC_UPASS=$(echo "$KC_USER_DATA" | cut -d: -f2)
                    KC_FIRST=$(echo "$KC_USER_DATA" | cut -d: -f3)
                    KC_LAST=$(echo "$KC_USER_DATA" | cut -d: -f4)

                    # Create user if not exists (upstream creates alice/bob but not demo-user)
                    curl -sk -X POST "${KC_REALM_API}/users" \
                        -H "Authorization: Bearer ${KC_TOKEN}" \
                        -H "Content-Type: application/json" \
                        -d "{\"username\":\"${KC_UNAME}\",\"enabled\":true,\"firstName\":\"${KC_FIRST}\",\"lastName\":\"${KC_LAST}\",\"email\":\"${KC_UNAME}@demo.example.com\",\"emailVerified\":true,\"credentials\":[{\"type\":\"password\",\"value\":\"${KC_UPASS}\",\"temporary\":false}]}" 2>/dev/null > /dev/null

                    KC_UID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                        "${KC_REALM_API}/users?username=${KC_UNAME}&exact=true" 2>/dev/null | \
                        python3 -c "import sys,json; u=json.load(sys.stdin); print(u[0]['id'] if u else '')" 2>/dev/null || echo "")
                    if [ -n "$KC_UID" ]; then
                        curl -sk -X PUT "${KC_REALM_API}/users/${KC_UID}/reset-password" \
                            -H "Authorization: Bearer ${KC_TOKEN}" -H "Content-Type: application/json" \
                            -d "{\"type\":\"password\",\"value\":\"${KC_UPASS}\",\"temporary\":false}" 2>/dev/null > /dev/null
                    fi
                    echo "    ${KC_UNAME} / ${KC_UPASS}"
                done

                # platinum-access role (app-specific — controls MongoDB MCP data filtering)
                echo "  Creating 'platinum-access' role..."
                curl -sk -X POST "${KC_REALM_API}/roles" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d '{"name":"platinum-access","description":"Access to platinum-tier customer data"}' 2>/dev/null > /dev/null

                # Assign platinum-access to alice only
                PLAT_ROLE=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" "${KC_REALM_API}/roles/platinum-access" 2>/dev/null)
                ALICE_ID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                    "${KC_REALM_API}/users?username=alice&exact=true" 2>/dev/null | \
                    python3 -c "import sys,json; u=json.load(sys.stdin); print(u[0]['id'] if u else '')" 2>/dev/null || echo "")
                if [ -n "$ALICE_ID" ] && [ -n "$PLAT_ROLE" ]; then
                    curl -sk -X POST "${KC_REALM_API}/users/${ALICE_ID}/role-mappings/realm" \
                        -H "Authorization: Bearer ${KC_TOKEN}" -H "Content-Type: application/json" \
                        -d "[${PLAT_ROLE}]" 2>/dev/null > /dev/null
                    echo "    alice: platinum-access"
                fi
                echo "    (bob does NOT have platinum-access — data will be filtered)"

                echo ""
                echo "  App Keycloak config done:"
                echo "    Client: demo-ui (public, dashboard SSO)"
                echo "    Users: alice/alice (platinum), bob/bob (no platinum), demo-user/password"
                echo "    Role: platinum-access (alice only)"
                echo "    Note: realm, agent clients, audience scopes, and roles (admin, kagenti-viewer)"
                echo "          are managed by the upstream KAgenti installer"
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
# Restart pods (if config changed, e.g., vertical switch)
################################################################################
echo ""
read -p "Restart all app pods to pick up latest config? (y/N): " RESTART_PODS
if [ "$RESTART_PODS" = "y" ] || [ "$RESTART_PODS" = "Y" ]; then
    echo "Restarting app deployments..."
    for DEPLOY in campaign-api campaign-director creative-producer customer-analyst delivery-manager policy-guardian mongodb-mcp imagegen-mcp event-hub frontend; do
        oc rollout restart deployment/$DEPLOY -n $NAMESPACE 2>/dev/null && echo "  $DEPLOY"
    done
    echo ""
    echo "Waiting for rollouts..."
    for DEPLOY in campaign-api campaign-director creative-producer customer-analyst delivery-manager policy-guardian mongodb-mcp event-hub frontend; do
        oc rollout status deployment/$DEPLOY -n $NAMESPACE --timeout=60s 2>/dev/null || true
    done
    echo ""
    echo "Re-seeding MongoDB with new vertical data..."
    sleep 3
    oc exec deployment/mongodb-mcp -n $NAMESPACE -- env MONGODB_URI=mongodb://mongodb:27017 python3 seed_data.py 2>/dev/null || echo "  Seed failed (try manually later)"
fi

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

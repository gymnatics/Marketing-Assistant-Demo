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
for NS_TO_CREATE in "$NAMESPACE" "$MODEL_NS" "$DEV_NS" "$PROD_NS"; do
    if [ -n "$NS_TO_CREATE" ]; then
        oc create namespace "$NS_TO_CREATE" --dry-run=client -o yaml | oc apply -f - 2>/dev/null || true
    fi
done
echo "  $NAMESPACE, $MODEL_NS, $DEV_NS, $PROD_NS"
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
        if oc apply -k k8s/models/ -n "$MODEL_NS" 2>&1 | tee /tmp/model-apply.log | grep -E "created|configured|unchanged"; then
            echo ""
        else
            echo ""
            echo "WARNING: Model manifest apply had errors:"
            cat /tmp/model-apply.log
            echo ""
            echo "This usually means RHOAI is not installed (missing InferenceService/ServingRuntime CRDs)"
            echo "or the namespace '$MODEL_NS' does not exist."
            echo "You can deploy models manually later. Continuing..."
            echo ""
        fi
        rm -f /tmp/model-apply.log
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

        # Check for existing cert-manager (KAgenti installs its own)
        CERTMGR_COUNT=$(oc get deployment -n cert-manager --no-headers 2>/dev/null | wc -l | tr -dc '0-9')
        CERTMGR_COUNT=${CERTMGR_COUNT:-0}
        if [ "$CERTMGR_COUNT" -ge 1 ]; then
            echo "WARNING: cert-manager detected in cert-manager namespace."
            echo "KAgenti installs its own cert-manager. You may need to remove the existing one."
            read -p "Continue anyway? (y/N): " CONTINUE_CERTMGR
            if [ "$CONTINUE_CERTMGR" != "y" ] && [ "$CONTINUE_CERTMGR" != "Y" ]; then
                echo "Skipping KAgenti deployment. Remove cert-manager first, then re-run."
                DEPLOY_KAGENTI="n"
            fi
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

            # Install kagenti-deps (SPIRE, Keycloak, Istio, cert-manager)
            echo "  Installing kagenti-deps..."
            helm install --create-namespace -n kagenti-system kagenti-deps \
                oci://ghcr.io/kagenti/kagenti/kagenti-deps \
                --version "${KAGENTI_TAG}" \
                --set spire.trustDomain="${DOMAIN}" \
                --wait --timeout 10m 2>&1 | tail -3

            # Install MCP Gateway
            echo "  Installing MCP Gateway..."
            GATEWAY_TAG=$(skopeo list-tags docker://ghcr.io/kagenti/charts/mcp-gateway 2>/dev/null | python3 -c "import sys,json; tags=json.load(sys.stdin)['Tags']; print(tags[-1])" 2>/dev/null || echo "0.4.0")
            helm install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway \
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

            # Create keycloak-admin-secret in app namespace
            echo "  Creating keycloak-admin-secret in ${NAMESPACE}..."
            oc create secret generic keycloak-admin-secret -n "${NAMESPACE}" \
                --from-literal=KEYCLOAK_ADMIN_USERNAME=admin \
                --from-literal=KEYCLOAK_ADMIN_PASSWORD=admin \
                --dry-run=client -o yaml | oc apply -f - 2>/dev/null

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
            KEYCLOAK_ADMIN_USER="admin"
            KEYCLOAK_ADMIN_PASS="admin"
            KC_REALM="kagenti"

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
                    }" 2>/dev/null | head -c 0
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
                    }" 2>/dev/null | head -c 0
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
                        }" 2>/dev/null | head -c 0
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
                    }" 2>/dev/null | head -c 0
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
                    }" 2>/dev/null | head -c 0
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

                # --- Create realm role and assign to alice ---
                echo "  Creating 'platinum-access' realm role..."
                curl -sk -X POST "${KC_REALM_API}/roles" \
                    -H "Authorization: Bearer ${KC_TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "{
                        \"name\": \"platinum-access\",
                        \"description\": \"Access to platinum-tier customer data\"
                    }" 2>/dev/null | head -c 0

                # Assign platinum-access role to alice
                ALICE_ID=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                    "${KC_REALM_API}/users?username=alice&exact=true" 2>/dev/null | \
                    python3 -c "import sys,json; users=json.load(sys.stdin); print(users[0]['id'] if users else '')" 2>/dev/null || echo "")
                if [ -n "$ALICE_ID" ]; then
                    ROLE_JSON=$(curl -sk -H "Authorization: Bearer ${KC_TOKEN}" \
                        "${KC_REALM_API}/roles/platinum-access" 2>/dev/null)
                    curl -sk -X POST "${KC_REALM_API}/users/${ALICE_ID}/role-mappings/realm" \
                        -H "Authorization: Bearer ${KC_TOKEN}" \
                        -H "Content-Type: application/json" \
                        -d "[${ROLE_JSON}]" 2>/dev/null | head -c 0
                    echo "    platinum-access role assigned to alice"
                else
                    echo "    WARNING: Could not find alice user to assign role"
                fi
                echo "    (bob does NOT have this role — platinum data will be filtered)"

                echo ""
                echo "  Keycloak realm '${KC_REALM}' configured:"
                echo "    Clients: simon-casino-ui (public), mongodb-tool (confidential)"
                echo "    Users: alice/alice (platinum-access), bob/bob (no platinum), admin/admin, demo-user/password"
                echo "    Roles: platinum-access (assigned to alice only)"
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

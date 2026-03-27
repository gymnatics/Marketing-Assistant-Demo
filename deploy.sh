#!/bin/bash
set -e

NAMESPACE="0-marketing-assistant-demo"
APP_NAME="marketing-assistant"

echo "=========================================="
echo "Deploying Marketing Assistant to OpenShift"
echo "=========================================="

# Check if logged in
if ! oc whoami &> /dev/null; then
    echo "ERROR: Not logged into OpenShift. Please run 'oc login' first."
    exit 1
fi

echo "Logged in as: $(oc whoami)"
echo "Namespace: $NAMESPACE"
echo ""

# Step 1: Create ImageStream and BuildConfig
echo "[1/6] Creating ImageStream and BuildConfig..."
oc apply -f k8s/buildconfig.yaml

# Step 2: Create ServiceAccount and RBAC
echo "[2/6] Creating ServiceAccount and RBAC..."
oc apply -f k8s/serviceaccount.yaml

# Step 3: Create ConfigMap
echo "[3/6] Creating ConfigMap..."
oc apply -f k8s/configmap.yaml

# Step 4: Create Secret with model tokens
echo "[4/6] Creating Secret with model tokens..."
CODE_TOKEN=$(oc get secret default-token-qwen25-coder-32b-fp8-sa -n $NAMESPACE -o jsonpath='{.data.token}' | base64 -d)
LANG_TOKEN=$(oc get secret default-token-qwen3-32b-fp8-dynamic-sa -n $NAMESPACE -o jsonpath='{.data.token}' | base64 -d)

cat <<EOF | oc apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: marketing-assistant-secrets
  namespace: $NAMESPACE
  labels:
    app: marketing-assistant
type: Opaque
stringData:
  CODE_MODEL_TOKEN: "$CODE_TOKEN"
  LANG_MODEL_TOKEN: "$LANG_TOKEN"
EOF

# Step 5: Build the container image
echo "[5/6] Building container image (this may take a few minutes)..."
oc start-build $APP_NAME --from-dir=. --follow -n $NAMESPACE

# Step 6: Deploy the application
echo "[6/6] Deploying application..."
oc apply -f k8s/service.yaml
oc apply -f k8s/deployment.yaml
oc apply -f k8s/route.yaml

# Wait for deployment
echo ""
echo "Waiting for deployment to be ready..."
oc rollout status deployment/$APP_NAME -n $NAMESPACE --timeout=300s

# Get the route URL
ROUTE_URL=$(oc get route $APP_NAME -n $NAMESPACE -o jsonpath='{.spec.host}')

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Application URL: https://$ROUTE_URL"
echo ""
echo "To check status:"
echo "  oc get pods -n $NAMESPACE -l app=$APP_NAME"
echo ""
echo "To view logs:"
echo "  oc logs -f deployment/$APP_NAME -n $NAMESPACE"
echo ""

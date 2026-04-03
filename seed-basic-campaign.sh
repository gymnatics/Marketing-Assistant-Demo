#!/bin/bash
set -e

DEV_NS="${DEV_NS:-0-marketing-assistant-demo-dev}"
NAME="campaign-basic-preview"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=========================================="
echo "Deploying basic (pre-generated) campaign"
echo "=========================================="
echo "Namespace: $DEV_NS"
echo ""

if ! oc whoami &>/dev/null; then
    echo "Error: Not logged in to OpenShift. Run 'oc login' first."
    exit 1
fi

# Ensure namespace exists
oc create namespace "$DEV_NS" --dry-run=client -o yaml | oc apply -f - 2>/dev/null

# Create ConfigMap from HTML file
echo "Creating HTML ConfigMap..."
oc create configmap ${NAME}-html \
    --from-file=index.html="${SCRIPT_DIR}/k8s/basic-campaign.html" \
    -n "$DEV_NS" --dry-run=client -o yaml | oc apply -f -

# Create nginx config
cat <<'NGINX' | oc apply -n "$DEV_NS" -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: campaign-basic-preview-nginx
data:
  default.conf: |
    server {
        listen 8080;
        location / {
            root /usr/share/nginx/html;
            index index.html;
            add_header X-Frame-Options "";
            add_header Content-Security-Policy "";
        }
    }
NGINX

# Create Deployment
cat <<EOF | oc apply -n "$DEV_NS" -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${NAME}
  labels:
    app: ${NAME}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ${NAME}
  template:
    metadata:
      labels:
        app: ${NAME}
    spec:
      containers:
      - name: nginx
        image: nginxinc/nginx-unprivileged:alpine
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8080
        volumeMounts:
        - name: html
          mountPath: /usr/share/nginx/html
        - name: nginx-conf
          mountPath: /etc/nginx/conf.d
      volumes:
      - name: html
        configMap:
          name: ${NAME}-html
      - name: nginx-conf
        configMap:
          name: ${NAME}-nginx
EOF

# Create Service
cat <<EOF | oc apply -n "$DEV_NS" -f -
apiVersion: v1
kind: Service
metadata:
  name: ${NAME}
spec:
  selector:
    app: ${NAME}
  ports:
  - port: 80
    targetPort: 8080
EOF

# Create Route
CLUSTER_DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}' 2>/dev/null || echo "")
cat <<EOF | oc apply -n "$DEV_NS" -f -
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: ${NAME}
spec:
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
  port:
    targetPort: 8080
  to:
    kind: Service
    name: ${NAME}
EOF

echo ""
echo "Waiting for pod..."
oc rollout status deployment/${NAME} -n "$DEV_NS" --timeout=60s 2>/dev/null || true

ROUTE=$(oc get route ${NAME} -n "$DEV_NS" -o jsonpath='{.spec.host}' 2>/dev/null || echo "pending")
echo ""
echo "=========================================="
echo "Basic campaign deployed!"
echo "=========================================="
echo "URL: https://${ROUTE}"
echo ""

# KAgenti Platform Setup

Deploy [KAgenti](https://github.com/kagenti/kagenti) alongside the marketing assistant for Kubernetes-native agent discovery, interactive chat, and zero-trust security.

## What KAgenti Provides

| Capability | How It Works |
|------------|-------------|
| **Agent Discovery** | KAgenti operator reads `kagenti.io/type: agent` labels and auto-creates AgentCard CRDs |
| **Tool Discovery** | Same for `kagenti.io/type: tool` labels on MCP servers |
| **Interactive Chat** | KAgenti UI lets you chat with any discovered agent (our agents support dual-mode input) |
| **Zero-Trust Auth** | AuthBridge sidecars validate JWTs inbound, exchange tokens outbound via Keycloak |
| **MCP Inspector** | Browse and test MCP tools from the KAgenti dashboard |

## Architecture

```
KAgenti UI ─── Keycloak ─── SPIRE
    │              │
    │              │ (JWT tokens)
    ▼              ▼
┌─────────────────────────────────┐
│  App Namespace                  │
│                                 │
│  [All 5 agents]    ← discovery labels (kagenti.io/type: agent)
│  [2 MCP tools]     ← discovery labels (kagenti.io/type: tool)
│                                 │
│  [Customer Analyst] ← AuthBridge sidecar (inject labels, demo target)
│  [MongoDB MCP]      ← AuthBridge routes (token exchange target)
│                                 │
│  [Campaign API]     ← NO sidecar (internal gateway)
│  [Event Hub]        ← NO sidecar (SSE broadcaster)
│  [Frontend]         ← NO sidecar (static nginx)
└─────────────────────────────────┘
```

Only **customer-analyst** has AuthBridge injection labels (`kagenti.io/inject`, `kagenti.io/spire`) for the demo. This avoids breaking internal A2A calls on other agents while demonstrating the zero-trust flow:

1. User chats with Customer Analyst from KAgenti UI (JWT attached)
2. AuthBridge validates the JWT inbound
3. Customer Analyst calls MongoDB MCP
4. AuthBridge exchanges the token (target audience: `mongodb-tool`)
5. MongoDB MCP reads `preferred_username` from the exchanged token and filters data

## Installation via deploy.sh

The easiest path is to run `./deploy.sh` and answer **y** at Step 6:

```
--- Step 6: KAgenti Platform ---

Deploy KAgenti platform (agent discovery + zero-trust auth)? (y/N): y
```

This handles everything: Helm installs, SPIRE SCC fixes, Keycloak configuration, AuthBridge config patching.

## Manual Installation

If you prefer to install KAgenti separately:

### Prerequisites

```bash
# Verify tools
oc version    # >= 4.19
helm version  # >= 3.18.0, < 4

# Must be cluster-admin
oc whoami
oc auth can-i '*' '*' --all-namespaces
```

### Step 1: Remove Existing cert-manager

KAgenti installs its own cert-manager. Check for conflicts:

```bash
oc get all -n cert-manager-operator
oc get all -n cert-manager
```

If present, uninstall via OpenShift Console (Operators > Installed Operators > cert-manager > Uninstall), then:

```bash
kubectl delete deploy cert-manager cert-manager-cainjector cert-manager-webhook -n cert-manager
kubectl delete ns cert-manager-operator cert-manager
```

### Step 2: Enable OVN Local Gateway Mode

Required for Istio Ambient mesh:

```bash
NETWORK_TYPE=$(oc get network.config/cluster -o jsonpath='{.spec.networkType}')
if [ "$NETWORK_TYPE" = "OVNKubernetes" ]; then
    oc patch network.operator.openshift.io cluster --type=merge \
        -p '{"spec":{"defaultNetwork":{"ovnKubernetesConfig":{"gatewayConfig":{"routingViaHost":true}}}}}'
fi
```

### Step 3: Set Trust Domain

```bash
export DOMAIN=$(oc get ingresses.config/cluster -o jsonpath='{.spec.domain}')
echo "Trust domain: $DOMAIN"
```

### Step 4: Install Helm Charts

```bash
# Get latest KAgenti release
KAGENTI_TAG=$(git ls-remote --tags --sort="v:refname" \
    https://github.com/kagenti/kagenti.git | tail -n1 | \
    sed 's|.*refs/tags/v||; s/\^{}//')

# Install dependencies (SPIRE, Keycloak, Istio, cert-manager)
helm install --create-namespace -n kagenti-system kagenti-deps \
    oci://ghcr.io/kagenti/kagenti/kagenti-deps \
    --version "${KAGENTI_TAG}" \
    --set spire.trustDomain="${DOMAIN}" \
    --wait --timeout 10m

# Install MCP Gateway
GATEWAY_TAG=$(skopeo list-tags docker://ghcr.io/kagenti/charts/mcp-gateway | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['Tags'][-1])")
helm install mcp-gateway oci://ghcr.io/kagenti/charts/mcp-gateway \
    --create-namespace --namespace mcp-system \
    --version "${GATEWAY_TAG}" \
    --wait --timeout 5m

# Install KAgenti (UI, operator)
helm upgrade --install --create-namespace -n kagenti-system \
    kagenti oci://ghcr.io/kagenti/kagenti/kagenti \
    --version "${KAGENTI_TAG}" \
    --set agentOAuthSecret.spiffePrefix="spiffe://${DOMAIN}/sa" \
    --set uiOAuthSecret.useServiceAccountCA=false \
    --set agentOAuthSecret.useServiceAccountCA=false \
    --wait --timeout 10m
```

### Step 5: Fix SPIRE DaemonSets (if needed)

```bash
# Check SPIRE status
oc get daemonsets -n zero-trust-workload-identity-manager

# If Current=0 or Ready=0, fix SCC:
oc adm policy add-scc-to-user privileged -z spire-agent \
    -n zero-trust-workload-identity-manager
oc rollout restart daemonsets -n zero-trust-workload-identity-manager spire-agent

oc adm policy add-scc-to-user privileged -z spire-spiffe-csi-driver \
    -n zero-trust-workload-identity-manager
oc rollout restart daemonsets -n zero-trust-workload-identity-manager spire-spiffe-csi-driver
```

### Step 6: Configure App Namespace

```bash
NAMESPACE=0-marketing-assistant-demo  # or your namespace

# Create keycloak-admin-secret
oc create secret generic keycloak-admin-secret -n "${NAMESPACE}" \
    --from-literal=KEYCLOAK_ADMIN_USERNAME=admin \
    --from-literal=KEYCLOAK_ADMIN_PASSWORD=admin \
    --dry-run=client -o yaml | oc apply -f -

# Apply AuthBridge CRB
sed "s/NAMESPACE_PLACEHOLDER/${NAMESPACE}/" k8s/kagenti/crb.yaml | oc apply -f -

# Apply KAgenti ConfigMaps
oc apply -k k8s/kagenti/ -n "${NAMESPACE}"

# Patch AuthBridge config with Keycloak URLs
KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')
oc patch configmap authbridge-config -n "${NAMESPACE}" --type=merge \
    -p "{\"data\":{
        \"ISSUER\":\"https://${KEYCLOAK_ROUTE}/realms/kagenti\",
        \"KEYCLOAK_URL\":\"http://keycloak.keycloak.svc.cluster.local:8080\",
        \"TOKEN_URL\":\"http://keycloak.keycloak.svc.cluster.local:8080/realms/kagenti/protocol/openid-connect/token\"
    }}"
```

### Step 7: Configure Keycloak Realm

The Helm charts install Keycloak with a default `master` realm, but the app needs specific clients, users, and scopes in a `kagenti` realm. `deploy.sh` Step 6d handles this automatically via the Keycloak Admin REST API. If doing it manually:

```bash
KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')
FRONTEND_HOST=$(oc get route frontend -n "${NAMESPACE}" -o jsonpath='{.spec.host}')

# Get admin token
KC_TOKEN=$(curl -sk -X POST "https://${KEYCLOAK_ROUTE}/realms/master/protocol/openid-connect/token" \
    -d "client_id=admin-cli&username=admin&password=admin&grant_type=password" | \
    python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

KC_API="https://${KEYCLOAK_ROUTE}/admin/realms"

# Create kagenti realm
curl -sk -X POST "${KC_API}" \
    -H "Authorization: Bearer ${KC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"realm":"kagenti","enabled":true}'

# Create simon-casino-ui client (public, for React Dashboard SSO)
curl -sk -X POST "${KC_API}/kagenti/clients" \
    -H "Authorization: Bearer ${KC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{
        \"clientId\": \"simon-casino-ui\",
        \"publicClient\": true,
        \"standardFlowEnabled\": true,
        \"rootUrl\": \"https://${FRONTEND_HOST}\",
        \"redirectUris\": [\"https://${FRONTEND_HOST}/*\"],
        \"webOrigins\": [\"https://${FRONTEND_HOST}\"],
        \"attributes\": {\"pkce.code.challenge.method\": \"S256\"}
    }"

# Create mongodb-tool client (confidential, for AuthBridge token exchange)
curl -sk -X POST "${KC_API}/kagenti/clients" \
    -H "Authorization: Bearer ${KC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"clientId":"mongodb-tool","publicClient":false,"serviceAccountsEnabled":true,"standardFlowEnabled":false}'

# Create demo users
curl -sk -X POST "${KC_API}/kagenti/users" \
    -H "Authorization: Bearer ${KC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","enabled":true,"firstName":"Admin","lastName":"User",
         "email":"admin@simon-casino.example.com","emailVerified":true,
         "credentials":[{"type":"password","value":"admin","temporary":false}]}'

curl -sk -X POST "${KC_API}/kagenti/users" \
    -H "Authorization: Bearer ${KC_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"username":"demo-user","enabled":true,"firstName":"Demo","lastName":"User",
         "email":"demo-user@simon-casino.example.com","emailVerified":true,
         "credentials":[{"type":"password","value":"password","temporary":false}]}'
```

### Step 8: Verify

```bash
# KAgenti UI
KAGENTI_URL=$(oc get route kagenti-ui -n kagenti-system -o jsonpath='{.spec.host}')
echo "KAgenti UI: https://${KAGENTI_URL}"

# Keycloak
KEYCLOAK_URL=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')
echo "Keycloak: https://${KEYCLOAK_URL}"
echo "Credentials: admin / admin"
```

## MCP Service Naming Workaround

The KAgenti UI hardcodes MCP tool service discovery as `{service-name}-mcp` ([source](https://github.com/kagenti/kagenti/blob/main/kagenti/ui-v2/src/pages/ToolDetailPage.tsx#L292-L299)). Since our services are already named `mongodb-mcp` and `imagegen-mcp`, KAgenti looks for `mongodb-mcp-mcp` and `imagegen-mcp-mcp`.

Duplicate K8s Services with the `-mcp` suffix are included in the manifests as a workaround. No action needed -- they're applied automatically.

## AuthBridge: Enabling Sidecars

AuthBridge injection is controlled by pod labels. Currently only **customer-analyst** has injection labels (set to `disabled` by default):

```yaml
# In k8s/base/agents/customer-analyst.yaml
kagenti.io/inject: disabled    # Change to "enabled" to inject AuthBridge
kagenti.io/spire: disabled     # Change to "enabled" for SPIRE identity
```

To enable for the demo:

```bash
# Enable AuthBridge on customer-analyst
oc patch deployment customer-analyst -n $NAMESPACE --type=json \
    -p '[{"op":"replace","path":"/spec/template/metadata/labels/kagenti.io~1inject","value":"enabled"}]'
```

**Warning**: Enabling injection on agents that receive internal A2A calls (e.g., Campaign Director) will break the app unless internal calls carry valid JWTs. See "Production Hardening" below.

## Production Hardening (Optional)

For production deployments requiring zero-trust on all internal calls:

1. **Service account tokens**: Modify Campaign API and Campaign Director to obtain Keycloak service account tokens at startup and attach them to all outgoing A2A calls
2. **Enable injection on all agents**: Set `kagenti.io/inject: enabled` on all agent deployments
3. **Configure audience scopes**: Register each agent as a Keycloak client with appropriate audience scopes

This requires code changes in `services/campaign-api/app.py` and `services/campaign-director/agent.py` to inject tokens into httpx calls.

## Troubleshooting

### SPIRE daemonsets not ready (Current=0)
Usually an SCC issue. See Step 5 above.

### KAgenti UI shows no agents
Check labels: `oc get deployments -n $NAMESPACE --show-labels | grep kagenti`
Agents need `kagenti.io/type: agent` label.

### "Connection refused" when chatting with agent from KAgenti UI
The KAgenti UI connects to agents via their K8s Service on port 8080 (the `a2a` named port). Verify the service exists and resolves:
```bash
oc get svc -n $NAMESPACE | grep campaign-director
```

### AuthBridge 401 on internal calls
Internal services (Campaign API, Campaign Director) calling agents with AuthBridge sidecars will get 401 if they don't include JWTs. Keep `kagenti.io/inject: disabled` on agents that receive internal calls, or implement service account token injection.

### cert-manager conflicts
KAgenti requires its own cert-manager. If you see cert-manager errors, ensure the Red Hat cert-manager operator is fully removed before installing KAgenti.

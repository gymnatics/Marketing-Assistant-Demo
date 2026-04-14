# SSO Integration Guide

Single Sign-On for the React Dashboard using Keycloak (deployed by KAgenti).

## Prerequisites

- KAgenti platform deployed (see [KAGENTI-SETUP.md](KAGENTI-SETUP.md))
- Keycloak running and accessible

## How It Works

The SSO integration is **graceful** — when Keycloak is not configured, the app works without authentication (same as `main` branch).

```
React Dashboard
    │
    ├── docker-entrypoint.sh generates keycloak-config.js from env vars
    ├── index.html loads keycloak-config.js (sets window.__KEYCLOAK_URL__)
    ├── KeycloakProvider.tsx initializes keycloak-js if URL is set
    ├── authFetch.ts attaches Bearer token to all API calls
    │
    ▼
nginx (Authorization header forwarded)
    │
    ▼
Campaign API (extracts Authorization, passes to A2A calls)
    │
    ▼
Campaign Director / Agents (AuthBridge validates if sidecars present)
```

## Configuration

### Environment Variables

Set these in the ConfigMap or as environment variables on the frontend deployment:

| Variable | Default | Purpose |
|----------|---------|---------|
| `KEYCLOAK_URL` | `""` (disabled) | External Keycloak URL (e.g., `https://keycloak-keycloak.apps.cluster.example.com`) |
| `KEYCLOAK_REALM` | `kagenti` | Keycloak realm name |
| `KEYCLOAK_CLIENT_ID` | `simon-casino-ui` | Public client ID for the dashboard |

When `KEYCLOAK_URL` is empty, SSO is disabled and the app works without login.

### deploy.sh Integration

If you deploy KAgenti via `deploy.sh` Step 6, the Keycloak URL is auto-detected. You just need to restart the frontend to pick up the new config:

```bash
oc rollout restart deployment/frontend -n $NAMESPACE
```

### Manual Configuration

If configuring manually, patch the ConfigMap:

```bash
KEYCLOAK_ROUTE=$(oc get route keycloak -n keycloak -o jsonpath='{.spec.host}')

oc patch configmap marketing-assistant-config -n $NAMESPACE --type=merge \
    -p "{\"data\":{\"KEYCLOAK_URL\":\"https://${KEYCLOAK_ROUTE}\"}}"

oc rollout restart deployment/frontend -n $NAMESPACE
```

## Keycloak Client Setup

The `simon-casino-ui` client must be registered in Keycloak. If using KAgenti's Keycloak:

1. Open Keycloak admin console: `https://<keycloak-route>/admin/kagenti/console/`
2. Go to **Clients** > **Create client**
3. Configure:
   - **Client ID**: `simon-casino-ui`
   - **Client type**: OpenID Connect
   - **Client authentication**: OFF (public client)
4. In **Settings**:
   - **Root URL**: `https://frontend-<namespace>.<cluster-domain>`
   - **Valid redirect URIs**: `https://frontend-<namespace>.<cluster-domain>/*`
   - **Web origins**: `https://frontend-<namespace>.<cluster-domain>`
   - **Standard flow**: Enabled
   - **Direct access grants**: Disabled
5. Save

### Creating Demo Users

In the `kagenti` realm:

1. Go to **Users** > **Add user**
2. Create users:
   - `admin` / `admin` (full access)
   - `demo-user` / `password` (demo access)
3. Set passwords in the **Credentials** tab (set "Temporary" to OFF)

## Token Flow

1. User opens the dashboard
2. `KeycloakProvider` checks for an existing Keycloak session (`check-sso` mode)
3. If not authenticated, a "Sign In" button appears in the top nav
4. Clicking "Sign In" redirects to Keycloak login page
5. After login, Keycloak returns an access token + refresh token
6. `authFetch` automatically attaches `Authorization: Bearer <token>` to all API calls
7. The nginx proxy forwards the header to Campaign API
8. Campaign API forwards the header to A2A agent calls via httpx
9. If AuthBridge sidecars are present on agents, they validate the JWT inbound
10. Token auto-refreshes when it expires (30-second buffer)

## Troubleshooting

### "Sign In" button doesn't appear
The `enabled` flag in `KeycloakProvider` is false when `KEYCLOAK_URL` is empty. Check:
```bash
oc exec deployment/frontend -n $NAMESPACE -- cat /usr/share/nginx/html/keycloak-config.js
```

### Redirect fails after login
Check that the Keycloak client's **Valid redirect URIs** matches your frontend Route URL exactly (including `https://`).

### CORS errors in browser console
Ensure the Keycloak client's **Web origins** includes your frontend Route URL.

### Token not reaching agents
Check nginx config forwards the header: `proxy_set_header Authorization $http_authorization;`
Check Campaign API passes it: look for `auth_header` parameter in `call_director_a2a_sync`.

### Login works but user shows as "Unknown"
The Keycloak token may not include `name` or `preferred_username` claims. Ensure the user has these attributes set in Keycloak.

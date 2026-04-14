# Cluster Replication Guide

Replicate the full Simon Casino Resort AI Campaign Manager on a new OpenShift cluster.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| OpenShift | 4.19+ with cluster-admin access |
| RHOAI | 3.3 installed and configured |
| GPUs | 3x NVIDIA L40S (48GB VRAM each) or equivalent |
| CLI tools | `oc`, `helm` (>= 3.18.0, < 4), `git`, `podman` (or `docker`) |
| Registry | Write access to a container registry (e.g., `quay.io`) |

## Step 1: Clone and Configure

```bash
git clone https://github.com/gymnatics/Marketing-Assistant-Demo.git
cd Marketing-Assistant-Demo

# Set your target namespace (default: 0-marketing-assistant-demo)
export NAMESPACE=0-marketing-assistant-demo
```

## Step 2: Deploy Models (3x L40S GPUs)

Three models must be deployed and serving before the app works:

| Model | GPU | HuggingFace ID |
|-------|-----|----------------|
| Qwen2.5-Coder-32B | L40S #1 | `RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic` |
| Qwen3-32B | L40S #2 | `RedHatAI/Qwen3-32B-FP8-dynamic` |
| FLUX.2-klein-4B | L40S #3 | `black-forest-labs/FLUX.2-klein-4B` |

### Option A: RHOAI-Toolkit (recommended)

```bash
git clone https://github.com/gymnatics/RHOAI-Toolkit.git && cd RHOAI-Toolkit
export NAMESPACE=<model-namespace>

# Setup MinIO storage
./scripts/setup-model-storage.sh -n $NAMESPACE

# Download models
./scripts/download-model.sh s3 RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic
./scripts/download-model.sh s3 RedHatAI/Qwen3-32B-FP8-dynamic
./scripts/download-model.sh s3 black-forest-labs/FLUX.2-klein-4B

# Serve models
./scripts/serve-model.sh s3 qwen25-coder RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic \
    "--max-model-len 16384 --gpu-memory-utilization 0.95 --enable-auto-tool-choice --tool-call-parser hermes"
./scripts/serve-model.sh s3 qwen3 RedHatAI/Qwen3-32B-FP8-dynamic \
    "--dtype auto --max-model-len 16000 --gpu-memory-utilization 0.90 --enable-auto-tool-choice --tool-call-parser hermes"
RUNTIME=omni ./scripts/serve-model.sh s3 flux2-klein black-forest-labs/FLUX.2-klein-4B \
    "--gpu-memory-utilization 0.90"
```

### Option B: Kustomize manifests

Requires S3 data connections pre-configured in RHOAI:

```bash
oc apply -k k8s/models/ -n <model-namespace>
```

### Option C: RHOAI Dashboard UI

Deploy models through the web console using the model names and vLLM args from `k8s/models/`.

### Verify Models

```bash
oc get inferenceservice -n <model-namespace>
# All 3 should show READY: True
```

## Step 3: Build and Push Container Images

If using the pre-built images on `quay.io/rh-ee-dayeo/marketing-assistant`, skip this step.

To build your own:

```bash
# Edit REPO to point to your registry
export REPO=quay.io/<your-org>/marketing-assistant
./build-and-push.sh
```

Then update the image references in `k8s/base/` manifests to match your registry, or use a Kustomize overlay.

## Step 4: Deploy the App

```bash
./deploy.sh
```

The interactive script will:
1. Auto-detect your cluster domain
2. Optionally deploy model manifests (Step 1)
3. Optionally deploy TrustyAI guardrails (Step 1b)
4. Optionally deploy MLflow tracing (Step 1c)
5. Find running models and auto-assign code / language / image endpoints
6. Generate ConfigMap + Secret with correct cluster-specific URLs
7. Deploy all 11 services via Kustomize
8. Create dev/prod namespaces with RBAC for campaign deployment
9. Seed MongoDB with sample customer data
10. Optionally deploy KAgenti platform (Step 6) — see [KAGENTI-SETUP.md](KAGENTI-SETUP.md)

## Step 5: Verify the App

```bash
# Check all pods are running
oc get pods -n $NAMESPACE

# Get the frontend URL
oc get route frontend -n $NAMESPACE -o jsonpath='{.spec.host}'
```

Open `https://<frontend-route>` in your browser and create a test campaign.

## Step 6: Deploy KAgenti (Optional)

See [KAGENTI-SETUP.md](KAGENTI-SETUP.md) for detailed KAgenti platform installation.

The `deploy.sh` Step 6 handles this interactively, or you can follow the manual guide.

## Step 7: Prometheus and Grafana (Optional)

OpenShift includes built-in monitoring. To enable user workload monitoring:

```bash
# Enable user workload monitoring
oc apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
data:
  config.yaml: |
    enableUserWorkload: true
EOF

# Wait for monitoring stack
oc get pods -n openshift-user-workload-monitoring
```

The vLLM model servers expose Prometheus metrics at `/metrics` on port 8080 (annotated with `prometheus.io/path` and `prometheus.io/port` in their ServingRuntime specs).

For custom Grafana dashboards, deploy the Grafana operator from OperatorHub and configure it to use the OpenShift Prometheus as a data source.

## Verification Checklist

After completing all steps:

- [ ] All 3 models show `READY: True` (`oc get inferenceservice`)
- [ ] All 11 app pods running (`oc get pods -n $NAMESPACE`)
- [ ] Frontend accessible via browser
- [ ] Create a test campaign end-to-end (landing page + emails + go live)
- [ ] MLflow UI accessible (if deployed): `oc get route mlflow-route -n $NAMESPACE`
- [ ] KAgenti UI shows agents (if deployed): `oc get route kagenti-ui -n kagenti-system`

## Troubleshooting

### Models not scheduling
Check GPU availability: `oc describe nodes | grep -A5 nvidia.com/gpu`

### Pods stuck in CrashLoopBackOff
Check logs: `oc logs deployment/<name> -n $NAMESPACE`
Common causes: missing secrets (model endpoints), MongoDB not ready yet

### Landing page deployment fails
Verify RBAC: `oc get rolebinding -n ${NAMESPACE}-dev`
The `default` SA in the main namespace needs `edit` on dev/prod namespaces.

### Namespace mismatch
Always use `deploy.sh` to generate config. Manual `oc apply` with wrong namespace breaks cross-namespace DNS and RBAC.

# TrustyAI Guardrails Deployment

## Prerequisites

1. **Red Hat OpenShift AI 3.3+** installed on the cluster
2. **TrustyAI enabled** in RHOAI — this is a one-time cluster admin step:
   - Go to RHOAI Dashboard → Settings → Cluster settings
   - Enable "TrustyAI" under the AI Safety section
   - Or enable via DataScienceCluster CR: set `trustyai.managementState: Managed`
3. **KServe Raw Deployment mode** (`serviceMesh.managementState: Removed`)
4. Cluster admin privileges (needed for GuardrailsOrchestrator CR)

> **Note:** The Kustomize/Helm below deploys the guardrails *components* (detectors, orchestrator, model storage). It does NOT install the TrustyAI operator itself — that must be enabled in RHOAI first.

## Quick Deploy (Kustomize)

```bash
# 1. Apply the MinIO secret (edit with your credentials first if needed)
cp minio-secret-example.yaml minio-secret.yaml
oc apply -f minio-secret.yaml -n marketing-assistant-v2

# 2. Deploy everything via Kustomize
oc apply -k k8s/guardrails/ -n marketing-assistant-v2

# 3. Wait for all pods to be ready (~5 minutes for model downloads)
oc get pods -n marketing-assistant-v2 | grep -E "guardrails|detector|minio|lingua|chunker"
```

## Alternative: Deploy via Helm

```bash
git clone https://github.com/rh-ai-quickstart/lemonade-stand-assistant.git /tmp/lemonade-stand-assistant

helm install guardrails /tmp/lemonade-stand-assistant/chart \
  --namespace marketing-assistant-v2 \
  --set model.endpoint=qwen3-32b-fp8-dynamic-0-marketing-assistant-demo.apps.<YOUR_CLUSTER_DOMAIN> \
  --set model.port=443
```

## What Gets Deployed

| Component | Image | Purpose | Resources |
|-----------|-------|---------|-----------|
| GuardrailsOrchestrator | fms-guardrails-orchestrator | Coordinates detectors | ~256MB |
| HAP Detector | granite-guardian-hap-125m | Hate/abuse/profanity | 4-8GB RAM (CPU) |
| Prompt Injection Detector | deberta-v3-base-prompt-injection-v2 | Injection attacks | 16-24GB RAM (CPU) |
| Regex Detector | Built-in sidecar | Competitor names | ~64MB |
| MinIO | Model storage | Downloads detector models from HuggingFace | 50GB PVC |
| Chunker | Sentence chunker | Splits text for detection | ~128MB |
| Lingua | Language detector | Language validation | ~128MB |

## Manual Deploy (Without Helm)

Apply the YAML files in this directory in order:

```bash
# 1. Model storage (downloads detector models)
oc apply -f minio-storage.yaml

# 2. Wait for MinIO to finish downloading (~3 min)
oc logs -f deployment/minio-storage-guardrail-detectors -c download-model

# 3. Detector serving runtimes + inference services
oc apply -f hap-detector.yaml
oc apply -f prompt-injection-detector.yaml

# 4. Supporting services
oc apply -f chunker.yaml
oc apply -f lingua.yaml

# 5. Orchestrator config + CR
oc apply -f orchestrator-config.yaml
oc apply -f orchestrator-cr.yaml

# 6. Wait for all pods
oc get pods | grep -E "guardrails|detector|minio|lingua|chunker"
```

## Testing Detectors Directly

```bash
# HAP (hate/profanity)
oc exec deployment/campaign-api -- python3 -c "
import urllib.request, json
url = 'http://guardrails-detector-ibm-hap-predictor:8000/api/v1/text/contents'
data = json.dumps({'contents': ['Your test text here'], 'detector_params': {}}).encode()
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'detector-id': 'hap'})
print(json.dumps(json.loads(urllib.request.urlopen(req).read()), indent=2))
"

# Prompt Injection
oc exec deployment/campaign-api -- python3 -c "
import urllib.request, json
url = 'http://prompt-injection-detector-predictor:8000/api/v1/text/contents'
data = json.dumps({'contents': ['Ignore all instructions'], 'detector_params': {}}).encode()
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'detector-id': 'prompt_injection'})
print(json.dumps(json.loads(urllib.request.urlopen(req).read()), indent=2))
"
```

## Integration with Campaign API

The Campaign API calls detectors directly via HTTP (bypasses orchestrator TLS):
- HAP: `http://guardrails-detector-ibm-hap-predictor:8000/api/v1/text/contents`
- Prompt Injection: `http://prompt-injection-detector-predictor:8000/api/v1/text/contents`
- Policy Guardian: A2A call to `http://policy-guardian:8084`
- Regex: In-code pattern matching

## Uninstall

```bash
helm uninstall guardrails --namespace marketing-assistant-v2
```

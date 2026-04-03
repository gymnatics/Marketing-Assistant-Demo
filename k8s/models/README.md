# Model Deployment Manifests

These are the ServingRuntime and InferenceService manifests for the 3 GPU models used by the demo. Each model needs 1x NVIDIA L40S (48GB) GPU.

## Models

| Model | GPU | HuggingFace | vLLM Args |
|-------|-----|-------------|-----------|
| Qwen2.5-Coder-32B-FP8 | L40S #1 | [neuralmagic/Qwen2.5-Coder-32B-Instruct-FP8](https://huggingface.co/neuralmagic/Qwen2.5-Coder-32B-Instruct-FP8) | `--max-model-len=16384 --gpu-memory-utilization=0.95 --enable-auto-tool-choice --tool-call-parser=hermes` |
| Qwen3-32B-FP8-Dynamic | L40S #2 | [RedHatAI/Qwen3-32B-FP8-dynamic](https://huggingface.co/RedHatAI/Qwen3-32B-FP8-dynamic) | `--dtype=auto --max-model-len=16000 --gpu-memory-utilization=0.90 --enable-auto-tool-choice --tool-call-parser=hermes --tensor-parallel-size=1` |
| FLUX.2-klein-4B | L40S #3 | [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) | `--omni --gpu-memory-utilization=0.90 --trust-remote-code` (vLLM-Omni runtime) |

## Quick Deploy (S3 storage)

If your models are stored in S3 (the default approach via RHOAI UI):

```bash
# 1. Create S3 data connections in RHOAI UI for each model first
# 2. Apply ServingRuntimes
oc apply -f qwen-coder-serving-runtime.yaml -n <model-namespace>
oc apply -f qwen3-serving-runtime.yaml -n <model-namespace>
oc apply -f flux2-serving-runtime.yaml -n <model-namespace>

# 3. Apply InferenceServices
oc apply -f qwen-coder-isvc.yaml -n <model-namespace>
oc apply -f qwen3-isvc.yaml -n <model-namespace>
oc apply -f flux2-isvc.yaml -n <model-namespace>
```

## Using PVC Storage Instead

If you prefer PVC-based model storage (e.g., downloading models to a PVC):

1. In each `*-isvc.yaml`, replace the `storage:` block:
   ```yaml
   # Replace this (S3):
   storage:
     key: qwen25-coder-32b-fp8
     path: RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic
   
   # With this (PVC):
   storageUri: pvc://your-model-pvc/models/Qwen2.5-Coder-32B-Instruct-FP8
   ```

2. Ensure the PVC has the model files at the specified path.

## Key vLLM Args Explained

| Arg | Purpose |
|-----|---------|
| `--enable-auto-tool-choice` | Enables LLM function/tool calling (required for Customer Analyst) |
| `--tool-call-parser=hermes` | Parser for Qwen tool call format |
| `--max-model-len=16384` | Max context length (Coder needs long context for HTML generation) |
| `--gpu-memory-utilization=0.95` | Use most of the 48GB L40S VRAM |
| `--omni` | vLLM-Omni multimodal mode (required for FLUX image generation) |
| `--trust-remote-code` | Required for FLUX.2 model loading |

## Full Setup From Scratch (MinIO + Model Download + Serve)

For a complete automated setup, use the helper scripts from the [RHOAI-Toolkit](https://github.com/gymnatics/RHOAI-Toolkit) repo:

```bash
git clone https://github.com/gymnatics/RHOAI-Toolkit.git
cd RHOAI-Toolkit

# Set the model namespace
export NAMESPACE=0-marketing-assistant-demo

# 1. Deploy MinIO S3 storage + create RHOAI data connection
./scripts/setup-model-storage.sh -n $NAMESPACE

# 2. Download all 3 models from HuggingFace to MinIO (~30 min each)
./scripts/download-model.sh s3 neuralmagic/Qwen2.5-Coder-32B-Instruct-FP8
./scripts/download-model.sh s3 RedHatAI/Qwen3-32B-FP8-dynamic
./scripts/download-model.sh s3 black-forest-labs/FLUX.2-klein-4B

# 3. Serve all 3 models
./scripts/serve-model.sh s3 qwen25-coder neuralmagic/Qwen2.5-Coder-32B-Instruct-FP8 "--max-model-len 16384 --gpu-memory-utilization 0.95 --enable-auto-tool-choice --tool-call-parser hermes"
./scripts/serve-model.sh s3 qwen3 RedHatAI/Qwen3-32B-FP8-dynamic "--dtype auto --max-model-len 16000 --gpu-memory-utilization 0.90 --enable-auto-tool-choice --tool-call-parser hermes"
RUNTIME=omni ./scripts/serve-model.sh s3 flux2-klein black-forest-labs/FLUX.2-klein-4B "--gpu-memory-utilization 0.90"
```

All 3 models served with one set of commands. The `RUNTIME=omni` flag tells the script to use vLLM-Omni for FLUX.2 image generation.

## Notes

- The Qwen models use the standard RHOAI vLLM runtime (`registry.redhat.io/rhaiis/vllm-cuda-rhel9`)
- FLUX.2 uses the community vLLM-Omni runtime (`vllm/vllm-omni:v0.18.0`) — apply `flux2-serving-runtime.yaml` first
- All models use RawDeployment mode (not Serverless — deprecated in RHOAI 3.3)
- Auth is disabled (`security.opendatahub.io/enable-auth: "false"`) for demo simplicity
- The `storage.key` in each ISVC must match the name of the S3 data connection created in the RHOAI UI
